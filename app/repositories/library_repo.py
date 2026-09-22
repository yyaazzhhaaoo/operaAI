from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TeacherDemo


def get_library_list(db: Session) -> list[TeacherDemo] | None:
    return list(db.scalars(select(TeacherDemo)).all())


def add_library(db: Session, teacher_demo: TeacherDemo) -> TeacherDemo:
    """新增一条示范曲目。只 flush 拿自增 id，提交交给 service 层。"""
    db.add(teacher_demo)
    db.flush()
    return teacher_demo