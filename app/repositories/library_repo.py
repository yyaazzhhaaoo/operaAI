# -*- coding: utf-8 -*-
"""teacher_demos / segments 表的数据访问。

写操作只 flush()、不 commit——事务边界在 service 层，理由见 CLAUDE.md。
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import TeacherDemo
from app.models.audio import AudioFile
from app.models.demo import Segment


def get_library_list(db: Session) -> list[TeacherDemo] | None:
    return list(db.scalars(select(TeacherDemo)).all())


def add_library(db: Session, teacher_demo: TeacherDemo) -> TeacherDemo:
    """新增一条示范曲目。只 flush 拿自增 id，提交交给 service 层。"""
    db.add(teacher_demo)
    db.flush()
    return teacher_demo


def get_demo(db: Session, demo_id: int) -> TeacherDemo | None:
    return db.get(TeacherDemo, demo_id)


def list_segments(db: Session, demo_id: int) -> list[Segment]:
    """按 seq 升序取某 demo 的分段。前端就按这个顺序显示「第 N 段」。"""
    return list(db.scalars(
        select(Segment).where(Segment.demo_id == demo_id).order_by(Segment.seq)
    ).all())


def replace_segments(db: Session, demo_id: int, segments: list[dict]) -> None:
    """整批替换某 demo 的分段：先按 demo_id DELETE，再 INSERT。

    幂等的关键：同一 demo 重跑解析不会累积脏行（解析任务整体可重入）。
    不用「按 seq upsert」是因为段数可能变少（阈值调过、素材换过），
    upsert 会留下上一轮多出来的尾巴。

    参数是纯 dict（[{seq,title,duration}]）而不是 ORM 对象：分段在 worker
    进程里用 numpy 算出来，那边根本没有 Session。

    lyrics_json 一律 NULL——第 20 条：没有 ASR 组件，音频给不出汉字。
    segments 表也没有 start/end 列（本次不加），所以位置信息只有 seq 与 duration。

    只 flush 不 commit；DELETE 由 Core 语句当场发出，必然排在 flush 的
    INSERT 之前，不会出现「新行插进去又被删掉」。
    """
    db.execute(delete(Segment).where(Segment.demo_id == demo_id))
    db.add_all([
        Segment(
            demo_id=demo_id,
            seq=s["seq"],
            title=s["title"],
            lyrics_json=None,
            duration=s["duration"],
        )
        for s in segments
    ])
    db.flush()


def update_audio_duration(db: Session, demo_id: int, duration_sec: float) -> None:
    """把音频的真实全长回填到 audio_files.duration_sec。

    回填的是**文件真实时长**，不是 MAX_AUDIO_SEC 截断后的长度——列表页显示的
    时长必须如实（spec 4.3）。demo 或 audio 缺失时静默返回：回填是锦上添花，
    不该因为它失败而让整轮解析落成 error。
    """
    demo = db.get(TeacherDemo, demo_id)
    if demo is None or demo.audio_id is None:
        return
    audio = db.get(AudioFile, demo.audio_id)
    if audio is None:
        return
    audio.duration_sec = duration_sec
    db.flush()
