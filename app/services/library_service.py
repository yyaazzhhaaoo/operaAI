# -*- coding: utf-8 -*-
"""示范库（teacher_demos / segments）的业务逻辑。

事务边界在本层：写操作显式 commit。
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.errors import BusinessError
from app.models import TeacherDemo
from app.models.demo import Segment
from app.repositories import annotations_repo, library_repo
from app.services import parse_service


def demo_list(db: Session) -> list[dict]:
    """C1 曲目列表（陪练选曲 + 作业布置用）。

    duration 取自 audio_files.duration_sec（经 demo.audio 惰性加载）——
    teacher_demos 自己没有时长列。曲目无音频、或音频未回填时长时为 None。

    elo_difficulty 如实返回，**不做 0–1 兜底**：库里有未标定的列默认值 1000，
    那是「数据没标定」不是「取不到值」，后端悄悄改成 None 或夹到 1.0 会让调用方
    分不清两者（spec 3.2、DOC_ISSUES 第 19 条）。判定留给前端。

    不过滤 segment_count = 0 的曲目（spec 3.3）：标注页要置灰展示「还没解析」、
    陪练选曲要直接跳过，两个场景诉求不同，接口保持中立。

    返回 dict 而不是 ORM 对象：已经把分段数与 audio 摊平进来了，再让 api 层去
    ORM 上拼一遍等于把同一件事写两处（与 demo_library_list 同风格）。
    """
    return [
        {
            "id": demo.id,
            "title": demo.title,
            "role": demo.role,
            "banshi": demo.banshi,
            "duration": demo.audio.duration_sec if demo.audio else None,
            "elo_difficulty": demo.elo_difficulty,
            "segment_count": segment_count,
        }
        for demo, segment_count in library_repo.get_demo_list(db)
    ]


def demo_library_list(db: Session) -> list[dict]:
    """列表用的行：把 audio_files.duration_sec 与解析状态摊平进来。

    status 逐行查一次 redis（parse_service.status 的派生路径还要查一次库）。
    示范曲目是「剧目级」的量（演示数据 4 条，真实使用量级是几十），不值得为它
    做批量 pipeline 或 join；真到几百条再优化，这条注释留在这里当锚点。

    返回 dict 而不是 ORM 对象：这里已经要摊平两个来源（audio 关系 + redis），
    再让 api 层去 ORM 上拼一遍等于把同一件事写两处。
    """
    rows = []
    for demo in library_repo.get_library_list(db) or []:
        rows.append({
            "id": demo.id,
            "title": demo.title,
            "role": demo.role,
            "banshi": demo.banshi,
            "duration": demo.audio.duration_sec if demo.audio else None,
            "elo_difficulty": demo.elo_difficulty,
            "created_at": demo.created_at,
            "status": parse_service.status(db, demo.id)["status"],
        })
    return rows


def demo_library_get(db: Session, demo_id: int) -> tuple[TeacherDemo, list[Segment]]:
    """取一条示范曲目及其分段。不存在抛 404。

    同时返回 demo 与 segments（而不是让调用方再查一次分段）：详情接口两个都要，
    分两次查会在「demo 存在但分段刚好被重跑清空」的瞬间读到不一致的组合。
    """
    demo = library_repo.get_demo(db, demo_id)
    if demo is None:
        raise BusinessError(404, "示范曲目不存在")
    return demo, library_repo.list_segments(db, demo_id)


def demo_library_add(
    db: Session,
    *,
    title: str,
    role: str | None = None,
    banshi: str | None = None,
    audio_id: int | None = None,
) -> TeacherDemo:
    """新增示范曲目。事务边界在本层，写操作显式 commit。

    audio_id 由调用方传入（audio_files flush 出来的自增主键），本层只负责把
    外键写进去，不反查、不补建。

    下面这次 commit 同时提交前一步 save_upload(commit=False) 留在同一会话里的
    audio_files 行——示范曲目上传要的就是「两行一次提交」：任何一边失败，
    两边都留不下半条记录。

    **解析任务的投递不在这里做**：submit() 需要 demo.id，而这条 commit 之后
    才轮到 api 层调 parse_service.submit()。若 redis 挂了导致 submit 失败，
    上传接口会回 500，但 teacher_demos 那行已经落库、segments 为空——此时
    详情页的派生状态恰好是 unparsed（「没解析过」），是一句实话，用户可以
    重新上传。这个顺序是刻意选的：先落库、后投任务。
    """
    demo = TeacherDemo(
        title=title,
        # 表单下拉框未选时提交的是空串，落库统一成 NULL：
        # 空串会让「按行当筛选」之类的查询多出一个无意义的取值。
        role=role or None,
        banshi=banshi or None,
        audio_id=audio_id,
    )
    library_repo.add_library(db, demo)
    db.commit()
    return demo


def demo_segments(db: Session, demo_id: int) -> list[Segment]:
    """某曲目的分段列表（按 seq 升序）。曲目不存在抛 404。供 C2。

    不复用同一文件里的 demo_library_get：它一次返回 (demo, segments)，其 docstring
    解释了为什么要一起取（避免「demo 存在但分段刚好被重跑清空」的不一致组合）——
    C2 只要分段，那个理由不成立；而且它的 404 文案是「示范曲目不存在」，会把示范库
    管理的措辞泄漏给陪练/标注场景（同 C1 不返回 status 的理由，spec 4.1）。

    「曲目存在但没有分段」返回空列表、不抛 404：那是正常状态，不是错误（spec 3.3）。
    库里 demo 15/19 就是这个状态。
    """
    if library_repo.get_demo(db, demo_id) is None:
        raise BusinessError(404, "曲目不存在")
    return library_repo.list_segments(db, demo_id)


def _num(v) -> float | None:
    """JSONB 列没有类型约束，只放行真正的数值，其余一律 None。

    挡住字符串 "64"、True 这类：前端拿 pitch 去算 midiToNote()，非数值会渲染成
    「NaN undefined」，不如按「没有值」处理（spec 3.2）。

    bool 要单独排除——Python 里 isinstance(True, int) 是 True。
    """
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v


def _normalize_lyrics(raw: list | None) -> list[dict]:
    """把 lyrics_json 的库内形状映射成 C3 出参的逐字形状（spec 3.2）。

    | 库          | 出参       | 规则                                        |
    | word        | char       | 缺失/非字符串 → **整条丢弃**（构造不出字）       |
    | midi        | pitch      | 缺失/非数值 → None（前端靠 pitch === null 判标点）|
    | start       | start      | 缺失/非数值 → None                            |
    | end - start | duration   | 任一缺失 → None；标点是 end == start → 0.0     |
    | note        | note       | **原样传 NOTE_***，不做分数串映射（那是前端显示词）|
    | tip         | tip        | 缺失 → None                                  |

    raw 为 None（解析产出的新段落就是这样，见 DOC_ISSUES 第 20 条）→ 返回 []，
    不是 None：前端统一按数组处理，少一个分支。这是**常态不是边角**。

    条目不是对象就跳过，不让一个脏条目把整个接口打成 500。
    """
    out = []
    for e in raw or []:
        if not isinstance(e, dict):
            continue
        word = e.get("word")
        if not isinstance(word, str):
            continue
        start = _num(e.get("start"))
        end = _num(e.get("end"))
        out.append({
            "char": word,
            "pitch": _num(e.get("midi")),
            "start": start,
            "duration": (end - start) if (start is not None and end is not None) else None,
            "note": e.get("note"),
            "tip": e.get("tip"),
        })
    return out


def _lyric_at(seg, index: int) -> dict | None:
    """取某个唱段第 index 个字的**归一化**歌词，取不到回 None。供 C7 算 char。

    必须复用 _normalize_lyrics，**不许**直接 seg.lyrics_json[index]：归一函数会
    **丢弃**非法条目（非对象、word 非字符串），直接下标取会拿到错位的字。
    C3 出参、C5 写入校验、C7 的 char 三处必须同源，否则会出现
    「C5 说这个下标合法、C7 却取到别的字」。

    取不到有两种来源，都回 None（调用方据此把 char 置空，**行仍保留**）：
    seg 为 None（标注的 segment_id 为空）、index 越界（歌词在该标注写入后
    被重新解析过——replace_segments 会整批替换）。

    判 0 <= index 而不是只判上界：word_index 在 DDL 上只有 NOT NULL，
    负数下标会从列表尾部取字（Python 语义），那是静默取错值。
    """
    if seg is None:
        return None
    lyrics = _normalize_lyrics(seg.lyrics_json)
    if 0 <= index < len(lyrics):
        return lyrics[index]
    return None


def segment_detail(db: Session, segment_id: int) -> dict:
    """C3 段落详情。含归一后的逐字歌词。

    曲目列表（C1）与分段列表（C2）都不碰 lyrics_json，这里是唯一入口——
    也正是因此，映射逻辑写在这一个地方就够了，不必给每个调用方各写一遍。

    不返回 demo_id（调用方从 C2 过来，本来就知道，同 C2 不返回它的理由），
    不返回原始 lyrics_json 字符串（那是 JSONB 列的内部表示）。
    """
    seg = library_repo.get_segment(db, segment_id)
    if seg is None:
        raise BusinessError(404, "唱段不存在")
    return {
        "id": seg.id,
        "seq": seg.seq,
        "title": seg.title,
        "duration": seg.duration,
        "lyrics": _normalize_lyrics(seg.lyrics_json),
    }


def segment_annotations(db: Session, segment_id: int) -> list[dict]:
    """C4 标注列表。该唱段的全部标注，按 word_index 升序。

    **不按教师隔离**（spec 3.4）：annotations 的 UNIQUE 约束是
    (segment_id, word_index, tag)，**不含 teacher_id**——同一唱段的同一个字、
    同一个 tag 只能存一条，换个教师再标会撞唯一约束。这张表的设计前提就是
    「一个唱段一套全局唯一的规则集」，不是每教师一份。teacher_id 仍照常写入
    （C5 的事），只是不参与过滤。

    唱段不存在抛 404：**必须显式查 segments**，不能拿标注查询的结果反推——
    唱段不存在时查标注同样是空数组，不查 segments 就会把「唱段不存在」错答成
    200 + []，与 C3 的口径打架。

    唱段存在但没有标注回 []，不是 404（同 C2/C3 的「存在但为空」口径）。
    这是当前真库的唯一情况：annotations 表 0 行。

    返回 dict 而不是 ORM 对象：同 demo_list / demo_library_list 的风格，
    api 层直接喂给 pydantic。
    """
    if library_repo.get_segment(db, segment_id) is None:
        raise BusinessError(404, "唱段不存在")
    return [
        {
            "id": a.id,
            "word_index": a.word_index,
            "tag": a.tag,
            "tolerance": a.tolerance,
            "created_at": a.created_at,
        }
        for a in annotations_repo.list_by_segment(db, segment_id)
    ]


def create_annotation(db: Session, *, segment_id: int, word_index: int, tag: str,
                      tolerance: int | None, teacher_id: int | None) -> dict:
    """C5 新增标注。返回新建的行，形状与 C4 列表行相同。

    关键字参数：两个 int 加一个可空 int，位置调用时极易写反。

    判定顺序 —— **segment 存在性 → 下标范围 → 重复**：

    - 唱段不存在抛 404（同 C3/C4，必须显式查 segments）
    - 下标越界抛 422。上界按 **C3 归一后**的歌词长度算，与 C3 出参、前端歌词
      网格**同一个函数**——三者必须同源，否则会出现「接口说越界、页面上却
      有这个字」。C4 spec 5.5 对出参采取「越界保留、首列显示 ?」是为了让**已有
      的**脏数据可见；这里挡住是为了**不再生产**脏数据，两者不冲突
    - 同字同 tag 已存在抛 409（`UNIQUE(segment_id, word_index, tag)`）

    tag 的取值域与 tolerance 的 0–100 在 `AnnotationIn` 已经挡下，本层不重复判。

    返回 dict 而不是 ORM 对象：同 segment_annotations / demo_list 的风格，
    api 层直接喂给 pydantic。**字典在 commit 之前就组装好**——commit 会让
    ORM 实例的属性过期，之后再读会多发一次 SELECT。
    """
    seg = library_repo.get_segment(db, segment_id)
    if seg is None:
        raise BusinessError(404, "唱段不存在")

    n = len(_normalize_lyrics(seg.lyrics_json))
    if word_index >= n:
        # BusinessError 的消息不会被加字段名前缀（那是 pydantic 的 loc 拼的），
        # 所以这里要把上下文写全，前端 toast 直接展示这一句
        raise BusinessError(422, f"该唱段共 {n} 个字，word_index 必须在 0 到 {n - 1} 之间")

    if annotations_repo.get_one(db, segment_id, word_index, tag) is not None:
        raise BusinessError(409, "该字已标注此技法")

    try:
        ann = annotations_repo.add(
            db, segment_id=segment_id, word_index=word_index, tag=tag,
            tolerance=tolerance, teacher_id=teacher_id,
        )
    except IntegrityError:
        # 这里只会是唯一约束冲突：其余约束都已被前面的判定与 AnnotationIn 挡下
        # （segment_id 的外键由 404 判定、teacher_id 来自有效会话、tolerance 的
        # CHECK 由入参模型保证、word_index / tag 的 NOT NULL 由必填保证）。
        # **将来给 annotations 加新约束时，要回头重看这个假设。**
        # rollback 是必需的：flush 失败后会话处于不可用状态，不回滚就不能再
        # 执行任何语句（get_db() 只在 teardown 时 close()，不替这里回滚）。
        db.rollback()
        raise BusinessError(409, "该字已标注此技法") from None

    row = {
        "id": ann.id,
        "word_index": ann.word_index,
        "tag": ann.tag,
        "tolerance": ann.tolerance,
        "created_at": ann.created_at,
    }
    db.commit()
    return row


def delete_annotation(db: Session, annotation_id: int) -> None:
    """C6 删除标注。不存在抛 404。成功无返回值。

    只有一条判定——路径参数已由 `<int:annotation_id>` 保证是非负整数，
    没有请求体也就没有入参校验，重复删除在第一步就撞 404。所以这里没有
    create_annotation 那样的 404/422/409 三级。

    **不判归属**：任何教师可删任何人的标注（spec 3.3）。C4 的前提是
    「一个唱段一套全局唯一的规则集」，规则的所有者是唱段而不是标它的
    那位教师；且 C4 出参不返回 teacher_id，判归属只会让用户遇到
    「删不掉又不知道为什么」。若文档方要求按人隔离，改动点在这里。

    返回 None 而不是 dict：删除没有「新状态」可返回。本文件其他 service
    函数都返回 dict/ORM，是因为它们的出参有内容，这里没有。
    """
    ann = annotations_repo.get_by_id(db, annotation_id)
    if ann is None:
        raise BusinessError(404, "标注不存在")
    annotations_repo.remove(db, ann)
    db.commit()


def annotation_rules(db: Session, *, tag: str | None, word: str | None) -> list[dict]:
    """C7 全库标注规则列表，可按 tag 与 word 筛选。

    tag / word 为 None 表示不筛（api 层已把缺省与空串一起收敛成 None）。

    **tag 在 SQL 筛、word 在这里筛**：word 筛的是**字**，而字不存在于
    annotations 表里，得先经 _normalize_lyrics 归一 lyrics_json 才算得出来，
    SQL 层拿不到。这个不对称是本质的，不是随手分的。

    **char 取不到时回 None，行保留**（spec 3.4）：集中展示的价值就在于
    「全库有多少条规则」这个数字是对的，悄悄少几行等于谎报。同 C4 spec 5.5
    「越界保留、让脏数据可见」的口径。

    **不抛 BusinessError**：本接口没有路径参数、不读 body，没有 404 场景；
    tag 也不校验词表——筛一个词表外的值是合法查询，空结果是正确回答
    （词表只为写入端把关，见 C5）。

    关键字参数：两个都可空且都是 str，位置调用时极易把 tag 与 word 写反。

    返回 dict 而不是 ORM 对象：同 segment_annotations / demo_list 的风格，
    api 层直接喂 pydantic。

    不按 segment 缓存归一结果：同一唱段的多条标注会重复归一同一份
    lyrics_json，但量级是「一个唱段几条标注、歌词十几字」，重复归一的代价
    远小于多一张缓存表的复杂度。
    """
    rows = []
    for ann, seg, demo in annotations_repo.list_rules(db, tag):
        lyric = _lyric_at(seg, ann.word_index)
        char = lyric["char"] if lyric else None
        if word is not None and char != word:
            continue
        rows.append({
            "id": ann.id,
            "word_index": ann.word_index,
            "char": char,
            "tag": ann.tag,
            "tolerance": ann.tolerance,
            "created_at": ann.created_at,
            "segment_id": ann.segment_id,
            "segment_title": seg.title if seg else None,
            "demo_id": seg.demo_id if seg else None,
            "demo_title": demo.title if demo else None,
        })
    return rows
