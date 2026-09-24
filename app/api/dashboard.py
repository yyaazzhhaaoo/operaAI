from app.api import api_bp
from app.common.decorators import login_required, teacher_required
from app.db import get_db
from app.response import ok
from app.schemas.dashboard import DashBoardSummary
from app.services import dashboard_service


@api_bp.route("/dashboard/summary",methods=["GET"])
@login_required
@teacher_required
def dashboard_summary():
    summary = dashboard_service.summary(get_db())
    return ok(DashBoardSummary.model_validate(summary).model_dump())

@api_bp.route("/dashboard/alerts",methods=["GET"])
@login_required
@teacher_required
def dashboard_alerts():
    return ok(dashboard_service.alerts(get_db()).model_dump())

@api_bp.route("/dashboard/heatmap",methods=["GET"])
@login_required
@teacher_required
def dashboard_heatmap():
    return ok(dashboard_service.heatmap(get_db()))

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