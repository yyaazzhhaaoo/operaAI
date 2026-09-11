from typing import TYPE_CHECKING
from sqlalchemy import Boolean,ForeignKey,Integer,text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped,mapped_column,relationship
from app.db import Base

if TYPE_CHECKING:
    from app.models.demo import Segment


class CatQuestion(Base):
    """摸底测试题库（CAT）。题目复用 segments 的戏词与示范音频。"""

    __tablename__ = "cat_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    seq: Mapped[int] = mapped_column(Integer)                  # 题目顺序 1~8
    segment_id: Mapped[int | None] = mapped_column(ForeignKey("segments.id"))
    focus_dims: Mapped[list | None] = mapped_column(JSONB)     # ["音准","气息"]
    is_active: Mapped[bool | None] = mapped_column(Boolean, server_default=text("TRUE"))

    segment: Mapped["Segment | None"] = relationship()
