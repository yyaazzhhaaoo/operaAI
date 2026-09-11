from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import CheckConstraint,DateTime,ForeignKey,Integer,String,UniqueConstraint,func
from sqlalchemy.orm import Mapped,mapped_column,relationship
from app.db import Base

if TYPE_CHECKING:
    from app.models.demo import Segment
    from app.models.user import User


class Annotation(Base):
    """歌词级标注规则。

    tag 取值：滑音/归韵/换气/强音/拖腔/擞音
    """

    __tablename__ = "annotations"
    __table_args__ = (
        UniqueConstraint("segment_id", "word_index", "tag",
                         name="annotations_segment_id_word_index_tag_key"),
        CheckConstraint("tolerance BETWEEN 0 AND 100", name="annotations_tolerance_check"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    segment_id: Mapped[int | None] = mapped_column(ForeignKey("segments.id"))
    word_index: Mapped[int] = mapped_column(Integer)
    tag: Mapped[str] = mapped_column(String(10))
    tolerance: Mapped[int | None] = mapped_column(Integer)
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    segment: Mapped["Segment | None"] = relationship()
    teacher: Mapped["User | None"] = relationship()
