from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.models import BktHistory


def get_history_list(db:Session) -> list[BktHistory]:
    return db.scalars(select(BktHistory).order_by(BktHistory.student_id,BktHistory.skill,desc(BktHistory.recorded_at))).all()