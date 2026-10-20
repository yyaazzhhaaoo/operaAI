# -*- coding: utf-8 -*-
"""audio_files 表的数据访问，以及「分段 → 示范音频」的解析。

写操作只 flush()、不 commit——事务边界在 service 层，理由见 CLAUDE.md。
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.audio import AudioFile
from app.models.demo import Segment, TeacherDemo


def create(
    db: Session,
    *,
    uploader_id: int | None,
    file_path: str,
    original_name: str | None,
    file_size: int,
    access: str,
    duration_sec: float | None = None,
) -> AudioFile:
    """登记一条上传记录。file_path 存的是**相对 uploads/ 的路径**（可含一层
    demos/ 这样的子目录），不是绝对路径，也不是裸文件名（见 common/storage.py）。

    duration_sec 供解析管线登记分段音频时直接写入；普通上传不传，仍为 NULL。
    """
    audio = AudioFile(
        uploader_id=uploader_id,
        file_path=file_path,
        original_name=original_name,
        file_size=file_size,
        duration_sec=duration_sec,
        access=access,
    )
    db.add(audio)
    db.flush()          # 只为拿到自增 id，提交由 service 层负责
    return audio


def get_by_id(db: Session, audio_id: int) -> AudioFile | None:
    return db.get(AudioFile, audio_id)


def get_segment(db: Session, segment_id: int) -> Segment | None:
    """按 id 取分段。

    放在本文件是因为目前只有 B2 用它（要读 lyrics_json 当逐字时间轴）；
    等 S 组分段接口落地、需要按剧目列分段时，再抽成独立的 segment_repo。
    """
    return db.get(Segment, segment_id)


def get_segment_teacher_audio(db: Session, segment_id: int) -> AudioFile | None:
    """B2 模式二的教师轨：优先用该分段自己的音频，其次回退到整首示范音频。

    segments.audio_id 由 Demucs 解析产出；Excel 路径与旧数据为 NULL，
    继续走 segments → teacher_demos → audio_files 的老路。
    两者都没有返回 None，调用方统一按 404 处理。
    """
    segment = db.get(Segment, segment_id)
    if segment is None:
        return None
    if segment.audio_id is not None:
        audio = db.get(AudioFile, segment.audio_id)
        if audio is not None:
            return audio

    stmt = (
        select(AudioFile)
        .join(TeacherDemo, TeacherDemo.audio_id == AudioFile.id)
        .join(Segment, Segment.demo_id == TeacherDemo.id)
        .where(Segment.id == segment_id)
    )
    return db.scalar(stmt)


def delete_ids(db: Session, ids: list[int]) -> None:
    """按主键批量删除音频登记。只 flush 不 commit，事务边界在 service 层。

    segments.audio_id 的外键行必须先于本调用删除，否则会撞外键约束。
    """
    if not ids:
        return
    db.execute(delete(AudioFile).where(AudioFile.id.in_(ids)))
