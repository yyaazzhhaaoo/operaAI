from datetime import datetime

from pydantic import BaseModel


class PracticeRecordOut(BaseModel):
    """一条练习记录。dimensions 对应库里的 dimensions_json。

    文档没有定义 D2/D3 的响应体（详见 DOC_ISSUES 第 44 条），字段以
    practice_records 表为准；created_at 是北京时间墙上时间，不带时区偏移。
    """

    id: int
    student_id: int | None
    segment_id: int | None
    source: str | None
    audio_id: int | None
    ai_score: float | None
    dimensions: dict[str, float] | None
    duration_sec: float | None
    created_at: datetime | None


class PracticeSubmitOut(BaseModel):
    task_id: str


class PracticeLastOut(BaseModel):
    record: PracticeRecordOut | None


class PracticeLogsOut(BaseModel):
    records: list[PracticeRecordOut]
    total: int
