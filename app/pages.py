# -*- coding: utf-8 -*-
"""页面路由：把 12 个 HTML 收进 Flask，逐页挂鉴权。

页面不是接口，所以这个蓝图**没有 url_prefix**——/api 是接口的 Base URL
（《5-接口清单》第 1 节），页面挂在站点根下（/dashboard.html）。

也因此它**不进** app/api/__init__.py 末尾那份注册清单（那份清单只管挂在
api_bp 上的接口模块），改由 app/__init__.py::create_app() 显式导入并注册
——与 app-d.py 的 demo_bp 同一模式。

为什么页面要经 Flask：页面原本由 nginx `try_files` 静态直供，压根不进
Flask，login_required 加在哪都作用不到页面上。改经本蓝图转发后，
「未登录不能看页面」才是服务端强制的。
"""

from pathlib import Path

from flask import Blueprint, send_from_directory

from app.common.decorators import page_login_required

# app/pages.py → parents[0]=app/ → parents[1]=项目根
PAGES_DIR = Path(__file__).resolve().parents[1]

page_bp = Blueprint("page", __name__)


@page_bp.route("/login.html")
def login():
    """登录页。全站唯一的公开页面。"""
    return send_from_directory(PAGES_DIR, "login.html")


# 受保护页面：除登录页外的全部页面。
# 新增页面时在这里加一项即可，勿另写 @page_bp.route 装饰器。
PROTECTED_PAGES = [
    "index",
    "dashboard",
    "demo_library",
    "annotation",
    "homework",
    "tracking",
    "knowledge_graph",
    "cdm_report",
    "recommendation",
    "sing_along",
    "AI_teacher",
    "pitch_comparison",
]


def _serve(name):
    """返回一个把 <name>.html 发出去的视图函数。"""

    def view():
        # send_from_directory 而非 send_file：入参是目录 + 文件名，对 '..'
        # 做了转义校验。这里 name 全部来自上面的字面量列表、不来自请求，
        # 保持这个习惯是为了让后来者照抄时天然安全。
        #
        # Cache-Control 不用手动加：max_age 默认 None，Flask 据此设
        # no-cache，与 nginx 原先 add_header 的效果一致。
        return send_from_directory(PAGES_DIR, f"{name}.html")

    return view


# 循环注册而非写 12 个视图函数：它们的函数体完全相同，逐个写只是把同一个
# 字符串抄 12 遍。endpoint 必须显式命名——不指定的话 Flask 会从函数名
# "view" 推导，12 条路由全叫 page.view 而当场冲突。
for _name in PROTECTED_PAGES:
    page_bp.add_url_rule(
        f"/{_name}.html",
        endpoint=f"page_{_name}",
        view_func=page_login_required(_serve(_name)),
    )
