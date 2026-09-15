"""戏韵AI 后端应用包。

create_app() 是应用的唯一装配点：配置 → 数据库 teardown → 错误处理 → 蓝图。
脚本、测试、celery 都从这里取 app，不要再各自 new 一个 Flask()。
"""

from datetime import timedelta

from flask import Flask

from app.common.errors import register_error_handlers
from app.config import settings
from app.db import init_app


def create_app(config_overrides=None):
    """装配并返回 Flask 应用。

    config_overrides 供测试覆盖配置（如 {"TESTING": True}），生产不传。
    """
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=settings.secret_key,
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),   # 《6》第 3 节：会话 7 天
        SESSION_COOKIE_HTTPONLY=True,                   # 《6》第 3 节：HttpOnly
        SESSION_COOKIE_SAMESITE="Lax",                  # 《6》第 3 节：SameSite=Lax
        SESSION_COOKIE_SECURE=settings.session_cookie_secure,
    )
    if config_overrides:
        app.config.update(config_overrides)

    # Flask 3.x 已移除 JSON_AS_ASCII 配置项，改在这里设。不设的话返回的中文
    # 全是 \uXXXX 转义，虽然前端 JSON.parse 后能正确显示，但抓包与日志都没法读。
    app.json.ensure_ascii = False

    init_app(app)                  # 请求结束关闭数据库会话，与 get_db() 配对
    register_error_handlers(app)

    # import 必须在 register_blueprint 之前：这行会触发 app/api/__init__.py
    # 末尾的注册清单（`from . import auth`），业务路由到那时才挂到 api_bp 上。
    # 若先 register 再 import，注册时蓝图里还是空的，所有路由静默失效。
    from app.api import api_bp

    app.register_blueprint(api_bp)

    # 页面路由：无前缀、不挂 api_bp，故不在 app/api/ 的注册清单里，
    # 在此显式注册。与上面同样的顺序约束——import 必须在 register 之前。
    from app.pages import page_bp

    app.register_blueprint(page_bp)
    return app
