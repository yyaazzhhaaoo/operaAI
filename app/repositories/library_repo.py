# -*- coding: utf-8 -*-
"""teacher_demos / segments 表的数据访问。

写操作只 flush()、不 commit——事务边界在 service 层，理由见 CLAUDE.md。
"""

from sqlalchemy import delete, func, select
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


def get_segment(db: Session, segment_id: int) -> Segment | None:
    """按主键取单个分段。供 C3。

    用 db.get 而不是 select().where()：它先查会话的 identity map，命中就不发 SQL。
    这里没有 join 需求，主键查询就是全部。
    """
    return db.get(Segment, segment_id)


def get_segment_demo_map(db: Session) -> dict[int, int]:
    """segments.id -> demo_id，一次取全表。

    推荐（功能 5.7）用它把知识图谱的唱段节点换回它所属的曲目——难度
    （teacher_demos.elo_difficulty）与标题都挂在曲目上，不在唱段节点上。
    """
    return {
        seg_id: demo_id
        for seg_id, demo_id in db.execute(select(Segment.id, Segment.demo_id)).all()
        if demo_id is not None
    }


def replace_segments(db: Session, demo_id: int, segments: list[dict]) -> None:
    """整批替换某 demo 的分段：先按 demo_id DELETE，再 INSERT。

    幂等的关键：同一 demo 重跑解析不会累积脏行（解析任务整体可重入）。
    不用「按 seq upsert」是因为段数可能变少（阈值调过、素材换过），
    upsert 会留下上一轮多出来的尾巴。

    参数是纯 dict（[{seq,title,duration,lyrics?}]）而不是 ORM 对象：分段可能
    在 worker 进程里用 numpy 算出来，那边根本没有 Session。

    lyrics 来自上传时附带的逐字数据（app/services/lyrics_excel.py）；没有它
    时（Demucs 那条路）为 None——第 20 条：音频本身给不出汉字。segments 表没有
    start/end 列，逐字的位置信息全在 lyrics_json 里。

    dict 里的 audio_id 由解析管线在登记 audio_files 后填入；Excel 路径没有，
    s.get("audio_id") 得到 None。

    只 flush 不 commit；DELETE 由 Core 语句当场发出，必然排在 flush 的
    INSERT 之前，不会出现「新行插进去又被删掉」。
    """
    db.execute(delete(Segment).where(Segment.demo_id == demo_id))
    db.add_all([
        Segment(
            demo_id=demo_id,
            seq=s["seq"],
            title=s["title"],
            lyrics_json=s.get("lyrics"),
            duration=s["duration"],
            audio_id=s.get("audio_id"),
        )
        for s in segments
    ])
    db.flush()


def get_demo_list(db: Session) -> list[tuple[TeacherDemo, int]]:
    """全部曲目 + 各自的分段数，按 id 升序。供 C1 `GET /api/demos`。

    outerjoin 而非 join：没解析出分段的曲目也要出现在列表里（spec 3.3），
    join 会把它们整条丢掉。

    计数写 count(Segment.id) 而非 count(*)：outerjoin 未命中时 segments 侧
    全是 NULL，count(*) 会数成 1，count(Segment.id) 才是 0。

    一条 SQL 查完，不做 N+1。注意这与 demo_library_list 的取舍不同——那边逐行
    查一次 redis（状态在 redis 里），这里没有那个约束。

    返回 (TeacherDemo, 分段数) 二元组而不是往模型上挂个临时属性：分段数不是
    模型上的列，挂上去会让「哪些字段来自库、哪些是算出来的」变得看不出来。

    duration 不在这里取——它挂在 audio_files 上，由 service 层经 demo.audio
    关系惰性加载（逐行一次查询，曲目量级是几十条，够用；真到几百条再改 joinedload）。
    """
    return list(db.execute(
        select(TeacherDemo, func.count(Segment.id))
        .outerjoin(Segment, Segment.demo_id == TeacherDemo.id)
        .group_by(TeacherDemo.id)
        .order_by(TeacherDemo.id)
    ).all())


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
