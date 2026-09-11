# -*- coding: utf-8 -*-
"""users 表的数据访问。

写操作只 flush()、不 commit——事务边界在 service 层，理由见 CLAUDE.md。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


def get_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def get_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def update_password(db: Session, user: User, password_hash: str) -> None:
    """改密码哈希。只 flush，提交由 service 层负责。"""
    user.password_hash = password_hash
    db.flush()
