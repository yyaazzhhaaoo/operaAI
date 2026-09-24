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

class PrereqSkill(BaseModel):
    """一条未达标的前置技法。"""
    model_config = ConfigDict(from_attributes=True)
    skill: str          # 前置技法名
    mastery: float      # 该前置技法当前的掌握度 p_l
    threshold: float    # 该前置技法自己的达标线


class PrereqLockAlert(BaseModel):
    """前置技法锁定（功能 5.4）：前置技法没达标，它的下游技法对该学生锁定。

    按学生聚合，一个学生一行——同一个学生的多条锁定原本会长成多行、姓名重复。
    一个前置可能锁住多个技法（气息支撑→归韵/拖腔），一个技法也可能被多个前置
    锁住（润腔），所以 locked_skills 与 prereqs 两边都去过重。
    """
    model_config = ConfigDict(from_attributes=True)
    student_id: int
    student_name: str | None
    locked_skills: list[str]      # 被锁掉的下游技法名，已去重
    prereqs: list[PrereqSkill]    # 导致锁定的前置技法明细，已去重

class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    masteryDropAlert: list[MasteryDropAlert]
    overduePracticeAlert: list[OverduePracticeAlert]
    prerequisiteLockAlert: list[PrereqLockAlert]