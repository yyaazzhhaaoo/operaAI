from app.api import api_bp
from app.response import ok


@api_bp.route("/cat/questions",methods=["GET"])
def cat_questions():
    return ok()

@api_bp.route("/cat/submit",methods=["POST"])
def cat_submit():
    return ok()

@api_bp.route("/cat/report/<record_id>",methods=["GET"])
def cat_report(record_id):
    return ok(record_id)