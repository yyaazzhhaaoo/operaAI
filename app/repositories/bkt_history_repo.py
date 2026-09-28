from sqlalchemy import select, desc, func
from sqlalchemy.orm import Session, aliased

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


def get_recent_by_skill(db:Session, limit:int = 2) -> list[BktHistory]:
    """每个 (student_id, skill) 只留 recorded_at 最近的 limit 条，组内倒序。

    掌握度热力图（G3）要两个数：第 1 条是当前 p_l，第 1、2 条比对出趋势箭头。
    不用 get_history_list 是它会把全表拉回来——只为这两个数拉全部历史不划算。

    row_number() 的开窗排序正好命中 idx_bkt_student_skill(student_id, skill,
    recorded_at DESC)；DISTINCT ON 做不到「每组前 N 条」，只能每组一条。
    """
    ranked = select(
        BktHistory,
        func.row_number().over(
            partition_by=(BktHistory.student_id, BktHistory.skill),
            order_by=desc(BktHistory.recorded_at),
        ).label("rn"),
    ).subquery()

    history = aliased(BktHistory, ranked)
    return list(db.scalars(
        select(history)
        .where(ranked.c.rn <= limit)
        .order_by(history.student_id, history.skill, desc(history.recorded_at))
    ).all())