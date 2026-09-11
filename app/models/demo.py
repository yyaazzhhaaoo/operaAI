from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import DateTime,Float,ForeignKey,Integer,String,func,text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped,mapped_column,relationship
from app.db import Base

if TYPE_CHECKING:
    from app.models.audio import AudioFile


class TeacherDemo(Base):
    """示范曲目（剧目级）。"""

    __tablename__ = "teacher_demos"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    role: Mapped[str | None] = mapped_column(String(50))       # 行当
    banshi: Mapped[str | None] = mapped_column(String(50))     # 板式
    audio_id: Mapped[int | None] = mapped_column(ForeignKey("audio_files.id"))
    elo_difficulty: Mapped[float | None] = mapped_column(Float, server_default=text("1000"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    audio: Mapped["AudioFile | None"] = relationship()


class Segment(Base):
    """曲目分段，逐字声学数据与教师提示存在 lyrics_json 里。"""

    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    demo_id: Mapped[int | None] = mapped_column(ForeignKey("teacher_demos.id"))
    seq: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String(100))
    # JSONB 不跟踪原地修改（d["k"]=v 不会自动标脏），改动需整体重新赋值
    lyrics_json: Mapped[list | None] = mapped_column(JSONB)    # [{word,midi,start,end,note,tip}]
    duration: Mapped[float | None] = mapped_column(Float)

    demo: Mapped["TeacherDemo | None"] = relationship()
