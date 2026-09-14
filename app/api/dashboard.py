from app.api import api_bp
from app.common.decorators import login_required, teacher_required
from app.response import ok


@api_bp.route("/dashboard/summary",methods=["GET"])
@login_required
@teacher_required
def dashboard_summary():
    return ok()

@api_bp.route("/dashboard/alerts",methods=["GET"])
@login_required
@teacher_required
def dashboard_alerts():
    return ok()

@api_bp.route("/dashboard/heatmap",methods=["GET"])
@login_required
@teacher_required
def dashboard_heatmap():
    return ok()

@api_bp.route("/dashboard/students",methods=["GET"])
@login_required
@teacher_required
def dashboard_students():
    return ok()

@api_bp.route("/students/<id>/recommendations",methods=["GET"])
@login_required
@teacher_required
def students_recommendations():
    return ok()

@api_bp.route("/dashboard/process-metrics",methods=["GET"])
@login_required
@teacher_required
def dashboard_process_metrics():
    return ok();

@api_bp.route("/dashboard/homework-progress",methods=["GET"])
@login_required
@teacher_required
def dashboard_homework_progress():
    return ok()