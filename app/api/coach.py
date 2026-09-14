from app.api import api_bp
from app.common.decorators import login_required
from app.response import ok


@api_bp.route("/coach/context/<student_id>",methods=["GET"])
@login_required
def coach_context(student_id):
    return ok(student_id)

@api_bp.route("/coach/chat",methods=["POST"])
@login_required
def coach_chat():
    return ok()

@api_bp.route("/coach/history/<student_id>",methods=["GET"])
@login_required
def coach_history(student_id):
    return ok(student_id)