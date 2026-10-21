# -*- coding: utf-8 -*-
"""CDM 归因诊断：规则引擎 + 置信度（《3-功能清单》4.6）。

输入是 B4 已经算好的五维分数与逐字偏差，不重新解码音频。纯函数、不碰数据库，
所以 worker（分析管线）与脚本（历史回填）可以共用同一套判定。

规则口径是**初始版本、未经真实素材标定**（性质同 parse_service.TOP_DB）：
阈值全部集中在本文件顶部，标定后只改这里。输出的 defect 形状照库里已有的
submissions.ai_detail.defects：{id, label, status, category, evidence, features,
confidence}，前端两处（AI_teacher.html 与 cdm_report.html）不需要分支。

「没有数据源」与「查了是空」的区分沿用项目约定：build() 在既没有维度分、
也没有可用逐字偏差时返回 None；有数据但没触发任何规则返回 defects=[]。
"""

import math
import statistics

# 五维低于该值判为该维度存在缺陷；低于 DIM_HIGH 的给 high，否则 medium。
DIM_THRESHOLD = 50.0
DIM_HIGH = 30.0

# 逐字偏差中位数超过该值判为整体偏高/偏低；超过 HIGH 给 high。
PITCH_BIAS_CENTS = 25.0
PITCH_BIAS_HIGH = 50.0

# 逐字偏差标准差超过该值判为随机波动（不是系统性跑调）；超过 HIGH 给 high。
PITCH_STD_CENTS = 30.0
PITCH_STD_HIGH = 60.0

# 有逐字数据时音准用上面的中位数/标准差判；没有歌词的曲目（Demucs）退回
# 五维里的「音准」总分，标签用既有词表里的「调门不准」。
_DIMENSION_RULES = (
    ("节奏", "节奏感知弱", "节奏"),
    ("气息", "气息支撑不足", "气息"),
    ("咬字", "咬字不清", "咬字"),
    # 分类沿用前端既有词表：拖腔类缺陷在 cdm_report.html 的 mock 里归到「节奏」
    # （如「拖腔时值偏短」），不另造一个页面上没有图标的分类。
    ("拖腔", "拖腔不足", "节奏"),
)


def build(dimensions: dict | None, words: list | None) -> dict | None:
    """五维分数 + 逐字偏差 → {"defects": [...], "overallConfidence": float}。"""
    dims = dimensions if isinstance(dimensions, dict) else {}
    scores = {key: _number(dims.get(key)) for key, _, _ in _DIMENSION_RULES}
    pitch_score = _number(dims.get("音准"))
    deviations = _deviations(words)

    # 既没有可用维度分、也没有可用逐字偏差 → 没有数据源。脏数据（有键但值
    # 全非数值）也走这里，不能返回 defects=[] 冒充「查了没缺陷」。
    if not deviations and pitch_score is None and all(v is None for v in scores.values()):
        return None

    defects: list[dict] = []
    median = statistics.median(deviations) if deviations else None
    std = statistics.pstdev(deviations) if deviations else None

    if median is not None and std is not None:
        if median <= -PITCH_BIAS_CENTS:
            defects.append(_pitch_bias_defect(median, low=True))
        elif median >= PITCH_BIAS_CENTS:
            defects.append(_pitch_bias_defect(median, low=False))
        if std >= PITCH_STD_CENTS:
            defects.append(_pitch_std_defect(std))

    for dimension, label, category in _DIMENSION_RULES:
        score = scores[dimension]
        if score is not None and score < DIM_THRESHOLD:
            defects.append(_dimension_defect(dimension, label, category, score))

    # 没有逐字数据时，音准只能用五维总分兜底；有逐字数据时上面已经判过，
    # 再加一条「调门不准」只会和「整体音准偏低/偏高」重复报同一件事。
    if not deviations and pitch_score is not None and pitch_score < DIM_THRESHOLD:
        defects.append(_dimension_defect("音准", "调门不准", "音准", pitch_score))

    defects.sort(key=lambda d: -d["confidence"])
    for index, defect in enumerate(defects, 1):
        defect["id"] = f"d{index}"
    top = [d["confidence"] for d in defects[:3]]
    return {
        "defects": defects,
        "overallConfidence": round(sum(top) / len(top), 2) if top else 0.0,
    }


def _deviations(words: list | None) -> list[float]:
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


def _number(value) -> float | None:
    """只收真正的有限数值；bool 是 int 的子类，要单独排除。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _confidence(base: float, extras: float) -> float:
    return round(min(0.95, base + extras), 2)


def _pitch_bias_defect(median: float, *, low: bool) -> dict:
    # 「整体音准偏高」不在 cdm_report.html 的 mock 标签表里。E1 只展示文本，
    # 不影响；该页将来接真数据时要把这个标签补进 ALL_DEFECT_LABELS。
    label = "整体音准偏低" if low else "整体音准偏高"
    status = "high" if abs(median) >= PITCH_BIAS_HIGH else "medium"
    direction = "低" if low else "高"
    return {
        "id": "",  # 排序后统一编号
        "label": label,
        "status": status,
        "category": "音准",
        "evidence": (
            f"逐字音准偏差中位数 {median:+.1f}c，整体偏{direction}，"
            f"超过阈值 ±{PITCH_BIAS_CENTS:.0f}c。"
        ),
        "features": {
            "中位偏差": f"{median:+.1f}c",
            "阈值": f"±{PITCH_BIAS_CENTS:.0f}c",
        },
        "confidence": _confidence(0.55, (abs(median) - PITCH_BIAS_CENTS) / 200.0),
    }


def _pitch_std_defect(std: float) -> dict:
    status = "high" if std >= PITCH_STD_HIGH else "medium"
    return {
        "id": "",
        "label": "音准偏差随机",
        "status": status,
        "category": "音准",
        "evidence": (
            f"逐字音准偏差标准差 {std:.1f}c，波动方向不一致，"
            f"超过阈值 {PITCH_STD_CENTS:.0f}c。"
        ),
        "features": {
            "标准差": f"{std:.1f}c",
            "阈值": f"{PITCH_STD_CENTS:.0f}c",
        },
        "confidence": _confidence(0.55, (std - PITCH_STD_CENTS) / 150.0),
    }


def _dimension_defect(dimension: str, label: str, category: str, score: float) -> dict:
    status = "high" if score < DIM_HIGH else "medium"
    return {
        "id": "",
        "label": label,
        "status": status,
        "category": category,
        "evidence": f"{dimension}维度得分 {score:.1f}，低于阈值 {DIM_THRESHOLD:.0f}。",
        "features": {
            "维度得分": f"{score:.1f}",
            "阈值": f"{DIM_THRESHOLD:.0f}",
        },
        "confidence": _confidence(0.55, (DIM_THRESHOLD - score) / 100.0),
    }
