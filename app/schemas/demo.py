# -*- coding: utf-8 -*-
"""曲目/分段列表接口（C1 `GET /api/demos`、C2 `GET /api/demos/<id>/segments`）的出参模型。

**role / banshi / duration / elo_difficulty 一律可空**：teacher_demos 与
audio_files 里这几列在 DDL 上都可空（见 schema.sql）。写成非空的话，库里只要
有一行空值，整个列表就 500——与 app/schemas/demo_library.py 同一个坑。

与 DemoLibraryListOut 的差别只有两点：不含 status（那是解析进度，属于示范库
管理场景，泄漏给陪练/作业只会让它们平白依赖 redis），多一个 segment_count
（调用方要据此判断「这条能不能用」）。
"""

from pydantic import BaseModel, ConfigDict


class DemoListOut(BaseModel):
    """曲目列表行。segment_count 无分段时是 0，不是 None。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    role: str | None = None
    banshi: str | None = None
    duration: float | None = None
    elo_difficulty: float | None = None
    segment_count: int


class DemoSegmentOut(BaseModel):
    """分段列表行（C2 `GET /api/demos/<id>/segments`）。

    **seq / title / duration 一律可空**：segments 表这三列在 DDL 上均可空
    （见 schema.sql），写成非空的话库里只要有一行空值，整个列表就 500。

    `id` 必须有——前端拿它去调 C3 `/segments/<id>` 与 C4 标注，不给 id 这个接口
    就没有下游（spec 3.1）。**不返回 lyrics_json**：文档把逐字数据划给 C3，
    而且库里那列目前有三种互不兼容的形状（DOC_ISSUES 第 27 条），未统一前
    返回什么都是错的。也不返回 demo_id——它是入参，调用方本来就知道。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    seq: int | None = None
    title: str | None = None
    duration: float | None = None
