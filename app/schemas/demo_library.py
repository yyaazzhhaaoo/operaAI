# -*- coding: utf-8 -*-
"""示范库接口的出参模型。

**role / banshi / elo_difficulty / created_at / duration 一律可空**，因为
teacher_demos 与 audio_files 里这几列在 DDL 上都可空（见 schema.sql）：
写成非空的话，库里只要有一行空值，列表接口就整片 500。上一版的
`role: str` / `banshi: str` 正是这个错。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DemoLibraryListOut(BaseModel):
    """列表行。status 由 parse_service 逐行算出（redis 或派生）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    role: str | None = None
    banshi: str | None = None
    duration: float | None = None
    elo_difficulty: float | None = None
    created_at: datetime | None = None
    status: str


class SegmentOut(BaseModel):
    """一个唱段。**没有起止时间**——segments 表没有 start/end 列（本次不加），

    位置信息只有 seq；前端显示「第 N 段 · 6.6s」。逐字歌词（lyrics_json）
    按第 20 条一律不写，所以这里也不暴露这个字段。
    """

    seq: int | None = None
    title: str | None = None
    duration: float | None = None


class DemoLibraryDetailOut(BaseModel):
    """详情。url 由 api 层的 url_for 生成，指向 B5。

    `elo_difficulty` 与列表模型同字段同语义——详情页的难度条要读它，所以这里也必须有；
    库里是默认值 1000 时前端按「取不到有效值」显示「待校准」，不在本层过滤。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    role: str | None = None
    banshi: str | None = None
    duration: float | None = None
    elo_difficulty: float | None = None
    created_at: datetime | None = None
    status: str
    segments: list[SegmentOut] = []
    url: str | None = None
