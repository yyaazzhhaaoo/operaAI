# -*- coding: utf-8 -*-
"""A 组认证接口（《5-接口清单-V1.0》）。

    A1  POST /api/auth/login       公开
    A2  POST /api/auth/logout      登录
    A3  GET  /api/auth/me          登录
    A4  POST /api/auth/password    登录

本层只做三件事：校验入参 → 调 service → 组装响应。
不写 SQL、不写业务规则、不写 try/except（错误由 app/common/errors.py 的
全局 handler 兜）。

session 的读写**只在本文件发生**——service 层不碰 flask.session，
因此可以脱离请求上下文测试；「谁改了会话」全项目只有这一处。
"""

from flask import request, session

from app.api import api_bp
from app.common.decorators import current_user_id, login_required
from app.db import get_db
from app.response import ok
from app.schemas.auth import LoginIn, PasswordChangeIn, UserOut
from app.services import auth_service


def _payload() -> dict:
    """取 JSON 请求体。

    客户端没带 Content-Type: application/json 时 get_json() 会抛 415；
    silent=True 把它压成 None，这里再兜成 {}，让 pydantic 报「字段必填」
    而不是让 Flask 抛一个前端看不懂的 415。
    """
    return request.get_json(silent=True) or {}


@api_bp.route("/auth/login", methods=["POST"])
def login():
    """A1 登录（公开）。成功后写会话，返回 UserOut。"""
    data = LoginIn.model_validate(_payload())
    user = auth_service.login(get_db(), data.username, data.password)

    # permanent=True 才会用 PERMANENT_SESSION_LIFETIME（7 天），
    # 否则退出浏览器会话就没了。
    session.permanent = True
    session["user_id"] = user.id
    session["role"] = user.role

    return ok(UserOut.model_validate(user).model_dump())


@api_bp.route("/auth/logout", methods=["POST"])
@login_required
def logout():
    """A2 登出。"""
    session.clear()
    return ok(None)


@api_bp.route("/auth/me")
@login_required
def me():
    """A3 当前登录用户。"""
    user = auth_service.get_user(get_db(), current_user_id())
    return ok(UserOut.model_validate(user).model_dump())


@api_bp.route("/auth/password", methods=["POST"])
@login_required
def change_password():
    """A4 修改密码。成功后清会话，强制用新密码重新登录。"""
    data = PasswordChangeIn.model_validate(_payload())
    db = get_db()
    user = auth_service.get_user(db, current_user_id())
    auth_service.change_password(db, user, data.old, data.new)

    # 改密后原会话作废（DOC_ISSUES.md 第 11 条）
    session.clear()
    return ok(None)
