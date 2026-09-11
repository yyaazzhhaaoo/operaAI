from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import DateTime,ForeignKey,String,Text,func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped,mapped_column,relationship
from app.db import Base

if TYPE_CHECKING:
    from app.models.student import Student


class ChatMessage(Base):
    """AI 教练对话记录。"""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id"))
    role: Mapped[str] = mapped_column(String(10))              # user / assistant
    content: Mapped[str] = mapped_column(Text)
    context_snapshot: Mapped[dict | None] = mapped_column(JSONB)   # 当时画像/策略/情绪
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    student: Mapped["Student | None"] = relationship()
