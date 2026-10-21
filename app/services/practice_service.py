# -*- coding: utf-8 -*-
"""D1–D3 智能陪练接口的业务逻辑。

D1 复用 B2 的分析管线，任务完成后由 worker 调 `save_result` 落库；D2/D3
只读 practice_records。BKT 更新规则文档未定义，当前是一套临时口径
（见 DOC_ISSUES 第 44 条与 `docs/superpowers/specs/2026-10-19-practice-api-design.md`）。
"""

from sqlalchemy.orm import Session

from app.common.errors import BusinessError
from app.models import BktHistory, PracticeRecord
from app.repositories import (
    audio_repo,
    bkt_history_repo,
    practice_records_repo,
    user_repo,
)
from app.schemas.audio import AnalyzeSubmitIn
from app.schemas.practice import (
    PracticeLastOut,
    PracticeLogsOut,
    PracticeRecordOut,
)
from app.services import analyze_service

# 维度 → bkt_history.skill。技法名沿用库里既有的 8 个（DOC_ISSUES 第 23 条），
# 不另造一套叫法。滑音/装饰音技巧/颤音没有对应维度，本次不更新。
_SKILL_BY_DIMENSION = {
    "音准": "音准控制",
    "节奏": "节奏感知",
    "气息": "气息支撑",
    "咬字": "归韵咬字",
    "拖腔": "拖腔",
}

_BKT_PRIOR = 0.5
_BKT_LEARNING_RATE = 0.3
_BKT_CONFIDENCE_STEP = 0.05


def _own_student_id(db: Session, user_id: int) -> int:
    student_id = user_repo.get_student_id_by_user_id(db, user_id)
    if student_id is None:
        raise BusinessError(403, "当前账号没有学生档案")
    return student_id


def _to_out(record: PracticeRecord) -> PracticeRecordOut:
    return PracticeRecordOut(
        id=record.id,
        student_id=record.student_id,
        segment_id=record.segment_id,
        source=record.source,
        audio_id=record.audio_id,
        ai_score=record.ai_score,
        dimensions=record.dimensions_json,
        duration_sec=record.duration_sec,
        created_at=record.created_at,
    )


def submit(
    db: Session,
    *,
    user_id: int,
    segment_id: int,
    audio_id: int,
    duration_sec: float | None,
) -> str:
    """D1：校验归属后把任务投进 B2 管线，返回 task_id。

    归属只认 `audio_files.uploader_id == 登录用户`：学生拿别人的录音提交，
    分数会记到自己名下，必须挡掉。音频不存在与不属于本人分开报（404/403），
    前者是调用方传错了 id，后者是越权。
    """
    student_id = _own_student_id(db, user_id)

    audio = audio_repo.get_by_id(db, audio_id)
    if audio is None:
        raise BusinessError(404, "音频不存在")
    if audio.uploader_id != user_id:
        raise BusinessError(403, "只能提交本人录音")

    task_id = analyze_service.submit(
        db,
        AnalyzeSubmitIn(segment_id=segment_id, student_audio_id=audio_id),
        persist={
            "kind": "practice",
            "student_id": student_id,
            "segment_id": segment_id,
            "audio_id": audio_id,
            "duration_sec": duration_sec,
        },
    )
    return task_id


def last(db: Session, *, user_id: int, segment_id: int) -> PracticeLastOut:
    """D3：本人该分段最近一次练习；没练过返回 record=null。"""
    student_id = _own_student_id(db, user_id)
    record = practice_records_repo.get_last_for_student_segment(
        db, student_id, segment_id
    )
    return PracticeLastOut(record=_to_out(record) if record else None)


