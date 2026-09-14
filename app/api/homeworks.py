from app.api import api_bp
from app.common.decorators import login_required, teacher_required, student_required
from app.response import ok


@api_bp.route("/homeworks",methods=["GET"])
@login_required
@teacher_required
def get_homeworks():
    return ok()

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