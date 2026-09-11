from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import DateTime,Float,ForeignKey,Integer,String,func,text
from sqlalchemy.orm import Mapped,mapped_column,relationship
from app.db import Base

if TYPE_CHECKING:
    from app.models.user import User


class AudioFile(Base):
    """音频文件登记表——权限校验的依据。

    access=public 为示范音频，所有登录用户可听；
    access=private 为学生录音，仅上传者本人与教师可听。
    """

    __tablename__ = "audio_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    uploader_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    file_path: Mapped[str] = mapped_column(String(255))
    original_name: Mapped[str | None] = mapped_column(String(255))
    file_size: Mapped[int | None] = mapped_column(Integer)
    duration_sec: Mapped[float | None] = mapped_column(Float)
    access: Mapped[str | None] = mapped_column(String(10), server_default=text("'private'"))
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    uploader: Mapped["User | None"] = relationship()
