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

from flask import redirect, session, url_for

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

def student_required(fn):
    """非教师则抛 403。必须叠在 login_required 内层使用。"""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("role") != "student":
            raise BusinessError(403, "需要学生权限")
        return fn(*args, **kwargs)

    return wrapper


def page_login_required(fn):
    """页面版鉴权：未登录 302 到登录页，而不是抛 401。

    与 login_required 的唯一区别是「未登录怎么表达」——接口请求回 401 JSON
    给前端 JS 判断，浏览器地址栏的页面请求要给一个能直接渲染的跳转。
    要复用 login_required 就得改 401 handler 让它按请求路径分流，等于把
    「跳转」这个业务决定藏进错误处理层，且浏览器直接访问 /api/xxx 时会误判。
    独立一个装饰器更显式，也不动 login_required 已有的契约。

    「是否已登录」的判断与 login_required 共用同一个 current_user_id()，
    全项目只有一处登录判定逻辑。
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if current_user_id() is None:
            return redirect(url_for("page.login"))
        return fn(*args, **kwargs)

    return wrapper
