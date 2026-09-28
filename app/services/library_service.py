# -*- coding: utf-8 -*-
"""示范库（teacher_demos / segments）的业务逻辑。

事务边界在本层：写操作显式 commit。
"""

from sqlalchemy.orm import Session

from app.common.errors import BusinessError
from app.models import TeacherDemo
from app.models.demo import Segment
from app.repositories import library_repo
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
