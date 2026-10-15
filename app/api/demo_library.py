# -*- coding: utf-8 -*-
"""示范库接口（`DOC_ISSUES.md` 第 16–20 条 / spec `2026-09-21-demo-library-parse-design.md`）。

    POST /api/demo/library/upload                     登录  上传示范音频（可附带逐字数据 Excel）
    GET  /api/demo/library/list                       登录+教师  示范曲目列表（带解析状态）
    GET  /api/demo/library/<int:demo_id>              登录  详情（含分段列表与音频 url）
    GET  /api/demo/library/<int:demo_id>/parse/status 登录  解析进度（前端每 3 秒轮询）

本层只做三件事：校验入参 → 调 service → 组装响应。不写 SQL、不写业务规则、
不写 try/except（错误由 app/common/errors.py 的全局 handler 兜）。
"""

from pathlib import Path

from flask import request, session, url_for

from app.api import api_bp
from app.common.decorators import current_user_id, login_required, teacher_required
from app.common.errors import BusinessError
from app.db import get_db
from app.response import ok
from app.schemas.demo_library import DemoLibraryDetailOut, DemoLibraryListOut
from app.services import audio_service, library_service, lyrics_excel, parse_service


@api_bp.route("/demo/library/upload", methods=["POST"])
@login_required
def demo_library_upload():
    """上传示范音频：落盘 + 建两行，返回 {demo_id, task_id}。

    带 `excel` 字段时按逐字数据建段、**不投 Demucs 任务**（task_id 为 null）；
    不带时原路不变，投 demucs 队列由 worker 切分（spec 3.1）。

    鉴权只要求登录（本轮「权限先不管」的决策，见 spec 第 2 节）。`access`
    仍按角色取值——`audio_service.save_upload` 只允许教师设 public。
    """
    file = request.files.get("audio")
    if file is None or not file.filename:
        raise BusinessError(400, "缺少音频文件（multipart 字段名应为 audio）")

    # 解析排在落盘之前：逐字数据有问题就整批回滚，连音频文件都不落盘（spec 3.4）
    excel = request.files.get("excel")
    segments = None
    if excel is not None and excel.filename:
        segments = lyrics_excel.parse_segments(excel.read())

    db = get_db()
    # commit=False：这一行先不提交，和下面 teacher_demos 那行合成一次事务，
    # 由 service 层末尾统一 commit（提交点见 service 层的说明）。
    audio = audio_service.save_upload(
        db,
        uploader_id=current_user_id(),
        is_teacher=session.get("role") == "teacher",
        access=request.form.get("access", "private"),
        # 示范音频落 uploads/demos/，与学生录音（uploads/ 根）分开。
        # 显式给而不用 access 推导，理由见 audio_service.save_upload 的 docstring。
        subdir="demos",
        file=file,
        commit=False,
    )

    # title 在库里是 NOT NULL，前端没填时退回文件名（不含扩展名）
    title = request.form.get("title") or Path(file.filename).stem
    if segments is None:
        demo = library_service.demo_library_add(
            db,
            title=title,
            role=request.form.get("role"),
            banshi=request.form.get("banshi"),
            audio_id=audio.id,
        )
        # 提交之后才投任务：submit() 需要 demo.id，而 redis 那条记录要在「两行都
        # 落定」之后才存在，否则任务可能先跑起来、查库时 demo 还没提交。
        return ok({"demo_id": demo.id, "task_id": parse_service.submit(db, demo)})

    demo = library_service.demo_library_add_with_segments(
        db,
        title=title,
        role=request.form.get("role"),
        banshi=request.form.get("banshi"),
        audio=audio,
        segments=segments,
    )
    # 状态不写 redis：详情/状态接口走 parse_service.status 的派生路径
    # （segments 有行 → parsed），前端即便轮询也是第一次就拿到 parsed（spec 3.1）。
    return ok({"demo_id": demo.id, "task_id": None})


@api_bp.route("/demo/library/list", methods=["GET"])
@login_required
@teacher_required
def demo_library_list():
    """示范曲目列表。

    `@teacher_required` 是工作区里**已有**的校验，口径是「不新增限制，也不移除
    已有校验」，所以保留（spec 4.5）。
    """
    rows = library_service.demo_library_list(get_db())
    return ok([DemoLibraryListOut.model_validate(r).model_dump(mode="json") for r in rows])


@api_bp.route("/demo/library/<int:demo_id>", methods=["GET"])
@login_required
def demo_library_get(demo_id):
    """示范曲目详情。含分段列表与可播放 url。

    `<int:demo_id>` 的转换器与 B5 同理：非数字路径在**路由层**就 404，
    不进视图，畸形输入也就没有变成 500 的机会。
    """
    db = get_db()
    demo, segments = library_service.demo_library_get(db, demo_id)
    return ok(DemoLibraryDetailOut.model_validate({
        "id": demo.id,
        "title": demo.title,
        "role": demo.role,
        "banshi": demo.banshi,
        "duration": demo.audio.duration_sec if demo.audio else None,
        # 手工拼的 dict 必须逐个键写全：`from_attributes=True` 只让 pydantic 能从
        # **对象属性**取值，对 dict 输入不生效——不在 dict 里的键一律落声明的默认值
        # None，不会去 ORM 对象上找。漏掉这行的话详情接口的 elo_difficulty 恒为
        # null，而列表接口（走 service 的行 dict）给的是真值，同一首曲子在两个接口
        # 上会显示成两种难度。
        "elo_difficulty": demo.elo_difficulty,
        "created_at": demo.created_at,
        "status": parse_service.status(db, demo_id)["status"],
        "segments": [
            {"seq": s.seq, "title": s.title, "duration": s.duration} for s in segments
        ],
        # 同 B1：url 由 url_for 生成，前端不必硬编码 /api/audio/<id>——硬编码
        # 路径与后端漂移正是 DOC_ISSUES 第 1 条记的那类问题。
        # **不返回 audio_files.file_path**：那是服务端存储名，common/storage.py
        # 承诺不把服务器目录结构泄漏到接口响应里。
        "url": url_for("api.audio_download", file_id=demo.audio_id) if demo.audio_id else None,
    }).model_dump(mode="json"))


@api_bp.route("/demo/library/<int:demo_id>/parse/status", methods=["GET"])
@login_required
def demo_library_parse_status(demo_id):
    """解析进度。前端 startPolling 每 3 秒调一次，拿到 parsed/error 才停表。

    状态从哪来（redis 还是按 segments 派生）由 service 决定，见
    `parse_service.status` 的 docstring。
    """
    return ok(parse_service.status(get_db(), demo_id))
