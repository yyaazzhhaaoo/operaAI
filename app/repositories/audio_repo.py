# -*- coding: utf-8 -*-
"""audio_files 表的数据访问，以及「分段 → 示范音频」的解析。

写操作只 flush()、不 commit——事务边界在 service 层，理由见 CLAUDE.md。
"""

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
) -> AudioFile:
    """登记一条上传记录。file_path 存的是**相对 uploads/ 的路径**（可含一层
    demos/ 这样的子目录），不是绝对路径，也不是裸文件名（见 common/storage.py）。"""
    audio = AudioFile(
        uploader_id=uploader_id,
        file_path=file_path,
        original_name=original_name,
        file_size=file_size,
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
    """分段要用的示范音频：优先该段切出来的音频，没有则回退整首（B2 模式二）。

    历史示范（切分上线前解析的）没有 segments.audio_id，走回退分支，行为与
    改造前完全一致。分段不存在、或剧目没绑音频，都返回 None——调用方统一
    当作 404 处理，对前端而言「这个分段现在没法比对」是同一种情况。
    """
    segment = db.get(Segment, segment_id)
    if segment is None:
        return None

    if segment.audio_id is not None:
        audio = db.get(AudioFile, segment.audio_id)
        if audio is not None:
            return audio

    if segment.demo_id is None:
        return None
    demo = db.get(TeacherDemo, segment.demo_id)
    if demo is None or demo.audio_id is None:
        return None
    return db.get(AudioFile, demo.audio_id)
