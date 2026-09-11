# -*- coding: utf-8 -*-
"""统一错误出口。

api 层与 services 层都不写 try/except——业务错误抛 BusinessError、
参数错误由 pydantic 抛 ValidationError，加上 HTTP 异常与未捕获异常，
四类一起汇到本文件注册的 handler，最终都变成
{"code","message","data"} 形态的 JSON。

code 沿用 HTTP 语义、与 HTTP 状态码一致（见 DOC_ISSUES.md 第 9 条）。
"""

from flask import jsonify
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

from app.response import fail


class BusinessError(Exception):
    """业务规则不满足。由 service 层抛出，handler 转成 fail(code, message)。

    例：raise BusinessError(401, "用户名或密码错误")
    """

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# pydantic v2 的默认报错是英文（实测 'Field required'、
# 'String should have at least 8 characters'），本项目是中文 UI，
# 直接透给前端不可接受。已知的 type 在这里映射成中文，参数从 err["ctx"] 取。
_MSG_CN = {
    "missing": lambda c: "必填",
    "string_too_short": lambda c: f"长度不能少于 {c['min_length']} 个字符",
    "string_too_long": lambda c: f"长度不能超过 {c['max_length']} 个字符",
    "int_parsing": lambda c: "必须是整数",
}

# HTTP 异常的默认 description 是 Werkzeug 的英文长句
# （"The requested URL was not found on the server..."），前端直接展示很突兀。
# 常见状态码映射成中文；表里没有的仍回退 description，不吞信息。
_HTTP_MSG_CN = {
    400: "请求参数错误",
    401: "未登录",
    403: "无权限",
    404: "接口不存在",
    405: "请求方法不允许",
    413: "上传内容过大",
    415: "不支持的 Content-Type",
    422: "参数错误",
    500: "服务器内部错误",
}


def _format_validation_error(exc: ValidationError) -> str:
    """把 pydantic 的报错压成一句话，供前端直接展示。

    三层处理：① 已知 type 走中文映射；② 自定义 validator 抛的 ValueError
    本身就是中文，只需去掉 pydantic 加的 "Value error, " 前缀；
    ③ 其余回退英文原文——宁可给英文，也不要用「参数错误」四个字把信息吞掉。
    """
    parts = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err["loc"]) or "body"
        if fmt := _MSG_CN.get(err["type"]):
            msg = fmt(err.get("ctx") or {})
        else:
            msg = err["msg"].removeprefix("Value error, ")
        parts.append(f"{loc}: {msg}")
    return "; ".join(parts)


def register_error_handlers(app):
    """在 Flask 应用上注册四个错误 handler。

    Flask 按异常类型的精确度选 handler，注册顺序无关紧要：
    BusinessError / ValidationError 比 Exception 更具体，会先命中。
    DEBUG=True 时同样生效——Flask 的 handle_user_exception 先查已注册的
    handler，查到就直接调用，走不到 PROPAGATE_EXCEPTIONS 那条分支（3.1.3 实测）。
    """

    @app.errorhandler(BusinessError)
    def _business_error(e: BusinessError):
        return fail(e.code, e.message)

    @app.errorhandler(ValidationError)
    def _validation_error(e: ValidationError):
        return fail(422, _format_validation_error(e))

    @app.errorhandler(HTTPException)
    def _http_exception(e: HTTPException):
        # 这条必须有：未匹配的 URL 默认返回 Werkzeug 的 HTML 404 页，
        # 前端 JSON.parse 会当场炸，也不符合《5-接口清单》的统一返回。
        code = e.code or 500
        return fail(code, _HTTP_MSG_CN.get(code) or e.description or "请求错误")

    @app.errorhandler(Exception)
    def _unexpected(e: Exception):
        # 堆栈只进日志，响应不回内部细节，避免泄漏文件路径、连接串等。
        app.logger.exception("未捕获异常: %s", e)
        return fail(500, "服务器内部错误")
