from datetime import date, datetime

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


class RecommendationItem(BaseModel):
    """一条推荐唱段（功能 5.7）。

    status 三档与页面既有的三色标签一一对应，取值只能是：
      match      难度与学生当前水平相当
      challenge  难度略高于当前水平，够得着
      lock       该唱段所需技法的前置技法未达标，暂不推荐
    判定口径见 dashboard_service.recommendations 的注释。
    """
    model_config = ConfigDict(from_attributes=True)
    segment_id: int          # graph_nodes.id（唱段节点），不是 segments.id
    demo_id: int             # 曲目 id，点进去要用
    title: str               # 曲目标题
    difficulty: float        # elo_difficulty，已归一到 0-1
    status: str              # match / challenge / lock
    reason: str              # 一句话理由，直接展示


class RecommendationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    student_id: int
    recommendations: list[RecommendationItem]   # 不足 3 条是正常的，可能为空


class HomeworkProgressItem(BaseModel):
    """作业进度列表的一行（功能 5.9）。

    文档（《1-PRD》5.9、《3-功能清单》5.9、《5-接口清单》G7）的全部描述是
    「作业进度列表 — 提交完成度及状态」，**没有定义状态有哪些档、怎么判**。
    以下口径是本次实现定死的，对齐页面既有的三个标签样式：

    - grading 批改中：**有提交且存在未终审的提交**（`submissions.status != 'reviewed'`）。
      优先级最高——截止没截止都要批，这是唯一需要教师动手的一档；
    - closed 已截止：`homeworks.status == 'closed'`（教师显式关闭）**或**截止日已过；
      截止当天算最后一天，仍可提交，不判已过；
    - ongoing 进行中：其余（未关闭且未到截止日）。

    「已截止」同时认 `status` 与 `deadline` 两个来源：种子数据里就有 `status='open'`
    但 deadline 早已过期的作业（教师忘了关），只看 status 会把它显示成「进行中」。
    """
    model_config = ConfigDict(from_attributes=True)
    homework_id: int
    title: str
    deadline: date | None                 # 档案没填为 None，页面不显示截止
    demo_title: str | None                # 曲目名；作业没挂曲目为 None
    demo_role: str | None                 # 行当（青衣…）
    demo_banshi: str | None               # 板式（西皮流水…）
    submitted_count: int                  # 已提交**人数**（按学生去重）
    progress: float                       # 提交完成度 0-1，分子分母见下
    pending_review_count: int             # 待批（未终审）条数，为 0 说明不用批
    status: str                           # grading / closed / ongoing


class HomeworkProgressResponse(BaseModel):
    """作业进度列表（功能 5.9）。

    student_count 是**完成度的分母**，与 ProcessMetrics.student_count 同源（同一份
    在册名单），放在响应级而不是每行——一份作业一个分母，行内重复没有意义。

    不过滤、不截断：返回**全部**作业，由页面自己决定展示几条（看板卡片放不下时
    页面上还有「管理作业 →」入口），接口层不替调用方做取舍。
    """
    model_config = ConfigDict(from_attributes=True)
    student_count: int                    # 分母，可能为 0
    homeworks: list[HomeworkProgressItem]


class ProcessMetrics(BaseModel):
    """班级过程指标（功能 5.8）。

    三个指标的口径都是本次实现定死的（《1-PRD》5.8、《3-功能清单》5.8、
    《5-接口清单》G6 只给了指标名）：

    - 窗口：**本周**（周一起算，北京日期），与 StudentAbility.week_practice_count 同口径；
      每个指标都另带一份上周同口径值，供前端算趋势箭头。不返回差值本身——减法前端做。
    - 分母：**全体在册学生数**，含本周没练过的。所以两个 avg_* 都是「人均」语义：
      avg_duration_sec 是「人均本周练了多少秒」，不是「单次平均时长」。
    - 单位：时长一律**秒**，与 practice_records.duration_sec 同单位，前端显示分钟自行 /60。

    fear_index 的算法来自 2026-09-28 新增的《班级看板--班级畏难倾向指数说明.md》：
    5 个分量各自归一化到 0~1 后按固定权重（各 0.2）加权求和，范围 0~1，越高越畏难。
    分量的具体判据文档没写，实现口径见 dashboard_service 的 FEAR_WEIGHTS 常量区与
    `_fear_index`，以及 docs/superpowers/specs/2026-09-28-class-fear-index-design.md。
    趋势由前端相减得出，与两个 avg_* 同构。
    """
    model_config = ConfigDict(from_attributes=True)
    week_start: date                      # 本周周一，供前端显示统计口径
    student_count: int                    # 分母，可能为 0
    avg_duration_sec: float               # 本周人均练习时长（秒）
    avg_duration_sec_last_week: float     # 上周同口径，算趋势用
    avg_practice_count: float             # 本周人均练习次数
    avg_practice_count_last_week: float   # 上周同口径，算趋势用
    # 本周班级畏难倾向指数，0~1。**唯一回 None 的场景是在册学生数为 0**——那时
    # 没有分母也没有数据，0 会被读成「一点都不畏难」，与「没有数据」是两回事。
    fear_index: float | None
    fear_index_last_week: float | None    # 上周同口径，算趋势用；与 fear_index 同时为 None