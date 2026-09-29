from flask import request

from app.api import api_bp
from app.common.decorators import current_user_id, login_required, teacher_required
from app.db import get_db
from app.response import ok
from app.schemas.demo import (
    AnnotationIn,
    AnnotationOut,
    DemoListOut,
    DemoSegmentOut,
    SegmentDetailOut,
)
from app.services import library_service


def _payload() -> dict:
    """取 JSON 请求体。

    客户端没带 Content-Type: application/json 时 get_json() 会抛 415；
    silent=True 把它压成 None，这里再兜成 {}，让 pydantic 报「字段必填」
    而不是让 Flask 抛一个前端看不懂的 415。
    """
    return request.get_json(silent=True) or {}


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

@api_bp.route("/segments/<int:segment_id>", methods=["GET"])
@login_required
def segments(segment_id):
    """C3 段落详情，含逐字歌词。

    `<int:segment_id>` 同 C2：非数字路径在**路由层**就 404，不进视图。

    权限只要求登录（文档 C3 的权限列就是「登录」）：学生端陪练要看歌词，
    加 @teacher_required 会堵死学生端。注意 C4–C7 才是教师专属。

    唱段存在但还没歌词时回 200 + lyrics: []，不是 404——解析产出的新段落
    lyrics_json 就是 NULL（DOC_ISSUES 第 20 条），那是常态。
    """
    data = library_service.segment_detail(get_db(), segment_id)
    return ok(SegmentDetailOut.model_validate(data).model_dump(mode="json"))

@api_bp.route("/segments/<int:segment_id>/annotations", methods=["GET"])
@login_required
@teacher_required
def segments_annotations(segment_id):
    """C4 标注规则列表。

    `<int:segment_id>` 同 C2/C3：非数字路径在**路由层**就 404，不进视图。

    **权限是教师**（文档 C4 的权限列就是「教师」），与 C1/C2/C3 的「登录」不同：
    2.3 节这一组里 C4–C7 都是教师专属。装饰器叠放顺序固定，login_required 在外层。

    唱段不存在回 404，唱段存在但没标注回 200 + []——「还没标过」是正常状态
    （当前真库 annotations 表 0 行，在没有标注数据时这就是唯一会遇到的情况）。
    """
    rows = library_service.segment_annotations(get_db(), segment_id)
    return ok([AnnotationOut.model_validate(r).model_dump(mode="json") for r in rows])

@api_bp.route("/annotations", methods=["POST"])
@login_required
@teacher_required
def annotations():
    """C5 新增标注。返回新建的那一行。

    **权限是教师**（文档 C5 的权限列就是「教师」），与同组的 C4/C6/C7 一致。

    `teacher_id` **从会话取**，不进请求体：让客户端指定归属等于开一个
    「以别人的名义标注」的越权入口，而接口没有任何理由需要它。

    成功回 200 不是 201：ok() 固定 200，auth/login 等既有 POST 也全走 200，
    为一个接口单独引入 201 会让「code 与 HTTP 状态码一致」多一个例外。

    校验顺序：pydantic 在本层先跑，service 的 404 判定在后。所以
    「segment_id 不存在 **且** tag 非法」回的是 422 而不是 404——参数合法性
    优先于资源存在性。调用方若按「先 404 后 422」写分支会踩到。
    """
    data = AnnotationIn.model_validate(_payload())
    row = library_service.create_annotation(
        get_db(),
        segment_id=data.segment_id,
        word_index=data.word_index,
        tag=data.tag,
        tolerance=data.tolerance,
        teacher_id=current_user_id(),
    )
    return ok(AnnotationOut.model_validate(row).model_dump(mode="json"))

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