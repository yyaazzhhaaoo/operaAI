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
from app.db import get_db
from app.response import ok
from app.schemas.coach import CoachChatIn, CoachContextOut
from app.services import coach_service


def _payload() -> dict:
    """取 JSON 请求体。

    客户端没带 Content-Type: application/json 时 get_json() 会抛 415；
    silent=True 把它压成 None，这里再兜成 {}，让 pydantic 报「字段必填」
    而不是让 Flask 抛一个前端看不懂的 415。与 homeworks/audio_analyze 同款。
    """
    return request.get_json(silent=True) or {}


# 路径参数用 <int:student_id> 而不是 <student_id>：后者是字符串转换器，
# /coach/context/abc 也会匹配进来再进视图去查库；<int:...> 让 Werkzeug 在路由层
# 就挡掉（IntegerConverter 的正则是 \d+），走 errors.py 的统一 404「接口不存在」。
# 与 homeworks.py 的 F5/F6/F7 同款。
@api_bp.route("/coach/context/<int:student_id>", methods=["GET"])
@login_required
@student_required
def coach_context(student_id):
    """E1 客观数据区：摘要 / BKT（逐字偏差、CDM、RAG 为显式空位）。"""
    db = get_db()
    sid = coach_service.resolve_student_id(db, student_id, current_user_id())
    return ok(CoachContextOut.model_validate(
        coach_service.build_context(db, sid)).model_dump(mode="json"))


@api_bp.route("/coach/chat", methods=["POST"])
@login_required
@student_required
def coach_chat():
    """E2 发消息 → AI 回复。契约见《5-接口清单》3.3。"""
    data = CoachChatIn.model_validate(_payload())
    db = get_db()
    sid = coach_service.resolve_student_id(db, data.student_id, current_user_id())
    return ok(coach_service.chat(db, sid, data.message))
