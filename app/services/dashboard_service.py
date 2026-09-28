from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.repositories import user_repo, library_repo, annotations_repo, homeworks_repo, bkt_history_repo, \
    practice_records_repo, graph_repo
from app.common.errors import BusinessError
from app.models import BktHistory, GraphNode, TeacherDemo
from app.schemas.dashboard import DashBoardSummary, MasteryDropAlert, AlertResponse, PrereqLockAlert, PrereqSkill, \
    HeatmapStudent, HeatmapResponse, StudentAbility, StudentAbilityResponse, \
    RecommendationItem, RecommendationResponse, ProcessMetrics, \
    HomeworkProgressItem, HomeworkProgressResponse

BEIJING = ZoneInfo("Asia/Shanghai")

# 推荐（功能 5.7）的两条难度判据。文档只写「BKT+依赖图谱 Top3 推荐曲目」，
# 没给匹配区间，这两个数是实现时定的：与当前水平差 0.10 以内算相当，
# 高出 0.10~0.25 算够得着，再高就太难；比水平低 0.10 以上则太简单，同样不推。
DIFF_MATCH = 0.10
DIFF_CHALLENGE = 0.25

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


def recommendations(db: Session, student_id: int) -> RecommendationResponse:
    """学生推荐路径（功能 5.7）：BKT 掌握度 × 依赖图谱，Top3 推荐唱段。

    文档（《5-接口清单》G5、《1-PRD》5.7）只写到「点击学生显示 Top 3 练习曲目」，
    响应结构与匹配规则均未定义，以下口径是本次实现定死的，改动前先看这几条：

    1. 候选集是**图谱里的唱段节点**（node_type='segment'），不是 segments 表：
       「这个唱段要练哪些技法」只存在于 graph_edges 的 contains 边。
    2. **能算才算**：需求技法里只要有一个在该生的 bkt 记录里没有，就判不出掌握度，
       整条跳过。图谱里的「音准稳定性」「归韵」等技法名与 bkt_history 对不上
       （见 DOC_ISSUES），「辕门外三声炮」等三个唱段因此永远进不了候选——
       这是已知取舍，不是 bug。
    3. 难度取 teacher_demos.elo_difficulty，且必须落在 0-1 才认：列默认值 1000
       表示「未标定」，拿它算匹配会得出荒谬结果，直接排除。
    4. **lock 优先于难度**：所需技法的前置技法未达标就记 lock，且不再参与难度过滤
       （前置没过关时，难度合不合适不是重点）。lock 项排最后。
    5. 排序 match → challenge → lock，同档按「偏离当前水平越小越靠前」，取前 3。
       不足 3 条、甚至为空都是正常的（数据现状就会如此），前端有对应占位。
    """
    if not any(row[0] == student_id for row in user_repo.get_student_roster(db)):
        raise BusinessError(404, "学生不存在")

    # 该生各技法当前掌握度。p_l 为 None 的记录不算「测过」
    mastery = {
        r.skill: r.p_l
        for r in bkt_history_repo.get_latest_by_skill(db)
        if r.student_id == student_id and r.p_l is not None
    }
    if not mastery:
        return RecommendationResponse(student_id=student_id, recommendations=[])

    level = sum(mastery.values()) / len(mastery)

    # (前置技法, 达标线) 按下游技法分组
    prereq_by_skill: dict[str, list[tuple[str, float]]] = {}
    for p_skill, threshold, skill in graph_repo.get_prereq_edges(db):
        prereq_by_skill.setdefault(skill, []).append((p_skill, threshold))

    need_by_segment = graph_repo.get_segment_skill_map(db)
    seg_demo = library_repo.get_segment_demo_map(db)
    demos = {d.id: d for d in (library_repo.get_library_list(db) or [])}

    ranked: list[tuple[tuple[int, float], RecommendationItem]] = []
    for node in graph_repo.get_segment_nodes(db):
        skills = need_by_segment.get(node.id) or []
        if not skills or any(s not in mastery for s in skills):
            continue                          # 见口径 2

        demo = _resolve_demo(node, seg_demo, demos)
        if demo is None:
            continue
        difficulty = demo.elo_difficulty
        if difficulty is None or not 0.0 <= difficulty <= 1.0:
            continue                          # 见口径 3

        locks = [
            (p_skill, mastery[p_skill], threshold)
            for skill in skills
            for p_skill, threshold in prereq_by_skill.get(skill, [])
            if p_skill in mastery and mastery[p_skill] < threshold
        ]
        weakest = min(skills, key=lambda s: mastery[s])
        diff = difficulty - level

        if locks:
            p_skill, p_l, threshold = min(locks, key=lambda x: x[1])   # 最卡脖子的那个
            status, rank = "lock", (2, 0.0)
            reason = f"前置技法「{p_skill}」掌握度 {p_l:.0%}，未达 {threshold:.0%}，暂不推荐"
        elif abs(diff) <= DIFF_MATCH:
            status, rank = "match", (0, abs(diff))
            reason = f"难度与当前水平相当，重点巩固「{weakest}」（{mastery[weakest]:.0%}）"
        elif 0 < diff <= DIFF_CHALLENGE:
            status, rank = "challenge", (1, diff)
            reason = f"难度略高于当前水平，适合挑战；建议先巩固「{weakest}」（{mastery[weakest]:.0%}）"
        else:
            continue                          # 太难或太简单，都不推

        ranked.append((rank, RecommendationItem(
            segment_id=node.id,
            demo_id=demo.id,
            title=demo.title,
            difficulty=round(difficulty, 2),
            status=status,
            reason=reason,
        )))

    ranked.sort(key=lambda x: x[0])
    return RecommendationResponse(
        student_id=student_id,
        recommendations=[item for _, item in ranked[:3]],
    )


