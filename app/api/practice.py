import math

from flask import request, session

from app.api import api_bp
from app.common.decorators import (
    current_user_id,
    login_required,
    student_required,
)
from app.common.errors import BusinessError
from app.db import get_db
from app.response import ok
from app.schemas.practice import PracticeSubmitOut
from app.services import practice_service

_LIMIT_DEFAULT = 50
_LIMIT_MAX = 200


def _form_int(name: str) -> int:
    raw = request.form.get(name)
    if raw is None or raw == "":
        raise BusinessError(400, f"缺少 {name}")
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise BusinessError(400, f"{name} 必须是整数") from None


def _duration_sec() -> float | None:
    raw = request.form.get("duration_sec")
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise BusinessError(400, "duration_sec 必须是数字") from None
    if not math.isfinite(value) or value <= 0:
        raise BusinessError(400, "duration_sec 必须是正数")
    return value


def _query_int(name: str, default: int | None = None) -> int | None:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise BusinessError(400, f"{name} 必须是整数") from None


@api_bp.route("/practice/submit", methods=["POST"])
@login_required
@student_required
def practice_submit():
    task_id = practice_service.submit(
        get_db(),
        user_id=current_user_id(),
        segment_id=_form_int("segment_id"),
        audio_id=_form_int("audio_id"),
        duration_sec=_duration_sec(),
    )
    return ok(PracticeSubmitOut(task_id=task_id).model_dump())


@api_bp.route("/practice/logs", methods=["GET"])
@login_required
def practice_logs():
    limit = _query_int("limit", _LIMIT_DEFAULT)
    offset = _query_int("offset", 0)
    if limit < 1 or limit > _LIMIT_MAX:
        raise BusinessError(400, f"limit 必须在 1–{_LIMIT_MAX} 之间")
    if offset < 0:
        raise BusinessError(400, "offset 不能为负数")

    out = practice_service.logs(
        get_db(),
        is_student=session.get("role") == "student",
        user_id=current_user_id(),
        student_id=_query_int("student_id"),
        segment_id=_query_int("segment_id"),
        limit=limit,
        offset=offset,
    )
    return ok(out.model_dump(mode="json"))


@api_bp.route("/practice/last/<int:segment_id>", methods=["GET"])
@login_required
@student_required
def practice_last(segment_id):
    out = practice_service.last(
        get_db(), user_id=current_user_id(), segment_id=segment_id
    )
    return ok(out.model_dump(mode="json"))
