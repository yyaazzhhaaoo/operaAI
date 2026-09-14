"""`/api` 蓝图——全项目接口前缀的唯一来源。

《5-接口清单-V1.0》第 1 节定的 Base URL 是 `/api`。这个前缀只在下面
`API_PREFIX` 这一处写死：业务路由一律写不带前缀的相对路径
（`@api_bp.route("/demos")`），将来要加要改（比如上 `/api/v2`）都只动本文件。

Flask 没有 Spring Boot 的 `server.servlet.context-path` 那样的全局配置项，
蓝图 `url_prefix` 就是它的等价物——但作用范围是挂在蓝图上的路由，不是整个 app。
所以留在 Flask 实例上的路由（如 `app-d.py` 的根路由 `/`）不受这里影响。

演示路由（`app-d.py` 的上传/分析）刻意**不**挂在本蓝图上：它们在
`create_app()` 之后才定义，而 Flask 规定 `register_blueprint()` 之后不能再往
该蓝图加路由（会抛 AssertionError）。它们改用同样读 `API_PREFIX` 的独立
`demo_bp`，详见 app-d.py 里的说明。
"""

from flask import Blueprint

API_PREFIX = "/api"

api_bp = Blueprint("api", __name__, url_prefix=API_PREFIX)

# ↓↓↓ 注册清单 ↓↓↓
# 每新增一个接口模块都必须在此加一行 import，否则它的路由不会生效
# （Blueprint.route 只是把注册动作记进 deferred_functions，模块不被 import
# 就没人执行它）。与 app/models/__init__.py 的约定同构。
#
# import 必须放在 api_bp 定义之后：各子模块要 `from app.api import api_bp`
# 才能挂路由，放前面会循环导入。
from . import auth  # noqa: E402,F401  ← 注册清单：新增模块在此加一行
from . import audio_analyze  # noqa: E402,F401
from . import demos_segments_annotations
from . import practice
from . import coach
from . import homeworks
from . import dashboard
from . import students
from . import graph
from . import cat
from . import health