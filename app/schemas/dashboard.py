from datetime import datetime

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


class HeatmapStudent(BaseModel):
    """热力图的一行：一个学生 × 全部技法（功能 5.5）。

    values / trends 与 HeatmapResponse.skills **下标对齐**——列顺序由服务端定一次，
    前端 x 轴直接用返回的 skills，不存在前后端各排一套排错位的问题。
    """
    model_config = ConfigDict(from_attributes=True)
    student_id: int
    student_name: str | None
    values: list[float | None]    # 各技法当前 p_l；该生该技法无记录为 None
    trends: list[str | None]      # up/down/flat；不足两条记录为 None


class HeatmapResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    skills: list[str]                 # 技法列顺序，x 轴
    students: list[HeatmapStudent]    # y 轴


class StudentAbility(BaseModel):
    """学生能力状态列表的一行（功能 5.6）：掌握度 + 趋势箭头 + 练习统计。

    values / trends 与 StudentAbilityResponse.skills **下标对齐**，且与热力图的
    HeatmapStudent 完全同构——同一批技法、同一个取数口径，前端两个接口用同一套
    取值方式，不存在两边各排一套排错位的问题。

    行出**全部在册学生**（热力图只出有 bkt 记录的）：从没练过的学生在这里是
    「未练习」，是有用信息，不该从名单里消失。
    """
    model_config = ConfigDict(from_attributes=True)
    student_id: int
    student_name: str | None
    level: str | None                 # students.level，档案没填为 None
    avatar: str | None                # students.avatar，档案没填为 None（前端自行兜底占位）
    values: list[float | None]        # 各技法当前 p_l；该生该技法无记录为 None
    trends: list[str | None]          # up/down/flat；不足两条记录为 None
    last_practice_at: datetime | None # 最后一次练习时间，带 +08:00 偏移；没练过为 None
    week_practice_count: int          # 本周练习次数（周一为界，北京日期）
    streak_days: int                  # 连续练习天数，规则见 dashboard_service._streak


class StudentAbilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    skills: list[str]                     # 技法列顺序，与 HeatmapResponse.skills 同源
    students: list[StudentAbility]