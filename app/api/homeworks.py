from flask import request

from app.api import api_bp
from app.common.decorators import (
    current_user_id,
    login_required,
    student_required,
    teacher_required,
)
from app.common.errors import BusinessError
from app.db import get_db
from app.response import ok
from app.schemas.homework import (
    HomeworkCreateIn,
    SubmissionCalibrationIn,
    SubmissionReviewIn,
)
from app.services import homework_service


def _payload() -> dict:
    """取 JSON 请求体（同 auth：silent=True 兜成 {}，免得 415）。"""
    return request.get_json(silent=True) or {}


@api_bp.route("/homeworks",methods=["GET"])
@login_required
@teacher_required
def get_homeworks():
    # 同 dashboard_students：mode="json" 才有 ISO-8601（deadline 是 date）
    return ok(homework_service.list_homeworks(get_db()).model_dump(mode="json"))

@api_bp.route("/homeworks", methods=["POST"])
@login_required
@teacher_required
def post_homeworks():
    # F2 布置新作业（功能 4.2）。本桩原先错挂成 /coach/annotations（DOC_ISSUES 第
    # 34.3 条），2026-10-21 移回《5-接口清单》的地址。
    # teacher_id 在路由层从 session 取，service 不碰 flask.session（同 F7）。
    data = HomeworkCreateIn.model_validate(_payload())
    item = homework_service.create_homework(
        get_db(), data, teacher_id=current_user_id())
    # 同 dashboard_students：mode="json" 才有 ISO-8601（deadline 是 date）
    return ok(item.model_dump(mode="json"))


def _form_int(name: str) -> int:
    """取 multipart 整数表单字段，缺字段/非整数回 400（同 D1 的 _form_int）。"""
    raw = request.form.get(name)
    if raw is None or raw == "":
        raise BusinessError(400, f"缺少 {name}")
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise BusinessError(400, f"{name} 必须是整数") from None


@api_bp.route("/homeworks/mine", methods=["GET"])
@login_required
@student_required
def homeworks_mine():
    # 同 dashboard_students：mode="json" 才有 ISO-8601（deadline/submitted_at）
    return ok(homework_service.list_my_homeworks(
        get_db(), user_id=current_user_id()).model_dump(mode="json"))


@api_bp.route("/homeworks/mine/<int:homework_id>", methods=["GET"])
@login_required
@student_required
def homeworks_mine_detail(homework_id):
    return ok(homework_service.my_homework_detail(
        get_db(),
        user_id=current_user_id(),
        homework_id=homework_id,
    ).model_dump(mode="json"))


@api_bp.route("/homeworks/<int:homework_id>/submit", methods=["POST"])
@login_required
@student_required
def homeworks_submit(homework_id):
    # 路径参数用 <int:...> 而不是 <id>：<id> 是字符串转换器，会把
    # /homeworks/abc/submit 也匹配进来再进视图；<int:...> 让 Werkzeug 在路由层
    # 挡掉，走 errors.py 的统一 404「接口不存在」。同 F4/F5/F6。
    #
    # 返回两种形状：复用练习成绩时是 {"submission_id": N}（同步完成，不用轮询）；
    # 没有练习记录、回退分析管线时是 {"task_id": "..."}（照旧走 B3）。
    return ok(homework_service.submit_homework(
        get_db(),
        user_id=current_user_id(),
        homework_id=homework_id,
        segment_id=_form_int("segment_id"),
        audio_id=_form_int("audio_id"),
    ))

@api_bp.route("/homeworks/<int:homework_id>/submissions",methods=["GET"])
@login_required
@teacher_required
def homeworks_submissions(homework_id):
    # 同 dashboard_students：mode="json" 才有 ISO-8601（submitted_at 是 datetime）
    return ok(homework_service.list_pending_submissions(
        get_db(), homework_id).model_dump(mode="json"))

@api_bp.route("/submissions/<int:submission_id>/detail",methods=["GET"])
@login_required
@teacher_required
def submissions_detail(submission_id):
    # 同 dashboard_students：mode="json" 才有 ISO-8601（submitted_at / reviewed_at）
    return ok(homework_service.submission_detail(
        get_db(), submission_id).model_dump(mode="json"))

@api_bp.route("/submissions/<int:submission_id>/review",methods=["POST"])
@login_required
@teacher_required
def submissions_review(submission_id):
    # 路径参数用 <int:...> 而不是 <id>：<id> 是字符串转换器，会把
    # /submissions/abc/review 也匹配进来再进视图去查库；<int:...> 让 Werkzeug 在
    # 路由层就挡掉（IntegerConverter 的正则是 \d+，连负数都不收），走 errors.py
    # 的统一 404「接口不存在」。同文件 F1/F4/F5。
    #
    # 同 dashboard_students：mode="json" 才有 ISO-8601（reviewed_at 是 datetime）
    data = SubmissionReviewIn.model_validate(_payload())
    return ok(homework_service.review_submission(
        get_db(), submission_id, data).model_dump(mode="json"))

@api_bp.route("/submissions/<int:submission_id>/calibration",methods=["POST"])
@login_required
@teacher_required
def submissions_calibration(submission_id):
    # 路径参数用 <int:submission_id> 而不是 <id>：<id> 是字符串转换器，
    # /submissions/abc/calibration 也会匹配进来再进视图去查库；<int:...> 让 Werkzeug
    # 在路由层就挡掉（IntegerConverter 的正则是 \d+），走 errors.py 的统一 404。同 F1/F4/F5/F6。
    #
    # teacher_id 在路由层从 session 取，service 不碰 flask.session（见 service 的注释）。
    data = SubmissionCalibrationIn.model_validate(_payload())
    out = homework_service.calibrate_submission(
        get_db(), submission_id, data, teacher_id=current_user_id())
    # 撤销（bias_mode = null）时 out 是 None，None.model_dump() 会炸，所以判空。
    return ok(out.model_dump(mode="json") if out else None)