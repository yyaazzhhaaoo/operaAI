# -*- coding: utf-8 -*-
"""CDM 归因诊断页列表接口的出参。

接口清单没有这一条（只定义了逐条提交的 F5），本轮口径见 DOC_ISSUES 第 54 条。
只出顶部学生提交芯片需要的字段；缺陷标签、特征矩阵等报告详情留给后续接口。
"""
from datetime import datetime

from pydantic import BaseModel


class CdmSubmissionItem(BaseModel):
    """一条带 CDM 数据的作业提交。

    姓名/等级/头像都可能为 NULL（students 或 users 缺行），接口不造词，前端兜底
    占位；这与项目「null 表示没有数据源」的约定一致。
    """

    submission_id: int
    student_id: int | None
    student_name: str | None
    student_avatar: str | None
    student_level: str | None
    homework_title: str | None
    submitted_at: datetime | None       # 列可空；出参是 ISO-8601
    ai_score: float | None


class CdmSubmissionList(BaseModel):
    submissions: list[CdmSubmissionItem]


class CdmDefect(BaseModel):
    """一条 CDM 缺陷标签（来自 `submissions.ai_detail.defects` 的元素）。

    字段全部照分析管线原样透出，缺哪个就回 null，不由后端补词；`features` 是
    分析特征键值对，页面直接渲染成标签。`id` 统一成字符串供页面做处理去重。
    """

    id: str | None
    label: str | None
    status: str | None
    category: str | None
    evidence: str | None
    features: dict[str, str | int | float | bool | None] | None
    confidence: float | None


class CdmDefectList(BaseModel):
    """缺陷标签诊断模块的取数结果。

    `defects` 为 null 表示 `ai_detail` 里没有可用的 `defects` 数组（没有数据源），
    空数组表示「查了没缺陷」——同第 55 条的 null/[] 约定。
    """

    submission_id: int
    defects: list[CdmDefect] | None


class CdmFeatureMatrixData(BaseModel):
    """特征矩阵（功能 4.6 的「CDM 输入特征矩阵」）。

    `feature_matrix` 为 null 表示该提交没有 `ai_detail.featureMatrix`（新提交
    49 起就没有），不是空矩阵。键名保留分析侧的驼峰（pitchStd 等），与 F5
    的 `feature_matrix` 同一口径，不做 snake_case 转换。
    """

    submission_id: int
    feature_matrix: dict | None


class CdmPitchPattern(BaseModel):
    """音高偏差模式分析（功能 4.6 的「音高偏差模式分析」卡）。

    `source` 说明数据来源：
    - `feature_matrix`：旧种子提交的 `ai_detail.featureMatrix`（9 个声学量）；
    - `words`：没有特征矩阵时，用 `ai_detail.words` 的逐字偏差现算；
    - `null`：两者都没有可用数据。

    `mean` / `std` / `high_pitch_bias` / `low_pitch_bias` 单位都是 cents；
    `median` 只有 `words` 来源有；`word_count` 是参与统计的逐字样本数。
    """

    submission_id: int
    source: str | None
    trend: str | None
    mean: float | None
    median: float | None
    std: float | None
    high_pitch_bias: float | None
    low_pitch_bias: float | None
    word_count: int | None


class CdmSubmissionSummary(BaseModel):
    """CDM 报告顶部四个指标的数据（接口清单无此条，口径见 DOC_ISSUES 第 55 条）。

    `defect_count` / `high_confidence_count` / `overall_confidence` 为 null 表示
    `ai_detail` 里没有可用数据源，不是 0：0 表示「查了没缺陷」，null 表示「没查/查不了」。
    """

    submission_id: int
    ai_score: float | None
    overall_confidence: float | None
    defect_count: int | None
    high_confidence_count: int | None
