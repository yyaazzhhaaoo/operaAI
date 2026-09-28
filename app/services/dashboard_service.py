from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.repositories import user_repo, library_repo, annotations_repo, homeworks_repo, bkt_history_repo, \
    practice_records_repo, graph_repo
from app.models import BktHistory
from app.schemas.dashboard import DashBoardSummary, MasteryDropAlert, AlertResponse, PrereqLockAlert, PrereqSkill, \
    HeatmapStudent, HeatmapResponse, StudentAbility, StudentAbilityResponse

BEIJING = ZoneInfo("Asia/Shanghai")

# 热力图的技法列（功能 5.5），顺序即 x 轴顺序。
# 硬编码而不用 graph_nodes：库里 node_type='skill' 的节点只有 3 个、且技法名与页面
# 对不上（图谱写「归韵」、页面写「归韵咬字」，见 DOC_ISSUES），拿它当列会少一半、
# 还对不齐。技法维度变更时改这里这一处。
SKILLS: tuple[str, ...] = ("音准控制", "气息支撑", "滑音", "拖腔", "归韵咬字", "节奏感知")


def summary(db:Session) -> DashBoardSummary:
    # 在班学生
    user_list = user_repo.get_by_role(db,role="student") or []
    user_count = len(user_list)
    # 第二步：在这批结果里按 created_at 筛选本周
    today = datetime.now()
    start_of_week = (today - timedelta(days=today.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    weekly_students = [u for u in user_list if u.created_at >= start_of_week]

    # 新增人数
    new_student_count = len(weekly_students)

    # 示范曲目
    library_list = library_repo.get_library_list(db) or []
    library_count = len(library_list)
    weekly_library = [l for l in library_list if l.created_at >= start_of_week]
    new_library_count = len(weekly_library)

    # 标注规则
    annotations_list = annotations_repo.get_annotations_list(db) or []
    annotations_count = len(annotations_list)
    weekly_annotations = [a for a in annotations_list if a.created_at >= start_of_week]
    new_annotations_count = len(weekly_annotations)

    # 待批改
    homeworks_list = homeworks_repo.get_open_homeworks(db,status="open") or []
    homeworks_count = len(homeworks_list)

    return DashBoardSummary(
        user_count=user_count,
        new_student_count=new_student_count,
        library_count=library_count,
        new_library_count=new_library_count,
        annotations_count=annotations_count,
        new_annotations_count=new_annotations_count,
        homeworks_count=homeworks_count
    )

def alerts(db:Session):
    records = bkt_history_repo.get_history_list(db)
    grouped: dict[tuple[int, str], list] = {}
    for r in records:
        key = (r.student_id, r.skill)
        lst = grouped.setdefault(key, [])
        if len(lst) < 2:
            lst.append(r)

    # 组装结果；不足两条跳过
    # r.student_id 是 students.id 不是 users.id，姓名要经 students.user_id 拐一次，
    # 这里按学生批量取好，避免逐条查一次库（见 DOC_ISSUES 第 21 条）
    drop_names = user_repo.get_student_names(db, [r.student_id for r in records])
    result: list[MasteryDropAlert] = []
    for (student_id, skill), lst in grouped.items():
        if len(lst) < 2 or (lst[1].p_l - lst[0].p_l) <= 0.1:
            continue
        latest, previous = lst[0], lst[1]
        result.append(MasteryDropAlert(
            student_id=student_id,
            student_name=drop_names.get(student_id),
            skill=skill,
            latest=latest.p_l,
            previous=previous.p_l,
            diff=round(latest.p_l - previous.p_l, 2),
        ))

    # 连续未提交统计
    records = practice_records_repo.get_records(db)

    # 前置技法锁定：前置技法当前的掌握度低于它自己的达标线，就把下游技法锁掉。
    # 判的是「前置」而不是「下游」——下游自己掌握度低只是练得少，不算被卡住。
    current = bkt_history_repo.get_latest_by_skill(db)
    mastery_by_skill: dict[str, list[tuple[int, float]]] = {}
    for r in current:
        mastery_by_skill.setdefault(r.skill, []).append((r.student_id, r.p_l))
    # student_id 是 students.id，姓名要经 students.user_id 拐一次
    lock_names = user_repo.get_student_names(db, [r.student_id for r in current])

    # 按学生聚合：一个学生只出一行，否则同一个名字会因为锁了多项技法重复多行
    grouped_locks: dict[int, tuple[list[str], list[PrereqSkill]]] = {}
    for prereq_skill, threshold, locked_skill in graph_repo.get_prereq_edges(db):
        # 前置技法在 bkt_history 里没有数据的边直接跳过：判不了就不报，
        # 图谱 label 与 bkt_history.skill 名字对不上时就是这种情况（见 DOC_ISSUES）
        for student_id, p_l in mastery_by_skill.get(prereq_skill, []):
            if p_l >= threshold:
                continue
            locked_skills, prereqs = grouped_locks.setdefault(student_id, ([], []))
            # 两边都去重：气息支撑一个前置锁住归韵+拖腔，润腔则被滑音和装饰音各锁一次
            if locked_skill not in locked_skills:
                locked_skills.append(locked_skill)
            if all(p.skill != prereq_skill for p in prereqs):
                prereqs.append(PrereqSkill(skill=prereq_skill, mastery=p_l, threshold=threshold))

    locks = [
        PrereqLockAlert(
            student_id=student_id,
            student_name=lock_names.get(student_id),
            locked_skills=locked_skills,
            prereqs=prereqs,
        )
        for student_id, (locked_skills, prereqs) in grouped_locks.items()
    ]
    locks.sort(key=lambda a: a.student_id)

    return AlertResponse(
        masteryDropAlert=result,
        overduePracticeAlert=records,
        prerequisiteLockAlert=locks,
    )
def heatmap(db:Session) -> HeatmapResponse:
    """班级技能掌握概率热力图（功能 5.5）：学生 × 技法的 P(L) 矩阵 + 趋势箭头。

    行只出在这批技法上有记录的学生（整行空白的学生不占行），列是 SKILLS 常量。
    单个 (学生, 技法) 没记录时那一格仍是 null——学生整体有数据、个别技法没测过，
    跟整行没数据是两回事。
    """
    students = user_repo.get_students_with_bkt(db, list(SKILLS))

    # (students.id, skill) -> [最新, 次新]，每组最多两条
    history_by_cell: dict[tuple[int | None, str], list[BktHistory]] = {}
    for r in bkt_history_repo.get_recent_by_skill(db):
        history_by_cell.setdefault((r.student_id, r.skill), []).append(r)

    rows = []
    for student_id, student_name in students:
        values: list[float | None] = []
        trends: list[str | None] = []
        for skill in SKILLS:
            history = history_by_cell.get((student_id, skill), [])
            # 无记录写 null 不写 0：0 是「完全未掌握」这个真实测量值，
            # 拿它表示「没测过」会让看板凭空多出一片红格子。
            values.append(history[0].p_l if history else None)
            trends.append(_trend(history))
        rows.append(HeatmapStudent(
            student_id=student_id,
            student_name=student_name,
            values=values,
            trends=trends,
        ))

    return HeatmapResponse(skills=list(SKILLS), students=rows)


def _trend(history: list[BktHistory]) -> str | None:
    """最新一条相对次新一条的方向。

    不足两条就没有趋势可言，返回 None 而不是 flat——flat 的含义是「确实持平」，
    一条记录冒充不了它。文档没给趋势规则，所以不设死区阈值：差 0.001 也是 up。
    （alerts 里那个 0.1 是「骤降预警」的阈值，不是趋势箭头，不复用。）
    """
    if len(history) < 2:
        return None
    diff = history[0].p_l - history[1].p_l
    if diff > 0:
        return "up"
    if diff < 0:
        return "down"
    return "flat"


def _beijing_now() -> datetime:
    """当前的北京时间，naive。

    不用裸 datetime.now()：那取的是进程所在时区的时间，而 practice_records /
    bkt_history 的 created_at 是 timestamp without time zone + 列默认 now()，
    按 server 的 timezone 落库（本机 postgresql.conf 里是 Asia/Shanghai），
    存的**固定是北京时间**。Flask 一旦跑在 TZ=UTC 的容器里，两边就差 8 小时，
    「本周」的边界会算错。这里显式取北京时区，跟库里的口径对齐。

    （summary() 与 practice_records_repo.get_records() 用的还是裸 datetime.now()，
    口径没对齐，等它们改的时候统一收敛到这一个函数。）
    """
    return datetime.now(BEIJING).replace(tzinfo=None)


def students(db: Session) -> StudentAbilityResponse:
    """学生能力状态列表（功能 5.6）：在册学生 × 掌握度 + 趋势箭头 + 练习统计。

    与 heatmap 的两点差异都是有意的：
    - 行出**全部** role='student' 的学生，heatmap 只出有 bkt 记录的。从没练过的
      学生在这里显示成一行 null（前端渲染「未练习」）是有用信息；在热力图里则
      只是整行空白，纯粹占地方。
    - 多带练习统计（最近练习 / 本周次数 / 连续天数），这几个字段支撑不了热力图的
      格子，只有列表要。

    掌握度与趋势的取数与 heatmap 完全共用：同一份 get_recent_by_skill 结果 +
    同一个 _trend，两个接口不会给出不一致的箭头。
    """
    roster = user_repo.get_student_roster(db)
    student_ids = [row[0] for row in roster]

    # (students.id, skill) -> [最新, 次新]，每组最多两条
    history_by_cell: dict[tuple[int | None, str], list[BktHistory]] = {}
    for r in bkt_history_repo.get_recent_by_skill(db):
        history_by_cell.setdefault((r.student_id, r.skill), []).append(r)

    last_at = practice_records_repo.get_last_practice_at(db, student_ids)
    days_by_student = practice_records_repo.get_practice_days(db, student_ids)
    today = _beijing_now().date()
    week_start = today - timedelta(days=today.weekday())   # 本周一

    rows: list[StudentAbility] = []
    for student_id, student_name, level, avatar in roster:
        values: list[float | None] = []
        trends: list[str | None] = []
        for skill in SKILLS:
            history = history_by_cell.get((student_id, skill), [])
            values.append(history[0].p_l if history else None)
            trends.append(_trend(history))

        days = days_by_student.get(student_id, {})
        last = last_at.get(student_id)
        rows.append(StudentAbility(
            student_id=student_id,
            student_name=student_name,
            level=level,
            avatar=avatar,
            values=values,
            trends=trends,
            # 库里存的是 naive 的北京墙上时间，补上 +08:00 再序列化：不带偏移的
            # ISO 串会被浏览器按**本地**时区解析，换台不在北京的机器看就整体偏了。
            last_practice_at=last.replace(tzinfo=BEIJING) if last else None,
            week_practice_count=sum(n for d, n in days.items() if d >= week_start),
            streak_days=_streak(days, today),
        ))

    return StudentAbilityResponse(skills=list(SKILLS), students=rows)


def _streak(days: dict[date, int], today: date) -> int:
    """从最后一次练习那天往回数，连续有练习的天数。

    断点规则（文档没规定，这里定死并写进接口注释）：最后一次练习既不是今天也不是
    昨天就算断了，返回 0。不这么判的话，一个半年前连练 30 天、之后再也不来的学生
    会一直挂着「连续 30 天」。

    只数「有练习的天」，同一天练几次都算一天——days 是去重后的日期桶，值是天数次数。
    """
    if not days:
        return 0
    last = max(days)
    if (today - last).days > 1:
        return 0
    n = 0
    cur = last
    while cur in days:
        n += 1
        cur -= timedelta(days=1)
    return n


