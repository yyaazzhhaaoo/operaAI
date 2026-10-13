# -*- coding: utf-8 -*-
"""AI 教练对话（模块3）的出入参。

三条接口的契约见《5-接口清单-V1.0》2.5 / 3.3。
"""
from pydantic import BaseModel, ConfigDict, Field


class StudentBrief(BaseModel):
    id: int
    display_name: str | None
    level: str | None


class LastPractice(BaseModel):
    segment_id: int | None
    segment_title: str | None
    ai_score: float | None
    duration_sec: float | None
    recorded_at: str | None


class BktItem(BaseModel):
    skill: str
    p_l: float
    confidence: float | None


class WeakSkill(BaseModel):
    skill: str
    p_l: float


class CoachContextOut(BaseModel):
    """E1 客观数据区。

    `deviations` / `cdm` / `rag` 恒为 None —— 这三块在库里没有任何数据源
    （逐字偏差：dimensions_json 全 NULL 且语义是五维分数；CDM 与知识库：
    表都不存在）。用 None 而不是 [] 表达「没有数据源」，与 homework_service
    的同名约定一致：[] 是「查了，结果是空」，两者语义不同。

    字段保留在响应里、不省略，前端据 None 渲染「待接入」占位；
    将来补上数据源时前端判断不用改。
    """
    model_config = ConfigDict(from_attributes=True)

    student: StudentBrief
    last_practice: LastPractice | None
    bkt: list[BktItem]
    weak_skills: list[WeakSkill]

    deviations: list[dict] | None = None
    cdm: list[dict] | None = None
    rag: list[dict] | None = None


class CoachChatIn(BaseModel):
    """E2 入参（《5-接口清单》3.3）。"""
    student_id: int
    message: str = Field(min_length=1, max_length=1000)


class CoachChatOut(BaseModel):
    """E2 出参。四个字段是文档 3.3 定死的契约，不加不减。"""
    reply: str
    strategy: str
    emotion: str
    quick_replies: list[str]


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    created_at: str | None
