# -*- coding: utf-8 -*-
"""J1–J3 摸底测试接口 + 8.10 跳过（《5-接口清单》2.10）。"""

import math

from flask import request, session, url_for

from app.api import api_bp
from app.common.decorators import current_user_id, login_required, student_required
from app.common.errors import BusinessError
from app.db import get_db
from app.response import ok
from app.schemas.cat import (
    CatQuestionsOut,
    CatReportOut,
    CatSkipOut,
    CatSubmitOut,
)
from app.services import cat_service


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


@api_bp.route("/cat/questions", methods=["GET"])
@login_required
def cat_questions():
    rows = cat_service.questions(get_db())
    for row in rows:
        audio_id = row.pop("audio_id")
        row["audio_url"] = (
            url_for("api.audio_download", file_id=audio_id)
            if audio_id is not None
            else None
        )
    return ok(CatQuestionsOut(questions=rows).model_dump())


@api_bp.route("/cat/submit", methods=["POST"])
@login_required
@student_required
def cat_submit():
    task_id = cat_service.submit(
        get_db(),
        user_id=current_user_id(),
        segment_id=_form_int("segment_id"),
        audio_id=_form_int("audio_id"),
        duration_sec=_duration_sec(),
    )
    return ok(CatSubmitOut(task_id=task_id).model_dump())


@api_bp.route("/cat/report/<int:record_id>", methods=["GET"])
@login_required
def cat_report(record_id):
    out = cat_service.report(
        get_db(),
        user_id=current_user_id(),
        is_student=session.get("role") == "student",
        record_id=record_id,
    )
    return ok(CatReportOut(**out).model_dump())


@api_bp.route("/cat/skip", methods=["POST"])
@login_required
@student_required
def cat_skip():
    out = cat_service.skip(get_db(), user_id=current_user_id())
    return ok(CatSkipOut(**out).model_dump())
