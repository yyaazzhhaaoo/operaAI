from flask import request

from app.api import api_bp
from app.common.decorators import (
    current_user_id,
    login_required,
    student_required,
    teacher_required,
)
from app.db import get_db
from app.response import ok
from app.schemas.homework import SubmissionCalibrationIn, SubmissionReviewIn
from app.services import homework_service


def _payload() -> dict:
    """取 JSON 请求体。

    客户端没带 Content-Type: application/json 时 get_json() 会抛 415；
    silent=True 把它压成 None，这里再兜成 {}，让 pydantic 报「字段必填」
    而不是让 Flask 抛一个前端看不懂的 415。
    """
    return request.get_json(silent=True) or {}


@api_bp.route("/homeworks",methods=["GET"])
@login_required
@teacher_required
def get_homeworks():
    # mode="json"：出参里有 date（deadline）。默认 model_dump() 会给 Flask 一个
    # date 对象，而它按 RFC-822 序列化成 "Sun, 02 Aug 2026 00:00:00 GMT"；
    # mode="json" 出的是 ISO-8601（"2026-08-02"）。同 dashboard_homework_progress。
    return ok(homework_service.list_homeworks(get_db()).model_dump(mode="json"))

@api_bp.route("/coach/annotations",methods=["POST"])
@login_required
@teacher_required
def post_homeworks():
    return ok()

@api_bp.route("/homeworks/<id>/submit",methods=["POST"])
@login_required
@student_required
def homeworks_submit(id):
    return ok(id)

@api_bp.route("/homeworks/<int:homework_id>/submissions",methods=["GET"])
@login_required
@teacher_required
def homeworks_submissions(homework_id):
    # mode="json"：出参里有 datetime（submitted_at）。默认 model_dump() 会给 Flask
    # 一个 datetime 对象，而它按 RFC-822 序列化成 "Sat, 01 Aug 2026 00:00:00 GMT"；
    # mode="json" 出的是 ISO-8601（"2026-08-01T00:00:00"）。同 get_homeworks。
    return ok(homework_service.list_pending_submissions(
        get_db(), homework_id).model_dump(mode="json"))

@api_bp.route("/submissions/<int:submission_id>/detail",methods=["GET"])
@login_required
@teacher_required
def submissions_detail(submission_id):
    # mode="json"：出参里有 datetime（submitted_at / reviewed_at）。默认 model_dump()
    # 会给 Flask 一个 datetime 对象，而它按 RFC-822 序列化成
    # "Sat, 01 Aug 2026 00:00:00 GMT"；mode="json" 出的是 ISO-8601。同 F1/F4。
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
    # mode="json"：出参里有 datetime（reviewed_at）。默认 model_dump() 会给 Flask
    # 一个 datetime 对象，它按 RFC-822 序列化成 "Thu, 08 Oct 2026 00:00:00 GMT"；
    # mode="json" 出的是 ISO-8601。同 F1/F4/F5。
    data = SubmissionReviewIn.model_validate(_payload())
    return ok(homework_service.review_submission(
        get_db(), submission_id, data).model_dump(mode="json"))

@api_bp.route("/submissions/<int:submission_id>/calibration",methods=["POST"])
@login_required
@teacher_required
def submissions_calibration(submission_id):
    # 路径参数从原来的 <id> 改成 <int:submission_id>：<id> 是字符串转换器，
    # /submissions/abc/calibration 也会匹配进来再进视图去查库；<int:...> 让 Werkzeug
    # 在路由层就挡掉（IntegerConverter 的正则是 \d+），走 errors.py 的统一 404。同 F1/F4/F5/F6。
    #
    # teacher_id 在路由层从 session 取，service 不碰 flask.session（见 service 的注释）。
    data = SubmissionCalibrationIn.model_validate(_payload())
    out = homework_service.calibrate_submission(
        get_db(), submission_id, data, teacher_id=current_user_id())
    # 撤销（bias_mode = null）时 out 是 None，None.model_dump() 会炸，所以判空。
    return ok(out.model_dump(mode="json") if out else None)