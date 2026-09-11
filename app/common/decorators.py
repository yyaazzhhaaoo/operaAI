# -*- coding: utf-8 -*-
"""鉴权装饰器（《6-登录与数据隔离方案-V1.0》第 5 节）。

叠放顺序有意义——login_required 在外层，未登录先 401；
teacher_required 在内层，已登录再判 403：

    @api_bp.route("/students", methods=["POST"])
    @login_required
    @teacher_required
    def create_student(): ...
"""

from functools import wraps

from flask import session

from app.common.errors import BusinessError


def current_user_id():
    """取当前登录用户的 id；未登录返回 None。"""
    return session.get("user_id")


def login_required(fn):
    """未登录则抛 401。"""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("user_id") is None:
            raise BusinessError(401, "未登录")
        return fn(*args, **kwargs)

    return wrapper


def teacher_required(fn):
    """非教师则抛 403。必须叠在 login_required 内层使用。"""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("role") != "teacher":
            raise BusinessError(403, "需要教师权限")
        return fn(*args, **kwargs)

    return wrapper
