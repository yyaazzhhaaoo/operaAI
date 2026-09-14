from app.api import api_bp
from app.common.decorators import login_required, teacher_required
from app.response import ok


@api_bp.route("/graph",methods=["GET"])
@login_required
@teacher_required
def graph():
    return ok()

@api_bp.route("/graph/node/<id>",methods=["GET"])
@login_required
@teacher_required
def graph_node(id):
    return ok(id)

@api_bp.route("/graph/lock-diagnosis/<id>",methods=["GET"])
@login_required
@teacher_required
def graph_lock_diagnosis(id):
    return ok(id)

@api_bp.route("/graph/layout",methods=["POST"])
@login_required
@teacher_required
def graph_layout():
    return ok()