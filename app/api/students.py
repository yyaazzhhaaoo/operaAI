from flask import request

from app.api import api_bp
from app.response import ok


@api_bp.route("/students",methods=["GET"])
def students():
    return ok()

@api_bp.route("/students/overview",methods=["GET"])
def students_overview():
    return ok()

@api_bp.route("/students/<id>/bkt-history",methods=["GET"])
def students_bkt_history(id):
    days = request.args.get("days")
    return ok({"id":id,"days":days})

@api_bp.route("/students/<id>/events",methods=["GET"])
def students_events(id):
    return ok(id)

@api_bp.route("/students/<id>/skills-detail",methods=["GET"])
def students_skills_detail(id):
    return ok({"id":id})


