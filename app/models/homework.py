from datetime import date,datetime
from typing import TYPE_CHECKING
from sqlalchemy import Date,DateTime,Float,ForeignKey,String,Text,func,text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped,mapped_column,relationship
from app.db import Base

if TYPE_CHECKING:
    from app.models.audio import AudioFile
    from app.models.demo import TeacherDemo
    from app.models.student import Student
    from app.models.user import User


class Homework(Base):
    """作业。"""

    __tablename__ = "homeworks"

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(100))
    demo_id: Mapped[int | None] = mapped_column(ForeignKey("teacher_demos.id"))
    segment_ids: Mapped[list | None] = mapped_column(JSONB)
    focus_skills: Mapped[list | None] = mapped_column(JSONB)
    deadline: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(String(10), server_default=text("'open'"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    teacher: Mapped["User | None"] = relationship()
    demo: Mapped["TeacherDemo | None"] = relationship()


class Submission(Base):
    """作业提交，含 AI 评分明细、BKT 前后对比与教师评审结果。"""

    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    homework_id: Mapped[int | None] = mapped_column(ForeignKey("homeworks.id"))
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id"))
    audio_id: Mapped[int | None] = mapped_column(ForeignKey("audio_files.id"))
    ai_score: Mapped[float | None] = mapped_column(Float)
    ai_detail: Mapped[dict | None] = mapped_column(JSONB)      # 逐字偏差 + CDM 归因标签
    bkt_before: Mapped[dict | None] = mapped_column(JSONB)
    bkt_after: Mapped[dict | None] = mapped_column(JSONB)
    teacher_score: Mapped[float | None] = mapped_column(Float)
    teacher_comment: Mapped[str | None] = mapped_column(Text)
    voice_comment_audio_id: Mapped[int | None] = mapped_column(ForeignKey("audio_files.id"))
    voice_comment_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(10), server_default=text("'ai_scored'"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)

    homework: Mapped["Homework | None"] = relationship()
    student: Mapped["Student | None"] = relationship()
    # 两个外键都指向 audio_files，必须显式指定 foreign_keys，否则 SQLAlchemy 报
    # AmbiguousForeignKeysError
    audio: Mapped["AudioFile | None"] = relationship(foreign_keys=[audio_id])
    voice_comment_audio: Mapped["AudioFile | None"] = relationship(
        foreign_keys=[voice_comment_audio_id]
    )
