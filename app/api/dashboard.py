from app.api import api_bp
from app.response import ok


@api_bp.route("/dashboard/summary",methods=["GET"])
def dashboard_summary():
    return ok()

@api_bp.route("/dashboard/alerts",methods=["GET"])
def dashboard_alerts():
    return ok()

@api_bp.route("/dashboard/heatmap",methods=["GET"])
def dashboard_heatmap():
    return ok()

@api_bp.route("/dashboard/students",methods=["GET"])
def dashboard_students():
    return ok()

@api_bp.route("/students/<id>/recommendations",methods=["GET"])
def students_recommendations():
    return ok()

@api_bp.route("/dashboard/process-metrics",methods=["GET"])
def dashboard_process_metrics():
    return ok();

@api_bp.route("/dashboard/homework-progress",methods=["GET"])
def dashboard_homework_progress():
    return ok()