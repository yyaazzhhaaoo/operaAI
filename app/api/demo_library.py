import os
import uuid

from flask import request

from app.api import api_bp
from app.common.decorators import login_required, teacher_required, current_user_id
from app.db import get_db
from app.response import ok, fail
from app.schemas.demo_library import DemoLibraryOut
from app.services import library_service, auth_service, audio_service

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@api_bp.route("/demo/library/upload",methods=["POST"])
@login_required
def demo_library_upload():
    try:
        if "audio" not in request.files:
            return fail(404,"获取文件失败")
        f = request.files["audio"]

        user = auth_service.get_user(get_db(), current_user_id())
        user_id = user.id
        if not user:
            return fail(500,"user not found")

        access = request.form.get("access")
        # commit=False：这一行先不提交，和下面 teacher_demos 那行合成一次事务，
        # 由 demo_library_add() 末尾统一 commit（提交点见 service 层的说明）。
        audio = audio_service.save_upload(get_db(),uploader_id=user_id,is_teacher=(user.role=='teacher'),access=access,file=f,commit=False)

        demo = library_service.demo_library_add(
            get_db(),
            # title 在库里是 NOT NULL，前端没填时退回文件名（不含扩展名）
            title=request.form.get("title") or os.path.splitext(f.filename)[0],
            role=request.form.get("role"),
            banshi=request.form.get("banshi"),
            audio_id=audio.id
        )

        # 前端要用 demo_id 去轮询解析进度（data.demo_id）
        return ok({"demo_id": demo.id})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return fail(500,str(e))

@api_bp.route("/demo/library/list",methods=["GET"])
@login_required
@teacher_required
def demo_library_list():
    items = library_service.demo_library_list(get_db())
    return ok([DemoLibraryOut.model_validate(item).model_dump()
               for item in items
               ])