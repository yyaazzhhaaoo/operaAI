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
