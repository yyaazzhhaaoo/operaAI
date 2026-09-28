from datetime import date, datetime, timedelta

from sqlalchemy import Date, cast, desc, select, func, extract
from sqlalchemy.orm import Session, aliased

from app.models import PracticeRecord, Student, User
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

