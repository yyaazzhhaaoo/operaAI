from datetime import date, datetime, timedelta

from sqlalchemy import Date, cast, desc, select, func, extract
from sqlalchemy.orm import Session, aliased

from app.models import PracticeRecord, Segment, Student, User
from app.schemas.dashboard import OverduePracticeAlert


def get_records(db:Session) -> list[OverduePracticeAlert]:
    subq = (
        select(
            PracticeRecord,
            func.row_number()
            .over(
                partition_by=PracticeRecord.student_id,
                order_by=desc(PracticeRecord.created_at),
            )
            .label("rn"),
        )
        .subquery()
    )
    pr = aliased(PracticeRecord, subq, name="pr")

    two_days_ago = datetime.now() - timedelta(days=2)
    days_over = extract("day", func.now() - pr.created_at).label("days_over")

    stmt = (
        select(pr, days_over, User.display_name)          # 顺带查学生姓名
        # student_id 外键指向 students.id 而不是 users.id，姓名要多拐一次
        # students.user_id → users.id，直接 join users 会取到另一个人的名字
        # （见 DOC_ISSUES 第 21 条）
        .join(Student, Student.id == pr.student_id)
        .join(User, User.id == Student.user_id)
        .where(subq.c.rn == 1)
        .where(pr.created_at < two_days_ago)
        .order_by(desc(pr.created_at))
    )

    return [
        OverduePracticeAlert(
            days_over=row.days_over,
            student_id=row.pr.student_id,
            student_name=row.display_name,
        )
        for row in db.execute(stmt).all()
    ]


# ---- 以下两个查询供「学生能力状态列表」（功能 5.6）用 ----
#
# 时区口径：practice_records.created_at 是 timestamp without time zone，列默认值
# now() 按 server 的 timezone 设置落库——本机 postgresql.conf 里是 Asia/Shanghai，
# 所以**列里存的就是北京时间**（实测 DEFAULT now() 写进去的值与同时刻的
# now() AT TIME ZONE 'Asia/Shanghai' 相等）。因此下面直接取 ::date，不做
# AT TIME ZONE 换算——换成 AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai'
# 会把日期整体推后 8 小时，跨零点的那几条会串到第二天去。


def get_last_practice_at(db: Session, student_ids: list[int]) -> dict[int, datetime]:
    """每个学生最后一次练习的时间，{students.id: created_at}；没练过的不在字典里。

    返回的是 naive 的**北京墙上时间**，理由见上面模块注释。
    """
    if not student_ids:
        return {}
    rows = db.execute(
        select(PracticeRecord.student_id, func.max(PracticeRecord.created_at))
        .where(PracticeRecord.student_id.in_(set(student_ids)))
        .group_by(PracticeRecord.student_id)
    ).all()
    return {sid: at for sid, at in rows if at is not None}


def get_weekly_totals(db: Session, student_ids: list[int]) -> dict[date, tuple[int, float]]:
    """按北京**周一**分桶的练习总量，{周一日期: (练习次数, 总时长秒数)}。

    班级过程指标（功能 5.8）要的是「一周的总次数与总时长」，两个指标同源同窗口，
    一次查询出齐，不拆成两次各扫一遍表。date_trunc('week') 在 PostgreSQL 里就是
    周一起算，与 dashboard_service 里 week_start 的算法一致。

    created_at 不做时区换算：库里存的就是北京墙上时间，与 get_practice_days 同口径
    （见 CLAUDE.md「容器内 PostgreSQL 的时区是 Etc/UTC」一条）。

    时长用 coalesce 兜 0：duration_sec 允许为 NULL，一条没时长的记录不该把整周
    的时长合计变成 NULL。
    """
    if not student_ids:
        return {}
    week = func.date_trunc("week", PracticeRecord.created_at).label("week")
    rows = db.execute(
        select(
            week,
            func.count(),
            func.coalesce(func.sum(PracticeRecord.duration_sec), 0.0),
        )
        .where(PracticeRecord.student_id.in_(set(student_ids)))
        .where(PracticeRecord.created_at.is_not(None))
        .group_by(week)
    ).all()
    return {w.date(): (n, float(total)) for w, n, total in rows}


