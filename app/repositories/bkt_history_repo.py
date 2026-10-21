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


def get_latest_for_student_skill(
    db: Session, student_id: int, skill: str
) -> BktHistory | None:
    """某学生某技法最新一条掌握度；没有记录返回 None（练习接口以 0.5 作先验）。"""
    return db.scalar(
        select(BktHistory)
        .where(BktHistory.student_id == student_id)
        .where(BktHistory.skill == skill)
        .order_by(desc(BktHistory.recorded_at), desc(BktHistory.id))
        .limit(1)
    )


def get_by_source(
    db: Session, source_type: str, source_id: int
) -> list[BktHistory]:
    """某一次分析写入的全部 BKT 行。

    `apply_bkt` 每次写「实际参与更新的维度」各一行（通常 5 行），source_id
    指向 practice_records.id 或 submissions.id。F3 归档练习成绩时用它还原
    这次练习的 BKT 前后值。
    """
    return list(db.scalars(
        select(BktHistory)
        .where(BktHistory.source_type == source_type)
        .where(BktHistory.source_id == source_id)
        .order_by(BktHistory.id)
    ).all())


def get_previous_for_skill(
    db: Session, student_id: int, skill: str, before_id: int
) -> BktHistory | None:
    """同一学生同一技法在 `before_id` 之前最近的一条。

    用来还原 `apply_bkt` 写入时读到的「上一次掌握度」——它只落更新后的 p_l，
    before 没有落库。排序与 `get_latest_for_student_skill` 一致
    （recorded_at DESC, id DESC）。限定 `id < before_id`：同一次分析插入的
    多行 recorded_at 相同（同一事务的 NOW()），只能靠自增 id 区分先后。
    """
    return db.scalar(
        select(BktHistory)
        .where(BktHistory.student_id == student_id)
        .where(BktHistory.skill == skill)
        .where(BktHistory.id < before_id)
        .order_by(desc(BktHistory.recorded_at), desc(BktHistory.id))
        .limit(1)
    )


def get_latest_per_skill_for_student(db: Session, student_id: int) -> list[BktHistory]:
    """某个学生每个技法只留 recorded_at 最新的那一条，即「当前掌握度」。

    与已有的 get_latest_by_skill 是同一套 DISTINCT ON 写法，区别只是**限定单个
    学生**——那个函数把全班拉回来再按学生分组，只为渲染一个人的左侧面板不值当，
    且 LIMIT 也下推不到索引。这里带上 student_id 等值条件，正好命中
    idx_bkt_student_skill(student_id, skill, recorded_at DESC)。
    """
    return list(db.scalars(
        select(BktHistory)
        .where(BktHistory.student_id == student_id)
        .distinct(BktHistory.skill)
        .order_by(BktHistory.skill, desc(BktHistory.recorded_at))
    ).all())