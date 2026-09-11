from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import DateTime,ForeignKey,String,func
from sqlalchemy.orm import Mapped,mapped_column,relationship
from app.db import Base

if TYPE_CHECKING:
    from app.models.user import User


class Student(Base):
    """学生教学档案，与 users 一对一。"""

    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True)
    level: Mapped[str | None] = mapped_column(String(20))
    avatar: Mapped[str | None] = mapped_column(String(255))
    enrolled_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User | None"] = relationship()
