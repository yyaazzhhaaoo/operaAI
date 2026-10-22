from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import CatQuestion, Segment


def list_active(db: Session) -> list[CatQuestion]:
    """启用中的题目，按 seq 排序；一次取回 segment 与 demo，避免 N+1。"""
    return list(db.scalars(
        select(CatQuestion)
        .options(selectinload(CatQuestion.segment).selectinload(Segment.demo))
        .where(CatQuestion.is_active.is_(True))
        .where(CatQuestion.segment_id.is_not(None))
        .order_by(CatQuestion.seq)
    ).all())


def get_active_by_segment(db: Session, segment_id: int) -> CatQuestion | None:
    """某分段是否是启用中的摸底题；J2 用它挡住普通练习冒充摸底。"""
    return db.scalar(
        select(CatQuestion)
        .where(CatQuestion.segment_id == segment_id)
        .where(CatQuestion.is_active.is_(True))
        .limit(1)
    )
