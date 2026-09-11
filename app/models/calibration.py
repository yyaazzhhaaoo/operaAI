from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import DateTime,Float,ForeignKey,String,func
from sqlalchemy.orm import Mapped,mapped_column,relationship
from app.db import Base

if TYPE_CHECKING:
    from app.models.homework import Submission
    from app.models.user import User


class ScoreCalibration(Base):
    """AI 评分校准记录（教师终审与 AI 评分的偏差）。"""

    __tablename__ = "score_calibrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int | None] = mapped_column(ForeignKey("submissions.id"))
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    bias_mode: Mapped[str | None] = mapped_column(String(10))   # high(偏高)/low(偏低)/ok
    ai_score: Mapped[float | None] = mapped_column(Float)
    teacher_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    submission: Mapped["Submission | None"] = relationship()
    teacher: Mapped["User | None"] = relationship()
