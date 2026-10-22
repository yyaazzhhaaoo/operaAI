# -*- coding: utf-8 -*-
"""J1–J3 摸底测试与 8.10 跳过的业务逻辑。

J2 复用 B2 分析管线，落 practice_records(source='cat_test') 并更新 BKT；
J3 的 record_id 只作学生锚点，报告返回该生最新画像（口径见 DOC_ISSUES 第 47 条）。
"""

from sqlalchemy.orm import Session

from app.common.errors import BusinessError
from app.models import BktHistory, PracticeRecord
from app.repositories import (
    audio_repo,
    bkt_history_repo,
    cat_questions_repo,
    user_repo,
)
from app.schemas.audio import AnalyzeSubmitIn
from app.schemas.cat import CatSkillOut
from app.services import analyze_service

PROFILE_SKILLS = ("音准控制", "气息支撑", "拖腔", "归韵咬字", "节奏感知")
_SKIP_P_L = 0.35
_SKIP_CONFIDENCE = 0.4


def _own_student_id(db: Session, user_id: int) -> int:
    student_id = user_repo.get_student_id_by_user_id(db, user_id)
    if student_id is None:
        raise BusinessError(403, "当前账号没有学生档案")
    return student_id


def _lyrics_text(lyrics_json) -> str:
    if not isinstance(lyrics_json, list):
        return ""
    return "".join(
        str(item.get("word", ""))
        for item in lyrics_json
        if isinstance(item, dict)
    )


def questions(db: Session) -> list[dict]:
    """J1：启用中的题目，按 seq 排序。audio_url 由 API 层补。"""
    out = []
    for q in cat_questions_repo.list_active(db):
        segment = q.segment
        if segment is None:
            continue
        out.append({
            "id": q.id,
            "seq": q.seq,
            "segment_id": segment.id,
            "title": segment.title or f"第 {q.seq} 句",
            "demo_title": segment.demo.title if segment.demo else "",
            "duration": segment.duration,
            "focus_dims": q.focus_dims if isinstance(q.focus_dims, list) else [],
            "lyrics": _lyrics_text(segment.lyrics_json),
            "audio_id": segment.audio_id,
        })
    return out


def submit(
    db: Session,
    *,
    user_id: int,
    segment_id: int,
    audio_id: int,
    duration_sec: float | None,
) -> str:
    """J2：校验归属与题目后把任务投进 B2 管线。"""
    student_id = _own_student_id(db, user_id)

    audio = audio_repo.get_by_id(db, audio_id)
    if audio is None:
        raise BusinessError(404, "音频不存在")
    if audio.uploader_id != user_id:
        raise BusinessError(403, "只能提交本人录音")

    if cat_questions_repo.get_active_by_segment(db, segment_id) is None:
        raise BusinessError(404, "题目不存在")

    return analyze_service.submit(
        db,
        AnalyzeSubmitIn(segment_id=segment_id, student_audio_id=audio_id),
        persist={
            "kind": "cat_test",
            "student_id": student_id,
            "segment_id": segment_id,
            "audio_id": audio_id,
            "duration_sec": duration_sec,
        },
    )


def _profile(db: Session, student_id: int) -> list[CatSkillOut]:
    latest = {
        row.skill: row
        for row in bkt_history_repo.get_latest_per_skill_for_student(db, student_id)
    }
    out = []
    for skill in PROFILE_SKILLS:
        row = latest.get(skill)
        out.append(CatSkillOut(
            skill=skill,
            p_l=row.p_l if row else None,
            confidence=row.confidence if row else None,
        ))
    return out


def _top3(profile: list[CatSkillOut]) -> list[CatSkillOut]:
    """按 P(L) 升序取最弱 3 项；没有数据的技法排最后。"""
    ranked = sorted(
        profile,
        key=lambda x: (x.p_l is None, x.p_l if x.p_l is not None else 0.0),
    )
    return ranked[:3]


def report(db: Session, *, user_id: int, is_student: bool, record_id: int) -> dict:
    record = db.get(PracticeRecord, record_id)
    if record is None or record.source != "cat_test" or record.student_id is None:
        raise BusinessError(404, "摸底记录不存在")

    if is_student:
        own = _own_student_id(db, user_id)
        if own != record.student_id:
            raise BusinessError(403, "无权查看该记录")

    profile = _profile(db, record.student_id)
    return {
        "record_id": record.id,
        "student_id": record.student_id,
        "profile": profile,
        "top3": _top3(profile),
    }


def skip(db: Session, *, user_id: int) -> dict:
    """8.10：只给还没有 BKT 的技法写默认值，不覆盖已有画像。"""
    student_id = _own_student_id(db, user_id)
    created = 0
    for skill in PROFILE_SKILLS:
        if bkt_history_repo.get_latest_for_student_skill(db, student_id, skill) is not None:
            continue
        db.add(BktHistory(
            student_id=student_id,
            skill=skill,
            p_l=_SKIP_P_L,
            confidence=_SKIP_CONFIDENCE,
            source_type="cat_test",
            source_id=None,
        ))
        created += 1
    db.commit()

    profile = _profile(db, student_id)
    return {"created": created, "profile": profile, "top3": _top3(profile)}
