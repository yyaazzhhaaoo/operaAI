from pydantic import BaseModel, ConfigDict


class DashBoardSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_count:int
    new_student_count:int
    library_count:int
    new_library_count:int
    annotations_count:int
    new_annotations_count:int
    homeworks_count:int


class MasteryDropAlert(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    diff:float | int
    latest:float | int
    previous:float | int
    skill:str
    student_id:int
    student_name:str | None

class OverduePracticeAlert(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    days_over: int
    student_id: int
    student_name: str | None

class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    masteryDropAlert: list[MasteryDropAlert]
    overduePracticeAlert: list[OverduePracticeAlert]