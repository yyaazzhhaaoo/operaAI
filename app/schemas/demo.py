# -*- coding: utf-8 -*-
"""曲目列表接口（C1 `GET /api/demos`）的出参模型。

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
