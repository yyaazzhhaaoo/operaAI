# -*- coding: utf-8 -*-
"""曲目/分段列表接口（C1 `GET /api/demos`、C2 `GET /api/demos/<id>/segments`）的出参模型。

**role / banshi / duration / elo_difficulty 一律可空**：teacher_demos 与
audio_files 里这几列在 DDL 上都可空（见 schema.sql）。写成非空的话，库里只要
有一行空值，整个列表就 500——与 app/schemas/demo_library.py 同一个坑。

与 DemoLibraryListOut 的差别只有两点：不含 status（那是解析进度，属于示范库
管理场景，泄漏给陪练/作业只会让它们平白依赖 redis），多一个 segment_count
（调用方要据此判断「这条能不能用」）。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class LyricCharOut(BaseModel):
    """逐字歌词的一格（C3）。

    字段名对齐前端 annotation.html 的 LYRICS：库里的 word/midi/end 在这里换成
    char/pitch，end 与 start 合成 duration（spec 3.2）。

    **pitch 为 None 表示这是标点**——前端靠 `item.pitch === null` 加 .punct 类
    且不挂 onclick。所以映射时「库里的 midi 键缺失」必须补成显式 None，
    漏成 undefined 的话 undefined === null 为 false，标点会渲染成可点的坏格子。

    note 原样是 NOTE_* 词表（backend 不决定怎么显示，spec 3.4）。
    """

    model_config = ConfigDict(from_attributes=True)

    char: str
    pitch: float | None = None
    start: float | None = None
    duration: float | None = None
    note: str | None = None
    tip: str | None = None


class SegmentDetailOut(BaseModel):
    """段落详情（C3）。

    `duration` 是**唱段时长**，与 `lyrics[].duration`（单字时长）同名不同义，
    靠层级区分（spec 3.1）。

    `lyrics` 无歌词时是 []，不是 None：lyrics_json 为 NULL 的新段落会大量命中。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    seq: int | None = None
    title: str | None = None
    duration: float | None = None
    lyrics: list[LyricCharOut] = []


class AnnotationOut(BaseModel):
    """标注行。C4 `GET /api/segments/<id>/annotations` 的列表元素，
    **也是 C5 `POST /api/annotations` 的响应体**——同一个资源的同一形状，
    分成两个类只会在字段漂移时多一处要改。

    **tolerance / created_at 可空**：DDL 上这两列可空，库里只要有一行空值，
    写成非空就整个接口 500（同 DemoListOut / DemoSegmentOut 的坑）。
    `id` / `word_index` / `tag` 三列在 DDL 上是 NOT NULL，保持非空。

    字段名沿用文档给 C5 的入参名 `word_index`（C5 的说明是「新增标注
    （segment_id, word_index, tag, tolerance）」），不叫 index——出参与将来的
    写入字段名对齐，前端多写一行映射而已。

    **不出 char / category / note**：库里没有这三列。char 由前端从已加载的
    lyrics[word_index] 取（后端按下标去读 lyrics_json 会踩 C3 归一函数的
    丢弃错位）；category 是 CSS 类名、note 是拼出来的显示串，都属于 UI 措辞，
    同 C3 对 note 词表的口径（spec 3.2）。

    **不出 teacher_id**：C4 不按教师隔离，返回该唱段的全部标注（spec 3.4），
    给出 teacher_id 只会让人误以为有归属过滤。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    word_index: int
    tag: str
    tolerance: int | None = None
    created_at: datetime | None = None


# 标注技法词表（C5 入参 tag 的合法取值域）。
# 三处同源：本元组、annotation.html 六个类型按钮的 data-tag（第 492–497 行）、
# app/models/annotation.py 的类注释。将来按 tag 派发评测规则时，词表外的值
# 无法处理，所以在写入端就挡住。
ANNOTATION_TAGS = ("滑音", "归韵", "换气", "强音", "拖腔", "擞音")


class AnnotationIn(BaseModel):
    """C5 入参（`POST /api/annotations`）。

    **`teacher_id` 不在入参里**：从会话取（api 层传 `current_user_id()`）。
    让客户端指定归属等于开一个「以别人的名义标注」的越权入口。

    `tolerance` 可选：列在 DDL 上可空，C4 出参 `AnnotationOut` 也已允许 null。
    前端滑块总有值，但接口不必替调用方决定这个值一定存在。

    `word_index` 这里**只判非负**，上界在 service 判——上界要查 segments 与
    lyrics_json 才能算出来，是业务规则，不是入参格式。
    """

    segment_id: int
    word_index: int = Field(ge=0)
    tag: str
    tolerance: int | None = Field(default=None, ge=0, le=100)

    @field_validator("tag")
    @classmethod
    def _known_tag(cls, v: str) -> str:
        # 不用 Literal[...]：pydantic 对它的报错 type 是 literal_error，
        # app/common/errors.py 的 _MSG_CN 里没有这个映射，会回退成英文原文
        # "Input should be '滑音', '归韵', ..." 直接透给中文 UI。
        # 自定义 validator 抛的 ValueError 走的是 _MSG_CN 注释里的第 ②条路径，
        # 去掉 "Value error, " 前缀后原样展示。
        if v not in ANNOTATION_TAGS:
            raise ValueError("取值必须是 " + "/".join(ANNOTATION_TAGS) + " 之一")
        return v
