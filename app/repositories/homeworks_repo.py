from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Homework


def get_open_homeworks(db:Session,status:str) -> Homework:
    return list(db.scalars(select(Homework).where(Homework.status == status)).all())