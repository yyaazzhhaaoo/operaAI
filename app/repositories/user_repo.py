# -*- coding: utf-8 -*-
"""users 表的数据访问。

写操作只 flush()、不 commit——事务边界在 service 层，理由见 CLAUDE.md。
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.student import Student
from app.models.user import User


def get_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def get_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def update_password(db: Session, user: User, password_hash: str) -> None:
    """改密码哈希。只 flush，提交由 service 层负责。"""
    user.password_hash = password_hash
    db.flush()

def get_by_role(db:Session,role:str) -> list[User]:
    return list(db.scalars(select(User).where(User.role == role)).all())


def get_student_names(db: Session, student_ids: list[int]) -> dict[int, str]:
    """按 students.id 批量取学生姓名，返回 {students.id: display_name}。

    bkt_history / practice_records 等表的 student_id 外键指向 **students.id**，
    不是 users.id——两者只是偶尔数值相同。把它当 users.id 用 db.get(User, ...)
    查，会静默取到另一个人的名字（或取不到返回 None）。
    姓名必须经 students.user_id 拐一次，见 DOC_ISSUES 第 21 条。
    """
    if not student_ids:
        return {}
    rows = db.execute(
        select(Student.id, User.display_name)
        .join(User, User.id == Student.user_id)
        .where(Student.id.in_(set(student_ids)))
    ).all()
    return dict(rows)