from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import DateTime,Float,ForeignKey,Index,Integer,String,func,text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped,mapped_column,relationship
from app.db import Base

if TYPE_CHECKING:
    from app.models.audio import AudioFile
    from app.models.demo import Segment
    from app.models.student import Student


class PracticeRecord(Base):
    """练习记录。摸底测试也落这张表，用 source='cat_test' 区分。"""

    __tablename__ = "practice_records"
    # 学生成绩页按「某学生的记录倒序」翻页，无此索引会全表扫。
    # 用 text() 而非 created_at.desc()：后者要求列对象已绑定，写在类体前部会 NameError
    __table_args__ = (
        Index("idx_practice_student_time", "student_id", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id"))
    segment_id: Mapped[int | None] = mapped_column(ForeignKey("segments.id"))
    source: Mapped[str | None] = mapped_column(String(10), server_default=text("'practice'"))
    audio_id: Mapped[int | None] = mapped_column(ForeignKey("audio_files.id"))
    ai_score: Mapped[float | None] = mapped_column(Float)
    dimensions_json: Mapped[dict | None] = mapped_column(JSONB)   # {音准,节奏,气息,咬字,拖腔}
    duration_sec: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    student: Mapped["Student | None"] = relationship()
    segment: Mapped["Segment | None"] = relationship()
    audio: Mapped["AudioFile | None"] = relationship()


class BktHistory(Base):
    """BKT 掌握度历史。"""

    __tablename__ = "bkt_history"
    # 掌握度趋势图按「某学生某技法」取最近若干条，无此索引会全表扫
    __table_args__ = (
        Index("idx_bkt_student_skill", "student_id", "skill", text("recorded_at DESC")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id"))
    skill: Mapped[str] = mapped_column(String(50))
    p_l: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    source_type: Mapped[str | None] = mapped_column(String(20))   # practice/homework/cat_test
    source_id: Mapped[int | None] = mapped_column(Integer)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    student: Mapped["Student | None"] = relationship()
