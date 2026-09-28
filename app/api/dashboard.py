from app.api import api_bp
from app.common.decorators import login_required, teacher_required
from app.common.errors import BusinessError
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
    return ok(dashboard_service.heatmap(get_db()).model_dump())

@api_bp.route("/dashboard/students",methods=["GET"])
@login_required
@teacher_required
def dashboard_students():
    # mode="json"：这个响应里有 datetime（last_practice_at）。走默认的 model_dump()
    # 会把 datetime 对象交给 Flask 的 jsonify，而它按 RFC-822（http_date）序列化，
    # 出来是 "Mon, 21 Sep 2026 06:32:00 GMT" 这种串；mode="json" 出的是
    # ISO-8601（"2026-09-21T14:32:00+08:00"），前端 new Date() 直接能解析。
    return ok(dashboard_service.students(get_db()).model_dump(mode="json"))

@api_bp.route("/students/<id>/recommendations",methods=["GET"])
@login_required
@teacher_required
def students_recommendations(id):
    """G5 学生推荐路径（功能 5.7）。<id> 是 students.id。"""
    try:
        student_id = int(id)
    except (TypeError, ValueError):
        # 非数字的 <id> 与不存在的学生对调用方是同一件事：查无此人。
        # 路由用字符串转换器（与 /students/<id>/bkt-history 等保持一致），
        # 所以脏值要在这里拦，不能靠 Flask 的 int 转换器兜。
        raise BusinessError(404, "学生不存在")
    return ok(dashboard_service.recommendations(get_db(), student_id).model_dump())

@api_bp.route("/dashboard/process-metrics",methods=["GET"])
@login_required
@teacher_required
def dashboard_process_metrics():
    # mode="json"：响应里有 date（week_start）。默认 model_dump() 会给 Flask 一个
    # date 对象，而它按 RFC-822 序列化成 "Mon, 28 Sep 2026 00:00:00 GMT"；
    # mode="json" 出的是 ISO-8601（"2026-09-28"）。同 dashboard_students。
    return ok(dashboard_service.process_metrics(get_db()).model_dump(mode="json"))

@api_bp.route("/dashboard/homework-progress",methods=["GET"])
@login_required
@teacher_required
def dashboard_homework_progress():
    # mode="json"：响应里有 date（deadline）。默认 model_dump() 会给 Flask 一个
    # date 对象，而它按 RFC-822 序列化成 "Sun, 02 Aug 2026 00:00:00 GMT"；
    # mode="json" 出的是 ISO-8601（"2026-08-02"）。同 dashboard_students。
    return ok(dashboard_service.homework_progress(get_db()).model_dump(mode="json"))