from flask import request

from app.api import api_bp
from app.common.decorators import current_user_id, login_required, teacher_required
from app.db import get_db
from app.response import ok
from app.schemas.demo import (
    AnnotationIn,
    AnnotationOut,
    AnnotationRuleOut,
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

@api_bp.route("/annotations/<int:annotation_id>", methods=["DELETE"])
@login_required
@teacher_required
def del_annotations(annotation_id):
    """C6 删除标注。

    路径参数用 `<int:annotation_id>`：非整数与负数在**路由层**就 404，不进
    视图（同 C2/C3/C4 的 `<int:...>`）。所以本层与 service 层都不必判负数
    或非数字——那是永不可达的死分支。已实测：`/api/segments/abc/annotations`
    与 `/api/segments/-1/annotations` 都回 404（Werkzeug 的 IntegerConverter
    正则是 `\\d+`，不收负号）。

    参数名不叫 `id`：`id` 遮蔽内置函数，且读代码时分不清是「标注的 id」
    还是别的什么。

    **权限是教师**（文档 C6 的权限列就是「教师」），与同组 C4/C5/C7 一致。

    **不判归属**（spec 3.3）：任何教师可删任何人的标注，理由见 service 层。

    回 `ok(None)`，**不是 204**：本项目统一信封（《5-接口清单》），204 按
    定义无响应体，会打破它。也不回被删的行——行已经没了，而前端本来就知道
    自己删的是哪个 id（这点与 C5 不同：新建的 id 由数据库生成，前端不知道）。

    与 C7 `/annotations/rules` 不冲突，且不依赖注册顺序：`rules` 不是整数，
    永远匹配不上 `<int:annotation_id>`。反过来说，若这里保持字符串转换器，
    C7 能不能用就取决于两条路由谁先注册了。
    """
    library_service.delete_annotation(get_db(), annotation_id)
    return ok(None)

@api_bp.route("/annotations/rules", methods=["GET"])
@login_required
@teacher_required
def annotations_rules():
    """C7 规则列表管理（功能 9.6）。跨唱段的全库标注列表，可按 tag 与 word 筛。

    **权限是教师**（文档 C7 的权限列就是「教师」），与同组 C4/C5/C6 一致。

    契约未在文档中定义——文档只有「`GET /api/annotations/rules?tag=&word=` ｜
    教师 ｜ 规则列表管理（功能 9.6）」一行，响应体、两个参数的匹配语义、排序、
    分页一概没有。本轮口径见 `DOC_ISSUES.md` 第 32 条与本接口的 spec。

    `request.args.get(...) or None` 把**缺省与空串一起收敛成 None**
    （`?tag=` 与不带 tag 都是「不筛」）。不做 `strip()`：`?word=%20三` 这种
    畸形输入原样匹配、匹配不上回空列表，比替调用方猜意图更可预期。

    **tag 在 SQL 筛、word 在 service 的 Python 循环里筛**：word 筛的是字，
    而字不存在于 annotations 表里，得先归一 lyrics_json 才算得出来。
    这个不对称是本质的，理由见 service 层。

    **不校验 tag 取值**：筛一个词表外的值是**合法查询**，回 `200` + `[]`，
    不是 `422`。词表只为写入端把关（C5）——那是为了「不再生产脏数据」，
    读取端宽容同 C4 出参的不校验口径。

    **本接口没有 404，也没有 422**：没有路径参数、不读 body（`_payload()`
    不参与）、不校验入参取值。唯一的失败是权限（401/403）。

    与 C6 的 `/annotations/<int:annotation_id>` 不冲突，且不依赖注册顺序：
    `rules` 不是整数，永远匹配不上 IntegerConverter（正则 `\\d+`）。
    """
    tag = request.args.get("tag") or None
    word = request.args.get("word") or None
    rows = library_service.annotation_rules(get_db(), tag=tag, word=word)
    return ok([AnnotationRuleOut.model_validate(r).model_dump(mode="json") for r in rows])