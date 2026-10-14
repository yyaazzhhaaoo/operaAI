# -*- coding: utf-8 -*-
"""统一的接口响应格式。

依据《5-接口清单-V1.0》：「统一返回 {"code":0, "message":"ok", "data":{...}}」。

文档只规定了成功形态，错误码未定义（见 DOC_ISSUES.md 第 9 条）。本项目约定：
  - code 沿用 HTTP 语义：400 参数错误 / 401 未登录 / 403 无权限 /
    404 不存在 / 500 服务器错误
  - HTTP 状态码与 code 保持一致（便于浏览器、网关、日志按状态码识别）

注意：app-d.py 目前只有根路由 / 用了这套格式。它的 /upload、/progress、/analyze
三个路由仍返回裸字段——因为 pitch_comparison.html 直接消费那些字段
（j.url、data.logs、data.score…），改了会当场打断音准对比演示。
"""

from flask import jsonify


def ok(data=None, message="ok"):
    """data 直接装数据本身，不在外面再包一层。"""
    return jsonify({"code": 0, "message": message, "data": data})


def fail(code, message):
    """code 沿用 HTTP 语义，HTTP 状态码与之一致。"""
    return jsonify({"code": code, "message": message, "data": None}), code
