from app.api import api_bp
from app.response import ok


@api_bp.route("/graph",methods=["GET"])
def graph():
    return ok()

@api_bp.route("/graph/node/<id>",methods=["GET"])
def graph_node(id):
    return ok(id)

@api_bp.route("/graph/lock-diagnosis/<id>",methods=["GET"])
def graph_lock_diagnosis(id):
    return ok(id)

@api_bp.route("/graph/layout",methods=["POST"])
def graph_layout():
    return ok()