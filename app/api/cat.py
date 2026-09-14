from app.api import api_bp
from app.common.decorators import login_required, student_required
from app.response import ok


@api_bp.route("/cat/questions",methods=["GET"])
@login_required
def cat_questions():
    return ok()

@api_bp.route("/cat/submit",methods=["POST"])
@login_required
@student_required
def cat_submit():
    return ok()

@api_bp.route("/cat/report/<record_id>",methods=["GET"])
@login_required
def cat_report(record_id):
    return ok(record_id)