from flask import request

from app.api import api_bp
from app.common.decorators import login_required, teacher_required
from app.response import ok


@api_bp.route("/students",methods=["GET"])
@login_required
@teacher_required
def students():
    return ok()

@api_bp.route("/students/overview",methods=["GET"])
@login_required
@teacher_required
def students_overview():
    return ok()

@api_bp.route("/students/<id>/bkt-history",methods=["GET"])
@login_required
@teacher_required
def students_bkt_history(id):
    days = request.args.get("days")
    return ok({"id":id,"days":days})

@api_bp.route("/students/<id>/events",methods=["GET"])
@login_required
@teacher_required
def students_events(id):
    return ok(id)

@api_bp.route("/students/<id>/skills-detail",methods=["GET"])
@login_required
@teacher_required
def students_skills_detail(id):
    return ok({"id":id})


