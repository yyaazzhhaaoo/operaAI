# -*- coding: utf-8 -*-
"""B 组音频/分析接口（《5-接口清单-V1.0》）。

    B1  POST /api/audio/upload          登录  上传音频，落盘并写 audio_files
    B2  POST /api/analyze/submit         登录  异步提交分析，立即返回 task_id
    B3  GET  /api/analyze/status/<id>    登录  轮询进度（契约见 3.1）
    B4  GET  /api/analyze/result/<id>    登录  取完整结果（契约见 3.2）
    B5  GET  /api/audio/<file_id>        登录  按 access 规则校验后 send_file

本层只做三件事：校验入参 → 调 service → 组装响应。不写 SQL、不写业务规则、
不写 try/except（错误由 app/common/errors.py 的全局 handler 兜）。
"""

from flask import request, send_file, session

from app.api import api_bp
from app.common.decorators import current_user_id, login_required
from app.common.errors import BusinessError
from app.db import get_db
from app.response import ok
from app.schemas.audio import AnalyzeSubmitIn
from app.services import analyze_service, audio_service


def _payload() -> dict:
    """取 JSON 请求体。

    客户端没带 Content-Type: application/json 时 get_json() 会抛 415；
    silent=True 把它压成 None，这里再兜成 {}，让 pydantic 报「字段必填」
    而不是让 Flask 抛一个前端看不懂的 415。
    """
    return request.get_json(silent=True) or {}


@api_bp.route("/audio/upload", methods=["POST"])
@login_required
def audio_upload():
    """B1 上传音频。multipart：字段名 audio 为文件，可选 access（默认 private）。"""
    file = request.files.get("audio")
    if file is None or not file.filename:
        raise BusinessError(400, "缺少音频文件（multipart 字段名应为 audio）")

    audio = audio_service.save_upload(
        get_db(),
        uploader_id=current_user_id(),
        # 会话里的 role 由 A1 登录时写入。这里只把「是不是教师」传下去，
        # 具体能不能设 public 由 service 判——api 层不做业务规则。
        is_teacher=session.get("role") == "teacher",
        access=request.form.get("access", "private"),
        file=file,
    )
    return ok({"file_id": audio.id})


@api_bp.route("/analyze/submit", methods=["POST"])
@login_required
def analyze_submit():
    """B2 异步提交分析，立即返回 task_id（3.1 模式一 / 模式二）。"""
    data = AnalyzeSubmitIn.model_validate(_payload())
    task_id = analyze_service.submit(get_db(), data)
    return ok({"task_id": task_id})


@api_bp.route("/analyze/status/<task_id>", methods=["GET"])
@login_required
def analyze_status(task_id):
    """B3 轮询进度（3.1 第 2 步）。"""
    return ok(analyze_service.status(task_id))


@api_bp.route("/analyze/result/<task_id>", methods=["GET"])
@login_required
def analyze_result(task_id):
    """B4 取完整结果（3.2）。仅在 status=done 后调用。"""
    return ok(analyze_service.result(task_id))


@api_bp.route("/audio/<int:file_id>", methods=["GET"])
@login_required
def audio_download(file_id):
    """B5 按 access 规则取音频（《5-接口清单》B5 /《6》第 4 节第 2 条）。

    权限判定在 service 层（audio_service.get_playable）。这里回的是二进制流
    而不是 {"code","message","data"}——文档 B5 要的就是 send_file，文件下载
    没法套 JSON 信封；失败时仍抛 BusinessError，由全局 handler 转成统一信封。
    """
    path, audio = audio_service.get_playable(
        get_db(),
        file_id=file_id,
        user_id=current_user_id(),
        # 与 B1 同样的取法：会话里的 role 由 A1 登录时写入
        is_teacher=session.get("role") == "teacher",
    )
    # download_name 用原始文件名而非 uuid 存储名；中文名会被 Werkzeug 编码成
    # RFC 5987 的 filename*=，实测无问题。conditional 默认 True，Range 由此支持，
    # 音频拖动进度条要靠它，不用显式传。
    #
    # max_age=0 必须显式给：不传时 Flask 会去取 SEND_FILE_MAX_AGE_DEFAULT
    # （app.get_send_file_max_age）。实测把这个配置设成 3600，本接口的响应头就会
    # 变成 Cache-Control: public, max-age=3600——学生录音被标成公共可缓存。
    # 现在没出事只是因为没人设过那个配置，不能指望它一直没人设。
    # 另外 no-cache 只要求回源校验，并不禁止共享缓存落盘，所以再补一个 private。
    resp = send_file(path, download_name=audio.original_name, max_age=0)
    resp.cache_control.private = True
    return resp


# 关于 B5 的路径选择：用 `<int:file_id>` 而不是文档字面的 `<file_id>`。转换器名
# 不进 URL，形状不变；但非数字路径（如 /api/audio/abc）会在**路由层**就以 404
# 拒掉、不进视图，不必在视图里自己 int() 解析，畸形输入也就没有变成 500 的机会。
#
# 更要紧的是它让 B5 与演示取音频路由彻底解耦，而不是「碰巧不撞」。演示路由现在是
# 两段的 `/audio/demo/<path:filename>`，与单段本来就不重叠；但即便有人把 app-d.py
# 回退成早先的单段形态 `/audio/<path:filename>`，`<int:file_id>` 也只吃数字，
# 演示页的 `/api/audio/xxx.wav` 仍归 demo_bp。实测对照，在演示路由为单段的前提下：
#   `<file_id>`     → /api/audio/123、/x.wav、/abc、/14.wav 全部被 B5 抢走（演示页音频加载当场失效）
#   `<int:file_id>` → 只有 /api/audio/123 归 B5，其余三条照旧落到 demo_bp
#
# 仍未了结的是 pitch_comparison.html 的去留：它走 demo_bp 落盘、不写 audio_files
# 表，B5 查不到它的文件，且它的结果契约与 B4 的 3.2 契约不同，无法平滑切换。
# 详见 DOC_ISSUES.md 第 11 条。
