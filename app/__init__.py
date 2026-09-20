"""戏韵AI 后端应用包。

create_app() 是应用的唯一装配点：配置 → 数据库 teardown → 错误处理 → 蓝图。
脚本、测试、celery 都从这里取 app，不要再各自 new 一个 Flask()。
"""

from datetime import timedelta

from flask import Flask

from app.celery_utils import celery_init_app
from app.common.errors import register_error_handlers
from app.config import settings
from app.db import init_app


def create_app(config_overrides=None):
    """装配并返回 Flask 应用。

    config_overrides 供测试覆盖配置（如 {"TESTING": True}），生产不传。
    """
    app = Flask(__name__)
    app.config.from_mapping(
        CELERY=dict(
            # 连接串从 .env 出来（app/config.py 的 celery_broker_url），不再写死
            # localhost:6379/0——项目 redis 是带口令的（REDIS_PASSWORD），写死的
            # 串没有口令，worker 一连 broker 就是 NOAUTH。
            broker_url=settings.celery_broker_url,
            result_backend=settings.celery_broker_url,
            # 结果不往 result backend 里写：B3/B4 的真源是 analyze_task_repo 写在
            # redis 里的 analyze:task:<id> hash（文档 3.1 的 status/progress/stage
            # 三件套，Celery 的 result 表达不了这套语义）。留着 backend 只是排查时
            # 能翻一眼，默认不许它往里写。
            task_ignore_result=True,
            # 分析是分钟级长任务，两条一起配：
            # acks_late 让 worker 被 kill 时消息重回队列重投，而不是随进程一起丢；
            # prefetch=1 让一个 worker 一次只揽一个任务，避免它把队列全攥在手里、
            # 旁边几个 worker 空转。
            task_acks_late=True,
            worker_prefetch_multiplier=1,
            # Celery 6 会把这个默认值翻成 False，显式写死免得升级后行为漂移
            broker_connection_retry_on_startup=True,
        ),
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
    # 必须排在下面注册蓝图之前：注册蓝图会 import app/api/ 下的接口模块，
    # 进而 import analyze_service 里的 @shared_task，那时 Celery 实例得已经在位。
    # （shared_task 是延迟绑定的，顺序错了不会当场报错，只会让任务注册不上。）
    celery_init_app(app)

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
