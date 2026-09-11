from datetime import datetime
from sqlalchemy import Boolean,CheckConstraint,DateTime,String,func,text
from sqlalchemy.orm import Mapped,mapped_column
from app.db import Base


class User(Base):
    """用户账号（教师与学生共用一张表，用 role 区分）。"""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('teacher','student')", name="users_role_check"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(10))
    display_name: Mapped[str] = mapped_column(String(50))
    is_active: Mapped[bool | None] = mapped_column(Boolean, server_default=text("TRUE"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())
