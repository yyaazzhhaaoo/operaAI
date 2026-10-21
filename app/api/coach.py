# -*- coding: utf-8 -*-
"""AI 教练对话（模块3）的接口。

《5-接口清单-V1.0》2.5 节：
  E1 GET  /coach/context/<student_id>   客观数据区
  E2 POST /coach/chat                   发消息 → AI 回复
  E3 GET  /coach/history/<student_id>   历史对话
"""
from flask import request

from app.api import api_bp
from app.common.decorators import current_user_id, login_required, student_required
from app.common.errors import BusinessError
from app.db import get_db
from app.repositories import user_repo
from app.response import ok
from app.schemas.coach import ChatMessageOut, CoachChatIn, CoachContextOut
from app.services import coach_service


def _payload() -> dict:
    """取 JSON 请求体（同 auth：silent=True 兜成 {}，免得 415）。"""
    return request.get_json(silent=True) or {}


# 路径参数用 <int:student_id> 而不是 <student_id>：后者是字符串转换器，
# /coach/context/abc 也会匹配进来再进视图去查库；<int:...> 让 Werkzeug 在路由层
# 就挡掉（IntegerConverter 的正则是 \d+），走 errors.py 的统一 404「接口不存在」。
# 与 homeworks.py 的 F5/F6/F7 同款。
@api_bp.route("/coach/context/<int:student_id>", methods=["GET"])
@login_required
@student_required
def coach_context(student_id):
    """E1 客观数据区：摘要 / BKT / 逐字偏差 / CDM（RAG 仍为显式空位）。"""
    db = get_db()
    sid = coach_service.resolve_student_id(db, student_id, current_user_id())
    return ok(CoachContextOut.model_validate(
        coach_service.build_context(
            db, sid, with_deviations=True, with_cdm=True
        )).model_dump(mode="json"))


@api_bp.route("/coach/context/me", methods=["GET"])
@login_required
@student_required
def coach_context_me():
    """E1 的本人便捷入口：路径不带 id。

    文档里 E1 只有带 <student_id> 的那条。加这条是因为页面登进来时只知道
    users.id，而 E1 要的是 students.id（DOC_ISSUES 第 21 条），前端无从换算。
    让它自己报回 student.id，前端再拿它去调带 id 的两条。

    与 /coach/context/<int:student_id> 不冲突：后者带 int 转换器，
    正则只认 \\d+，`me` 匹配不上，会落到这里。
    """
    db = get_db()
    own = user_repo.get_student_id_by_user_id(db, current_user_id())
    if own is None:
        raise BusinessError(403, "AI 教练仅学生可用")
    return ok(CoachContextOut.model_validate(
        coach_service.build_context(
            db, own, with_deviations=True, with_cdm=True
        )).model_dump(mode="json"))


@api_bp.route("/coach/chat", methods=["POST"])
@login_required
@student_required
def coach_chat():
    """E2 发消息 → AI 回复。契约见《5-接口清单》3.3。"""
    data = CoachChatIn.model_validate(_payload())
    db = get_db()
    sid = coach_service.resolve_student_id(db, data.student_id, current_user_id())
    return ok(coach_service.chat(db, sid, data.message))


@api_bp.route("/coach/history/<int:student_id>", methods=["GET"])
@login_required
@student_required
def coach_history(student_id):
    db = get_db()
    sid = coach_service.resolve_student_id(db, student_id, current_user_id())
    # request.args.get 拿到的永远是字符串，非数字会让 int() 抛 ValueError
    # 变成未捕获的 500；给个安全兜底，越界交给下面夹紧。
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 200))
    out = [ChatMessageOut.model_validate(m) for m in coach_service.history(db, sid, limit)]
    return ok([m.model_dump(mode="json") for m in out])