def process_metrics(db: Session) -> ProcessMetrics:
    """班级过程指标（功能 5.8）：本周人均练习时长与频次，附上周同口径值。

    周期、分母、单位与 fear_index 的处理见 ProcessMetrics 的注释。
    """
    student_ids = [row[0] for row in user_repo.get_student_roster(db)]

    # 本周一。与 students() 里的 week_start 同一套算法，两个接口的「本周」必须同一天，
    # 否则同一页面上「本周练习 3 次」和「人均 0.2 次」会打架
    this_week = _beijing_now().date()
    this_week -= timedelta(days=this_week.weekday())
    last_week = this_week - timedelta(days=7)

    totals = practice_records_repo.get_weekly_totals(db, student_ids)
    cur_count, cur_sec = totals.get(this_week, (0, 0.0))
    prev_count, prev_sec = totals.get(last_week, (0, 0.0))

    # 在册 0 人时给 0 而不是让 ZeroDivisionError 冒成 500：库是空的时候这个接口
    # 仍然应该能回 200，页面显示 0 比显示「加载失败」诚实
    n = len(student_ids) or 1
    return ProcessMetrics(
        week_start=this_week,
        student_count=len(student_ids),
        avg_duration_sec=cur_sec / n,
        avg_duration_sec_last_week=prev_sec / n,
        avg_practice_count=cur_count / n,
        avg_practice_count_last_week=prev_count / n,
    )


def homework_progress(db: Session) -> HomeworkProgressResponse:
    """作业进度列表（功能 5.9）：每份作业的提交完成度与状态。

    状态怎么判、列表怎么排，口径见 HomeworkProgressItem 的注释。
    """
    student_ids = [row[0] for row in user_repo.get_student_roster(db)]
    today = _beijing_now().date()
    # 在册 0 人时给 0 而不是让 ZeroDivisionError 冒成 500，同 process_metrics
    n = len(student_ids) or 1

    items: list[HomeworkProgressItem] = []
    for hw, demo, submitted, pending in homeworks_repo.get_progress_rows(db, student_ids):
        if pending:
            # 先判批改中：截止没截止都要批，这一档优先级高于生命周期
            status = "grading"
        elif hw.status == "closed" or (hw.deadline is not None and hw.deadline < today):
            status = "closed"
        else:
            status = "ongoing"
        items.append(HomeworkProgressItem(
            homework_id=hw.id,
            title=hw.title,
            deadline=hw.deadline,
            # demo 可空：作业允许不挂曲目（demo_id 为 NULL）
            demo_title=demo.title if demo else None,
            demo_role=demo.role if demo else None,
            demo_banshi=demo.banshi if demo else None,
            submitted_count=submitted,
            progress=submitted / n,
            pending_review_count=pending,
            status=status,
        ))

    # 待办优先：批改中 → 进行中 → 已截止；同档按截止日**降序**（最近的在前），
    # 没填截止日的沉底——与仓储层 `deadline desc nulls_last` 同一口径，两层不打架。
    # 次键取 id 降序，同一天截止的几份作业顺序才稳定。
    order = {"grading": 0, "ongoing": 1, "closed": 2}
    items.sort(key=lambda it: (
        order[it.status],
        it.deadline is None,
        -(it.deadline.toordinal() if it.deadline else 0),
        -it.homework_id,
    ))
    return HomeworkProgressResponse(student_count=len(student_ids), homeworks=items)


def _resolve_demo(node: GraphNode, seg_demo: dict[int, int],
                  demos: dict[int, TeacherDemo]) -> TeacherDemo | None:
    """把图谱的唱段节点落到一个曲目上——难度与标题都挂在曲目上，不在节点上。

    优先走图谱自己的约定（唱段节点的 ref_id 指向 segments.id，再由 demo_id 换算）；
    ref_id 为空、或指到了一个不在册的 segment 时，退到「节点 label 是曲目标题的
    结尾」这一层匹配。库里 6 个唱段节点有 3 个 ref_id 是空的，只认 ref_id 会让
    它们永远进不了候选。
    """
    if node.ref_id is not None:
        demo = demos.get(seg_demo.get(node.ref_id, -1))
        if demo is not None:
            return demo
    for demo in demos.values():
        if demo.title and demo.title.endswith(node.label):
            return demo
    return None


