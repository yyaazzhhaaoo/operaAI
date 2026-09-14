from app.api import api_bp
from app.response import ok


@api_bp.route("/homeworks",methods=["GET"])
def get_homeworks():
    return ok()

@api_bp.route("/coach/annotations",methods=["POST"])
def post_homeworks():
    return ok()

@api_bp.route("/homeworks/<id>/submit",methods=["POST"])
def homeworks_submit(id):
    return ok(id)

@api_bp.route("/homeworks/<id>/submissions",methods=["GET"])
def homeworks_submissions(id):
    return ok(id)

@api_bp.route("/homeworks/<id>/detail",methods=["GET"])
def homeworks_detail(id):
    return ok(id)

@api_bp.route("/submissions/<id>/review",methods=["POST"])
def submissions_review(id):
    return ok(id)

@api_bp.route("/submissions/<id>/calibration",methods=["POST"])
def submissions_calibration(id):
    return ok(id)