def logs(
    db: Session,
    *,
    is_student: bool,
    user_id: int,
    student_id: int | None,
    segment_id: int | None,
    limit: int,
    offset: int,
) -> PracticeLogsOut:
    """D2：练习日志。学生只能查本人，教师必须指定学生。

    文档权限列只写「登录」，未区分角色（DOC_ISSUES 第 44 条）。这里按
    《6-登录与数据隔离方案》的隔离原则收紧：学生省略 student_id 时默认本人，
    显式传别人直接 403，避免「按 id 枚举」泄漏他人练习数据。
    """
    if is_student:
        own = _own_student_id(db, user_id)
        if student_id is not None and student_id != own:
            raise BusinessError(403, "无权查看该学员的练习记录")
        student_id = own
    elif student_id is None:
        raise BusinessError(400, "教师查询需指定 student_id")

    records = practice_records_repo.list_for_student(
        db, student_id, segment_id=segment_id, limit=limit, offset=offset
    )
    total = practice_records_repo.count_for_student(
        db, student_id, segment_id=segment_id
    )
    return PracticeLogsOut(records=[_to_out(r) for r in records], total=total)


def save_result(metadata: dict, result: dict) -> None:
    """worker 算完分析后落 practice_records 并更新 BKT。

    `metadata` 是 D1 提交时随 Celery 消息传下来的纯数据；这里在**请求之外**
    执行，所以用 `session_scope()` 而不是请求内的 `get_db()`。

    记录与 BKT 必须在同一个事务里：只写记录不写 BKT 会让掌握度停在旧值，
    只写 BKT 不写记录则 BKT 的 source_id 指向一个不存在的行。任何一步失败
    都抛出去，由 run_analysis 把任务置为 failed——前端宁可看不到分数，
    也不该看到一个「有分数但库里查不到」的结果。
    """
    from app.db import session_scope

    with session_scope() as db:
        record = PracticeRecord(
            student_id=metadata["student_id"],
            segment_id=metadata["segment_id"],
            source="practice",
            audio_id=metadata["audio_id"],
            ai_score=result.get("overall"),
            dimensions_json=result.get("dimensions"),
            # 逐字偏差原样落库（B4 已算好）。没有歌词的曲目这里是 []，
            # 与「没有数据源」的 None 区分开；历史结果缺该键时落 NULL。
            words_json=result.get("words"),
            # CDM 归因由分析管线按规则引擎算好；历史结果缺该键时落 NULL
            # （None = 没有数据源，与 defects=[] 的「查了是空」区分）。
            cdm_json=result.get("cdm"),
            duration_sec=metadata.get("duration_sec"),
        )
        db.add(record)
        db.flush()
        apply_bkt(
            db,
            student_id=record.student_id,
            dimensions=record.dimensions_json,
            source_type="practice",
            source_id=record.id,
        )


def apply_bkt(
    db: Session,
    *,
    student_id: int,
    dimensions: dict | None,
    source_type: str,
    source_id: int,
) -> tuple[dict, dict]:
    """按维度分数移动掌握度，返回 (本次更新前, 本次更新后) 的 P(L) 字典。

    规则是临时口径（DOC_ISSUES 第 44 条），第 4 周标定时替换。D1 练习与
    F3 作业提交共用这一份，只有 `source_type` / `source_id` 不同：两处各写
    一套的话，同一份 B4 结果会在两条链路里推出不同的掌握度。

    `before` / `after` 只包含本次真正更新了的技法（维度分非数值的跳过），
    形状是「技法名 → P(L)」的扁平字典，正好是 F5 `_bkt_changes` 读取的形状。
    """
    before: dict = {}
    after: dict = {}
    dims = dimensions if isinstance(dimensions, dict) else {}

    for dimension, skill in _SKILL_BY_DIMENSION.items():
        score = dims.get(dimension)
        # bool 是 int 的子类；JSONB 里的字符串/"80" 也不能当分数用。
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            continue

        previous = bkt_history_repo.get_latest_for_student_skill(
            db, student_id, skill
        )
        old_p_l = previous.p_l if previous else _BKT_PRIOR
        new_p_l = old_p_l + _BKT_LEARNING_RATE * (score / 100.0 - old_p_l)
        old_confidence = (
            previous.confidence
            if previous is not None and previous.confidence is not None
            else _BKT_PRIOR
        )

        before[skill] = old_p_l
        after[skill] = min(1.0, max(0.0, new_p_l))
        db.add(BktHistory(
            student_id=student_id,
            skill=skill,
            p_l=after[skill],
            confidence=min(1.0, old_confidence + _BKT_CONFIDENCE_STEP),
            source_type=source_type,
            source_id=source_id,
        ))
    return before, after
