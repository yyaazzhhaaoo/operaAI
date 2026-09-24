from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.models import BktHistory


def get_history_list(db:Session) -> list[BktHistory]:
    return db.scalars(select(BktHistory).order_by(BktHistory.student_id,BktHistory.skill,desc(BktHistory.recorded_at))).all()


def get_latest_by_skill(db:Session) -> list[BktHistory]:
    """每个 (student_id, skill) 只留 recorded_at 最新的那一条，即「当前掌握度」。

    bkt_history 是历史表，同一 (学生, 技法) 会有多行，判预警只能拿最新的比。
    DISTINCT ON 是 PostgreSQL 的写法（`.distinct(*cols)` 在 PG 方言下渲染成它）。
    """
    return list(db.scalars(
        select(BktHistory)
        .distinct(BktHistory.student_id, BktHistory.skill)
        .order_by(BktHistory.student_id, BktHistory.skill, desc(BktHistory.recorded_at))
    ).all())