def get_practice_days(db: Session, student_ids: list[int]) -> dict[int, dict[date, int]]:
    """按北京日期分桶的练习次数，{students.id: {日期: 次数}}；没练过的不在字典里。

    「本周次数」与「连续天数」都从这一份数据派生，不另开查询：一个学生一天最多
    一行，结果集大小是「学生数 × 有练习的天数」，与练习总量无关。
    """
    if not student_ids:
        return {}
    day = cast(PracticeRecord.created_at, Date).label("day")
    rows = db.execute(
        select(PracticeRecord.student_id, day, func.count())
        .where(PracticeRecord.student_id.in_(set(student_ids)))
        .where(PracticeRecord.created_at.is_not(None))
        .group_by(PracticeRecord.student_id, day)
    ).all()
    out: dict[int, dict[date, int]] = {}
    for sid, d, n in rows:
        out.setdefault(sid, {})[d] = n
    return out


# ---- 以下三个查询供「班级畏难倾向指数」（功能 5.8）用 ----
#
# 时区口径与上面 `get_weekly_totals` / `get_practice_days` 一致：created_at 存的
# 就是北京墙上时间，直接比，不做 AT TIME ZONE 换算。


def get_interrupt_rows(db: Session, start: datetime, end: datetime) -> list[tuple[float, float]]:
    """判「练习中断」用的原始行，[(本次练习时长秒, 该唱段时长秒)]，窗口左闭右开。

    practice_records 里**没有**任何「学生主动退出」的字段，只能拿「录下来的时长
    明显短于唱段时长」当「没唱完」的近似（见设计第 3.1 节）。比例阈值不在这里判，
    由 service 层的 INTERRUPT_RATIO 决定——本层只负责把两个时长取齐。

    只取两端都在的行：segment_id 为空、唱段 duration 为空或非正、本次 duration_sec
    为空，任缺其一就判不了，**分子分母都不含它**，不用「班级人均时长」之类的第二把
    尺子兜底。
    """
    if start >= end:
        return []
    rows = db.execute(
        select(PracticeRecord.duration_sec, Segment.duration)
        .join(Segment, Segment.id == PracticeRecord.segment_id)
        .where(Segment.duration > 0)
        .where(PracticeRecord.duration_sec.is_not(None))
        .where(PracticeRecord.created_at >= start)
        .where(PracticeRecord.created_at < end)
    ).all()
    return [(float(dur), float(seg_dur)) for dur, seg_dur in rows]


def get_retry_rows(db: Session, start: datetime, end: datetime) -> list[tuple[int, int, float | None, datetime]]:
    """判「重试放弃」用的原始行，[(student_id, segment_id, ai_score, created_at)]。

    按 `created_at` **升序**返回：service 层判「最后一遍有没有刷新最好成绩」依赖
    这个顺序，不要在那边再排一次。

    segment_id 为空的行取不到——按唱段分组是这条判据的前提。ai_score 为空的行
    **照常返回**（不过滤）：要不要弃用整组由 service 层决定，本层不替它做取舍。
    """
    if start >= end:
        return []
    rows = db.execute(
        select(
            PracticeRecord.student_id,
            PracticeRecord.segment_id,
            PracticeRecord.ai_score,
            PracticeRecord.created_at,
        )
        .where(PracticeRecord.segment_id.is_not(None))
        .where(PracticeRecord.created_at >= start)
        .where(PracticeRecord.created_at < end)
        .order_by(PracticeRecord.created_at)
    ).all()
    return [(sid, seg_id, score, at) for sid, seg_id, score, at in rows]


def get_last_practice_dates(db: Session, student_ids: list[int], until: datetime) -> dict[int, date]:
    """每个学生在 `until`（含当天）之前的最后一次练习日期，{students.id: 北京日期}。

    没练过的学生不在字典里——调用方要自己把「不在字典里」当成「从未练过」处理，
    不能当成 0 或今天（见设计第 3.3 节）。

    返回 date 而不是 datetime：连续未练习天数是按**北京日期**相减的，时分秒不参与。
    用 cast 取日期，与 `get_practice_days` 同一套口径。
    """
    if not student_ids:
        return {}
    day = cast(PracticeRecord.created_at, Date)
    rows = db.execute(
        select(PracticeRecord.student_id, func.max(day))
        .where(PracticeRecord.student_id.in_(set(student_ids)))
        .where(PracticeRecord.created_at.is_not(None))
        .where(PracticeRecord.created_at <= until)
        .group_by(PracticeRecord.student_id)
    ).all()
    return {sid: d for sid, d in rows if d is not None}

