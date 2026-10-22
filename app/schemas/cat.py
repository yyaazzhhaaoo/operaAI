from pydantic import BaseModel


class CatQuestionOut(BaseModel):
    id: int
    seq: int
    segment_id: int
    title: str
    demo_title: str
    duration: float | None
    focus_dims: list[str]
    lyrics: str
    audio_url: str | None


class CatQuestionsOut(BaseModel):
    questions: list[CatQuestionOut]


class CatSubmitOut(BaseModel):
    task_id: str


class CatSkillOut(BaseModel):
    skill: str
    p_l: float | None
    confidence: float | None = None


class CatReportOut(BaseModel):
    record_id: int
    student_id: int
    profile: list[CatSkillOut]
    top3: list[CatSkillOut]


class CatSkipOut(BaseModel):
    created: int
    profile: list[CatSkillOut]
    top3: list[CatSkillOut]
