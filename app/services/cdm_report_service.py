# -*- coding: utf-8 -*-
"""CDM 归因诊断页的取数：提交列表与单条摘要。

与 `cdm_service` 分开：那个是纯函数规则引擎、不碰数据库；这里是请求侧的取数装配。
本轮做到「列表 + 顶部四指标摘要」，报告详情（缺陷标签明细、特征矩阵、老师修正
记录）不在范围内，口径见 DOC_ISSUES 第 54、55 条。
"""
import math
import statistics

from sqlalchemy.orm import Session

from app.common.errors import BusinessError
from app.repositories import homeworks_repo
from app.schemas.cdm import (
    CdmDefect,
    CdmDefectList,
    CdmFeatureMatrixData,
    CdmPitchPattern,
    CdmSubmissionItem,
    CdmSubmissionList,
    CdmSubmissionSummary,
)
from app.services import cdm_service

# 与页面徽标、缺陷分组同一阈值：「置信度 > 0.7」在页面上按 >= 0.70 实现。
HIGH_CONFIDENCE = 0.70


def _number(value) -> float | None:
    """JSONB 里取有限数字；bool / 字符串 / NaN / Inf 一律当没有数据源。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def _string(value) -> str | None:
    """只接受真正的字符串；数字/对象等异常形态当没有数据源，不强行转换。"""
    return value if isinstance(value, str) else None


def _features(value) -> dict | None:
    """特征键值对原样透出，只保留能直接渲染的标量值。"""
    if not isinstance(value, dict):
        return None
    return {
        str(key): item
        for key, item in value.items()
        if item is None or isinstance(item, (str, int, float, bool))
    }


def submission_defects(db: Session, submission_id: int) -> CdmDefectList:
    """单条提交的缺陷标签明细（功能 4.6 的「CDM 缺陷标签诊断」）。

    取数口径：
    - `ai_detail.defects` 不是数组 → `defects=null`（没有数据源）；
    - 数组里的非对象元素跳过，字段缺失回 null，分析管线没写的字段不由后端补词；
    - `id` 统一转字符串，页面用它做本地处理去重与 DOM 定位。

    确认/修正/忽略仍是页面本会话的本地操作，库里没有标签修正表（第 55 条）。
    """
    sub = homeworks_repo.get_cdm_submission(db, submission_id)
    if sub is None:
        raise BusinessError(404, "提交不存在")

    detail = sub.ai_detail if isinstance(sub.ai_detail, dict) else {}
    raw = detail.get("defects")
    if not isinstance(raw, list):
        return CdmDefectList(submission_id=sub.id, defects=None)

    defects = [
        CdmDefect(
            id=None if item.get("id") is None else str(item.get("id")),
            label=_string(item.get("label")),
            status=_string(item.get("status")),
            category=_string(item.get("category")),
            evidence=_string(item.get("evidence")),
            features=_features(item.get("features")),
            confidence=_number(item.get("confidence")),
        )
        for item in raw
        if isinstance(item, dict)
    ]
    return CdmDefectList(submission_id=sub.id, defects=defects)


def submission_features(db: Session, submission_id: int) -> CdmFeatureMatrixData:
    """单条提交的 CDM 输入特征矩阵（功能 4.6 的「CDM 输入特征矩阵」）。

    与 F5 的 `feature_matrix` 同口径：`ai_detail.featureMatrix` 是 dict 就原样
    透传，保留驼峰键名；不是 dict 回 null（没有数据源）。旧种子提交（23–27）
    有这份数据，新提交（49 起）没有——页面按 null 出空态，不拿别的字段拼。
    """
    sub = homeworks_repo.get_cdm_submission(db, submission_id)
    if sub is None:
        raise BusinessError(404, "提交不存在")

    detail = sub.ai_detail if isinstance(sub.ai_detail, dict) else {}
    matrix = detail.get("featureMatrix")
    return CdmFeatureMatrixData(
        submission_id=sub.id,
        feature_matrix=matrix if isinstance(matrix, dict) else None,
    )


def _deviations(words) -> list[float]:
    """逐字偏差的有效值；跳过非 dict、缺字段、非数值与非有限数。"""
    if not isinstance(words, list):
        return []
    out: list[float] = []
    for item in words:
        if not isinstance(item, dict):
            continue
        value = _number(item.get("deviation_cents"))
        if value is not None:
            out.append(value)
    return out


def _pitch_trend(median: float, std: float) -> str:
    """按 CDM 规则判模式：先看整体偏差方向，再看离散程度。

    与 `cdm_service.build` 共用同一组阈值。规则引擎允许「整体偏低 + 随机波动」
    同时成立，而卡片只能显示一个模式，因此系统性偏差优先于随机波动。
    """
    if median <= -cdm_service.PITCH_BIAS_CENTS:
        return "systematic_low"
    if median >= cdm_service.PITCH_BIAS_CENTS:
        return "systematic_high"
    if std >= cdm_service.PITCH_STD_CENTS:
        return "random"
    return "stable"


def submission_pitch_pattern(db: Session, submission_id: int) -> CdmPitchPattern:
    """单条提交的音高偏差模式（功能 4.6 的「音高偏差模式分析」）。

    优先用 `ai_detail.featureMatrix`；没有可用值时回退到 `ai_detail.words` 的
    逐字偏差。两条来源的字段面不同：逐字来源没有高/低音区偏差（没有可靠的
    声区划分），对应字段回 null，页面不画那两条。
    """
    sub = homeworks_repo.get_cdm_submission(db, submission_id)
    if sub is None:
        raise BusinessError(404, "提交不存在")

    detail = sub.ai_detail if isinstance(sub.ai_detail, dict) else {}
    fm = detail.get("featureMatrix")
    if isinstance(fm, dict):
        trend = fm.get("pitchTrend")
        pattern = CdmPitchPattern(
            submission_id=sub.id,
            source="feature_matrix",
            trend=trend if isinstance(trend, str) else None,
            mean=_number(fm.get("pitchMean")),
            median=None,
            std=_number(fm.get("pitchStd")),
            high_pitch_bias=_number(fm.get("highPitchBias")),
            low_pitch_bias=_number(fm.get("lowPitchBias")),
            word_count=None,
        )
        # 矩阵存在但一个音高字段都没有时，继续尝试逐字偏差。
        if any(v is not None for v in (
            pattern.trend, pattern.mean, pattern.std,
            pattern.high_pitch_bias, pattern.low_pitch_bias,
        )):
            return pattern

    deviations = _deviations(detail.get("words"))
    if not deviations:
        return CdmPitchPattern(
            submission_id=sub.id, source=None, trend=None, mean=None, median=None,
            std=None, high_pitch_bias=None, low_pitch_bias=None, word_count=None,
        )

    median = statistics.median(deviations)
    std = statistics.pstdev(deviations)
    return CdmPitchPattern(
        submission_id=sub.id,
        source="words",
        trend=_pitch_trend(median, std),
        mean=round(statistics.fmean(deviations), 2),
        median=round(median, 2),
        std=round(std, 2),
        high_pitch_bias=None,
        low_pitch_bias=None,
        word_count=len(deviations),
    )


def list_submissions(db: Session) -> CdmSubmissionList:
    """有 CDM 归因数据的作业提交，最新在前（默认选中第一条）。

    取数与口径全在 `homeworks_repo.get_cdm_submissions`，这里只做装配。
    """
    return CdmSubmissionList(
        submissions=[
            CdmSubmissionItem(
                submission_id=sub.id,
                student_id=sub.student_id,
                student_name=name,
                student_avatar=avatar,
                student_level=level,
                homework_title=title,
                submitted_at=sub.submitted_at,
                ai_score=sub.ai_score,
            )
            # 元组顺序是 (提交, 姓名, 等级, 头像, 作业标题)，与仓储 SELECT 逐列对齐
            for sub, name, level, avatar, title in homeworks_repo.get_cdm_submissions(db)
        ]
    )


def submission_summary(db: Session, submission_id: int) -> CdmSubmissionSummary:
    """单条提交的四个顶部指标（功能 4.6 的摘要部分）。

    - `ai_score`：AI 初评分，原样取 `submissions.ai_score`。
    - `overall_confidence`：`ai_detail.overallConfidence`，非有限数值回 null。
    - `defect_count`：`ai_detail.defects` 的数组长度；键不存在或不是数组回 null，
      空数组是 0（查了没缺陷）。
    - `high_confidence_count`：`defects` 里 `confidence >= 0.70` 的条数；缺
      confidence 或值非有限数字的条目不计数。

    「已处理/总标签」里的**已处理**不进本接口：库里没有缺陷标签的修正表，
    本轮由页面按本次会话的本地操作计数（刷新归零），见 DOC_ISSUES 第 55 条。
    """
    sub = homeworks_repo.get_cdm_submission(db, submission_id)
    if sub is None:
        raise BusinessError(404, "提交不存在")

    detail = sub.ai_detail if isinstance(sub.ai_detail, dict) else {}
    defects = detail.get("defects")
    defect_count = len(defects) if isinstance(defects, list) else None
    high_count = None
    if isinstance(defects, list):
        high_count = sum(
            1
            for item in defects
            if isinstance(item, dict)
            and (conf := _number(item.get("confidence"))) is not None
            and conf >= HIGH_CONFIDENCE
        )

    return CdmSubmissionSummary(
        submission_id=sub.id,
        ai_score=_number(sub.ai_score),
        overall_confidence=_number(detail.get("overallConfidence")),
        defect_count=defect_count,
        high_confidence_count=high_count,
    )
