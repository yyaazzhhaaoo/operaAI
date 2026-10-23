from flask import request

from app.api import api_bp
from app.common.decorators import login_required, teacher_required
from app.common.errors import BusinessError
from app.db import get_db
from app.response import ok
from app.services import student_service


@api_bp.route("/students",methods=["GET"])
@login_required
@teacher_required
def students():
    """能力追踪页的学生芯片列表（功能 5.5 的名单部分）。"""
    return ok(student_service.roster(get_db()))

@api_bp.route("/students/<id>/overview",methods=["GET"])
@login_required
@teacher_required
def students_overview(id):
    """H2 综合统计四项（功能 6.2）。<id> 是 students.id。"""
    try:
        student_id = int(id)
    except (TypeError, ValueError):
        # 非数字 <id> 与查无此人对调用方是同一件事（同 /students/<id>/recommendations）
        raise BusinessError(404, "学生不存在")
    return ok(student_service.overview(get_db(), student_id))

@api_bp.route("/students/<id>/bkt-history",methods=["GET"])
@login_required
@teacher_required
def students_bkt_history(id):
    """H3 P(L) 历史曲线（功能 6.3 / 6.6）。<id> 是 students.id。"""
    try:
        student_id = int(id)
    except (TypeError, ValueError):
        raise BusinessError(404, "学生不存在")
    try:
        days = int(request.args.get("days", "30"))
    except (TypeError, ValueError):
        raise BusinessError(400, "days 必须是 1-365 的整数")
    return ok(student_service.bkt_history(get_db(), student_id, days))

@api_bp.route("/students/<id>/events",methods=["GET"])
@login_required
@teacher_required
def students_events(id):
    """H4 练习事件时间轴（功能 6.8）。<id> 是 students.id。"""
    try:
        student_id = int(id)
    except (TypeError, ValueError):
        raise BusinessError(404, "学生不存在")
    return ok(student_service.events(get_db(), student_id))

@api_bp.route("/students/<id>/skills-detail",methods=["GET"])
@login_required
@teacher_required
def students_skills_detail(id):
    """H5 技法详情表（功能 6.9）。<id> 是 students.id。"""
    try:
        student_id = int(id)
    except (TypeError, ValueError):
        raise BusinessError(404, "学生不存在")
    return ok(student_service.skills_detail(get_db(), student_id))


