from app.api import api_bp
from app.common.decorators import login_required, teacher_required, student_required
from app.db import get_db
from app.response import ok
from app.services import homework_service


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

@api_bp.route("/homeworks/<id>/submissions",methods=["GET"])
@login_required
@teacher_required
def homeworks_submissions(id):
    return ok(id)

@api_bp.route("/homeworks/<id>/detail",methods=["GET"])
@login_required
@teacher_required
def homeworks_detail(id):
    return ok(id)

@api_bp.route("/submissions/<id>/review",methods=["POST"])
@login_required
@teacher_required
def submissions_review(id):
    return ok(id)

@api_bp.route("/submissions/<id>/calibration",methods=["POST"])
@login_required
@teacher_required
def submissions_calibration(id):
    return ok(id)