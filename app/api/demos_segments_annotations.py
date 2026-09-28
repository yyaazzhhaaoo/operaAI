from flask import request

from app.api import api_bp
from app.common.decorators import login_required, teacher_required
from app.db import get_db
from app.response import ok
from app.schemas.demo import DemoListOut, DemoSegmentOut
from app.services import library_service


@api_bp.route("/demos", methods=["GET"])
@login_required
def demos():
    """C1 曲目列表（陪练选曲 + 作业布置用）。

    权限只要求登录（文档 C1 的权限列写的也是「登录」）：本接口要服务学生端的
    「陪练选曲」，加 @teacher_required 会当场堵死学生端。注意这与
    /api/demo/library/list（教师专属）不是同一个场景。

    不过滤 segment_count = 0 的曲目，由调用方自己判断（spec 3.3）。
    """
    rows = library_service.demo_list(get_db())
    return ok([DemoListOut.model_validate(r).model_dump(mode="json") for r in rows])

@api_bp.route("/demos/<int:demo_id>/segments", methods=["GET"])
@login_required
def demos_segments(demo_id):
    """C2 分段列表。

    `<int:demo_id>` 与 /api/demo/library/<int:demo_id> 同理：非数字路径在**路由层**
    就 404，不进视图，畸形输入也就没有变成 500 的机会。

    权限只要求登录：学生端陪练要选唱段，加 @teacher_required 会堵死学生端。
    曲目不存在回 404；曲目存在但没有分段回 200 + []（spec 3.3）。
    """
    rows = library_service.demo_segments(get_db(), demo_id)
    return ok([DemoSegmentOut.model_validate(r).model_dump(mode="json") for r in rows])

@api_bp.route("/segments/<id>",methods=["GET"])
@login_required
def segments(id):
    return ok(id);

@api_bp.route("/segments/<id>/annotations",methods=["GET"])
@login_required
@teacher_required
def segments_annotations(id):
    return ok(id);

@api_bp.route("/annotations",methods=["POST"])
@login_required
@teacher_required
def annotations():
    return ok()

@api_bp.route("/annotations/<id>",methods=["DELETE"])
@login_required
@teacher_required
def del_annotations(id):
    return ok(id)

@api_bp.route("/annotations/rules",methods=["GET"])
@login_required
@teacher_required
def annotations_rules():
    tag = request.args.get("tag")
    word = request.args.get("word")
    return ok({"tag":tag,"word":word})