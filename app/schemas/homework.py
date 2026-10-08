from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class HomeworkListItem(BaseModel):
    """作业列表的一行（功能 4.1）。

    文档（《1-PRD》4.1、《3-功能清单》4.1、《5-接口清单》F1）的全部描述是
    「作业列表展示 — 进度/截止/提交人数」，**没有定义状态有哪些档、怎么判、
    分母放哪、怎么排序**。以下口径是本次实现定死的，与看板 G7
    （`app/schemas/dashboard.py::HomeworkProgressItem`）**逐字同源**——同一份数据
    在两条接口上必须是同一个档位，否则教师会在看板和作业页看到两个状态：

    - grading 批改中：有提交且存在未终审的提交（`submissions.status != 'reviewed'`）。
      优先级最高——截止没截止都要批；
    - closed 已截止：`homeworks.status == 'closed'` **或**截止日已过；
      截止当天算最后一天，仍可提交，不判已过；
    - ongoing 进行中：其余。

    **与 G7 的差别只有分母的位置**：G7 把分母放在响应级的一个 `student_count`，
    这里放在**每行**（`total`）。两个理由——(1) 页面每行就要渲染 `5/9` 与
    `submitted/total*100` 的进度条，行内拿到自己的分母最直接；(2) `homeworks`
    表目前没有班级/名单字段，所有作业共用同一个分母，但真实教学里作业是按班级
    布置的（`DOC_ISSUES.md` 第 25 条第 2 点），一旦补上班级维度每份作业的分母就会
    真的不同——那时响应级的一个数立刻作废，行内的不用改。所以这里**不再另给**
    响应级 `student_count`：那是同一个数字的第二个来源，漂移了就是线上事故。
    """

    model_config = ConfigDict(from_attributes=True)
    homework_id: int
    title: str
    deadline: date | None                 # 档案没填为 None，页面不显示截止
    demo_title: str | None                # 曲目名；作业没挂曲目（demo_id 为 NULL）为 None
    demo_role: str | None                 # 行当（青衣…）
    demo_banshi: str | None               # 板式（西皮流水…）
    submitted_count: int                  # 已提交**人数**（按学生去重）
    total: int                            # 分母：应提交人数（在册学生数）
    progress: float                       # submitted_count / total，0-1；total 为 0 时给 0
    pending_review_count: int             # 待批（未终审）条数，为 0 说明不用批
    status: str                           # grading / ongoing / closed


class HomeworkListResponse(BaseModel):
    """作业列表（功能 4.1）。

    不过滤、不截断、不分页：返回**全部**作业，由页面自己决定展示几条。
    库里没有作业时 `homeworks` 是 `[]`，**不是 404**。
    """

    model_config = ConfigDict(from_attributes=True)
    homeworks: list[HomeworkListItem]


class SubmissionTag(BaseModel):
    """待批改卡片上的一个 AI 归因标签。

    `label` 是 `ai_detail.defects[].label` 的**原文**（如「气息支撑不足」），后端
    不改写、不缩写——批改详情区（F5）用的是同一批文字，两处对不上教师会以为是两回事。

    `severity` 是 `defects[].status` 的**语义值透传**（high/medium/low），**不是**
    页面的 CSS 类名（`.tag.danger/.warn/.info`，见 homework.html:270-272）。出表现层
    词汇等于把「这个页面用这套配色」写进接口契约，换一版设计就要改后端。前端接到后
    自己映射；取到未知档时按中性色渲染即可，后端不做白名单过滤——滤掉一个未预期的
    分级会让标签凭空消失。
    """

    label: str
    severity: str


class PendingSubmissionItem(BaseModel):
    """待批改提交列表的一行（功能 4.3「AI 初评待终审」）。

    「待批改」= `submissions.status IS NULL OR status != 'reviewed'`，与 F1 的
    `pending_review_count` 逐字同源（口径见 spec 3.1）。因此 F1 里 hw12 的
    `pending_review_count` 与本列表的条数在干净数据下必然相等，验证时按这条对。

    **学生字段平铺，不做嵌套对象**：与同模块的 `demo_title/demo_role/demo_banshi`
    保持一种风格；嵌套更好看，但会引出「F5 要不要复用同一个 StudentBrief 模型」的
    跨接口耦合，而本项目的 schema 现在是彼此独立的，不为一个四字段对象破例。

    `student_name` / `student_level` / `student_avatar` 都可空：后两者是列本身可空
    （**张三的 avatar 是空串不是 NULL**，前端用 `||` 兜不到要看空串），前者还多一种
    情形——`students.user_id` 指向不存在的 user 时 join 不到（DOC_ISSUES 第 21/24 条
    描述的那类脏数据）。

    `tags` 的条数**没有上限**（spec 3.6）：页面自己声明的口径是「只展示置信度 > 0.7
    的标签」，那就按这条来，不再叠一层截断——真数据里刘思琪有 3 条过线，截到 2 会
    砍掉 0.71 的「拖腔不足」而留下 0.72 的「收尾偏急」，同量级留下哪个纯看运气。
    撑破布局是前端 CSS 该解决的问题，不该由后端悄悄丢数据。
    """

    model_config = ConfigDict(from_attributes=True)
    submission_id: int
    student_id: int | None              # students.id（不是 users.id）
    student_name: str | None            # users.display_name，经 students.user_id 拐一次
    student_avatar: str | None          # 可能是空串
    student_level: str | None           # 初学 / 进阶 / 高级
    ai_score: float | None              # AI 初评分数
    submitted_at: datetime | None       # 列可空；出参是 ISO-8601
    tags: list[SubmissionTag]           # 置信度 > 0.7 的归因标签，按置信度降序


class PendingSubmissionListResponse(BaseModel):
    """待批改提交列表（功能 4.3）。

    作业存在但没有待批提交时 `submissions` 是 `[]`，**不是 404**——「这份作业没有
    东西要批」是正常状态。作业**不存在**才 404，由 service 抛 BusinessError。

    与 F1「库里没有作业返回 `[]` 而非 404」不矛盾：F1 查的是集合（空集合是合法
    结果），这里查的是一个具名资源。

    `homework_title` 是给批改详情区标题用的：页面现在用 `HOMEWORKS[0].title` 硬编码
    （homework.html:813），接入后应显示当前作业名。前端本可以从 F1 的列表里查，但
    那要多一次请求和一份前端状态；这里一个字符串就够。
    `homework_id` 是路径参数回显，异步返回时用来确认是不是当前选中的那份，避免竞态。

    不分页（spec 3.8）：一份作业的待批提交是教师一次批完的工作量（真库 5 条），
    分页要的 page/size/total 三个参数与前端翻页状态远超收益。
    """

    model_config = ConfigDict(from_attributes=True)
    homework_id: int
    homework_title: str
    submissions: list[PendingSubmissionItem]


class CdmTag(BaseModel):
    """F5 批改详情里的一条 CDM 归因诊断标签（功能 4.6）。

    与 F4 的 `SubmissionTag` **不是同一个模型，也不要合并**：F4 只出 label + severity
    两个字段（卡片上就显示这两样），这里出全字段。两处的字段面会各自演化，共用一个
    模型会逼着它们同步，而它们需要的本来就不是一回事。

    **与 F4 的关键差异一：confidence 不设阈值。** F4 的 tags 只取 > 0.7，那条阈值是
    待批卡片自己的展示口径（F4 spec 3.5）；批改页是教师逐条判断 AI 对不对的地方，
    低置信度的标签恰恰是最该被质疑、因而最该被看见的一条。真库里 23 的 0.45、
    24 的 0.52、26 的 0.65 三条会因此出现在这里而不出现在卡片上，这是**有意的**。

    **与 F4 的关键差异二：confidence 取不到的元素不丢。** F4 是拿它排序筛选的，缺了
    没法定位；这里只是把它带出去，藏起来比带个 `null` 严重。这类元素给 None 排末尾。

    `severity` 是 `defects[].status` 的原文透传（high/medium/low），不是 CSS 类名，
    取不到给 `"unknown"`——同 F4 spec 3.11，不做白名单过滤（滤掉一个未预期的分级会
    让标签凭空消失）。

    `category` / `evidence` / `features` 是 AI 侧写入、F4 刻意不出的字段（F4 spec
    第 1090 行已声明它们是「批改详情页（F5）的内容」）。
    `id` 与 `defects[].id` 同名透传，供将来的逐条确认/驳回定位。
    """

    model_config = ConfigDict(from_attributes=True)
    id: str | None
    label: str
    severity: str
    confidence: float | None
    category: str | None
    evidence: str | None
    features: dict | None


class BktChange(BaseModel):
    """F5 的 BKT 前后对比一条（功能 4.7）。

    由 `submissions.bkt_before` / `bkt_after` 两个扁平字典（技法名 → P(L)）按 key
    并集合并而来，一侧没有的技法给 None。

    `delta` 由**后端**算（教师端只做展示，不该在前端算业务量），且 round 到 4 位：
    `0.48 - 0.46` 在浮点下是 0.020000000000000018，直接出会给前端一个 18 位小数。
    仅 before / after 都是数值时才算，否则 None。
    """

    model_config = ConfigDict(from_attributes=True)
    skill: str
    before: float | None
    after: float | None
    delta: float | None


class LyricWord(BaseModel):
    """F5 的歌词级偏差对比里的一个字（功能 4.4）。

    **当前恒为空数组**：`submissions` 没有逐字列，`ai_detail` 也没有 lyrics/words
    键——库里无数据源（spec 2.5）。契约现在就定死，等 F3 把 B 组结果落进 ai_detail
    时直接读。

    元素对齐 B 组 `words[]` 的**子集**（`app/services/analyze_service.py::_words`），
    字段名用 B 组的 `word` 而不是前端 mock 的 `char`：同一份逐字偏差在 B4 与 F5 两条
    接口上形状必须一致，将来落库时不必再翻译一次。

    **不出展示层的着色档**（excellent/good/fair/punct）：《5-接口清单》3.2 的原文是
    「着色规则在**前端**按 regions.level 渲染」。后端只出 deviation_cents 与 warning
    （B 组已按红黄阈值算好）。

    B 组 words 的另外三个字段 teacher_freq / student_freq / octave_fixed 不出——它们
    服务于音准曲线对比图，不是「歌词级偏差对比」的最小集；将来要加是非破坏性变更。
    """

    model_config = ConfigDict(from_attributes=True)
    index: int
    word: str | None
    start: float | None
    end: float | None
    deviation_cents: float | None
    warning: bool | None


class SubmissionCalibration(BaseModel):
    """一条 AI 评分校准记录（功能 4.10）。

    **F7 的响应体与 F5 详情里的 `calibration` 字段共用本类**——两处必须是同一个形状，
    否则页面「刚写完」与「重新打开」会渲染出两种结果。

    from_attributes=True：F7 与 F5 都从 ORM 行直接 `model_validate(row)` 构造，
    不手抄四个字段（抄漏一个不会有任何报错，只会安静地少一个键）。
    """

    model_config = ConfigDict(from_attributes=True)

    bias_mode: str
    ai_score: float | None
    teacher_score: float | None
    created_at: datetime


class SubmissionCalibrationIn(BaseModel):
    """F7 入参（`POST /api/submissions/<id>/calibration`，功能 4.10）。

    只有一项——`ai_score` / `teacher_score` / `teacher_id` 全由服务端取（spec 3.2），
    客户端传不了。

    `bias_mode` **没有默认值**，这是有意的：缺省要报「必填」（422），只有显式传
    `null` 才表示「撤销该校准」（spec 3.4）。写成 `= None` 会让缺省也变成合法，
    两种情形就分不开了。

    取值集合是封闭的三值，用 `Literal` 表达。代价：非法值抛 `literal_error`，
    不在 `app/common/errors.py` 的 `_MSG_CN` 里，message 回退英文原文（spec 3.8）。
    """

    bias_mode: Literal["high", "low", "ok"] | None


class SubmissionDetailResponse(BaseModel):
    """F5 批改详情（功能 4.4-4.7）。

    学生字段平铺不嵌套，同 F4 spec 3.9（不为一个四字段对象破例）。

    **三处显式空位，都是「库里没有数据源」而不是「本次没做」：**

    - `lyrics` 恒为 `[]`（功能 4.4 逐字偏差无数据源，spec 2.5 / 3.5）
    - `dimensions` 恒为 `None`（功能 4.5 四维分数无数据源，spec 2.5 / 3.6）
    - **不出 `fusion` 键**：前端 mock 的 fusion.total（0.72）按 40/30/20/10 加权它
      自己的 dimensions（84/84/86/80）算出来是 0.84，两数不符，真实语义文档从未
      定义。凭空造一个只会把 mock 的错误固化进契约。总分由 `ai_score` 承担。
      40/30/20/10 这套权重也**不进接口**——没有任何数据能与它相乘。

    功能 4.5 的四块里唯一有数据的是 `feature_matrix` 与 `overall_confidence`，原样
    透传；键名保留 AI 侧的驼峰（pitchStd 等），不做 snake_case 转换——改名会让它和
    写入方对不上，查问题时两边对不上号。

    批改现状那六个字段（status / teacher_score / teacher_comment / voice_comment_text
    / voice_comment_audio_id / reviewed_at）是 F6 写入的列，严格说不属功能 4.4-4.7。
    放进来是因为**没有它们本接口不可用**：status 是判「这份还批不批」的唯一依据；
    一个「批改详情」GET 若不回当前批改结果，F6 提交完还得另调接口才知道自己写了什么；
    `voice_comment_audio_id` 不给的话，功能 4.11 的语音点评音频就取不回来（前端要拿
    它走 B5 `GET /api/audio/<file_id>`）。

    `calibration` 是**第七个**批改现状字段，但它来自另一张表（`score_calibrations`，
    功能 4.10 / F7）——上面六个是 F6 写在 `submissions` 上的列。这里原来写的是「不出
    校准，那是 F7 的读职责」，2026-10-08 推翻：F7 在《5-接口清单》里只有 POST，读职责
    没有落点；不出的话教师打开一条已批改的提交，看不到自己勾过什么。取值口径见 F7 spec
    §3.6（同一提交多行时取最新一条），没校准过是 `None` 而不是空对象。

    真库里的一个反常照实透传、不替它推断：23/24 的 teacher_score 与 teacher_comment
    已有值，但 status 仍是 `ai_scored`、reviewed_at 仍是 NULL（「写了分数但没走终审」）。
    F6（`POST /api/submissions/<id>/review`）落地后已有代码会写 reviewed，但这两行是
    种子数据、从没走过终审接口，所以照旧透传——不替种子数据补一次「事后终审」。
    """

    model_config = ConfigDict(from_attributes=True)
    # 头部
    submission_id: int
    homework_id: int | None
    homework_title: str | None
    student_id: int | None
    student_name: str | None
    student_avatar: str | None
    student_level: str | None
    submitted_at: datetime | None
    audio_id: int | None
    # 4.5 多维加权融合评分
    ai_score: float | None
    overall_confidence: float | None
    feature_matrix: dict | None
    dimensions: dict | None
    # 4.4 歌词级偏差对比
    lyrics: list[LyricWord]
    # 4.6 CDM 归因诊断标签
    cdm_tags: list[CdmTag]
    # 4.7 BKT 状态更新对比
    bkt: list[BktChange]
    # 批改现状
    status: str | None
    teacher_score: float | None
    teacher_comment: str | None
    voice_comment_text: str | None
    voice_comment_audio_id: int | None
    reviewed_at: datetime | None
    # 4.10 AI 评分校准（F7 写入，读侧归本接口）
    calibration: SubmissionCalibration | None


class SubmissionReviewIn(BaseModel):
    """F6 入参（`POST /api/submissions/<id>/review`，功能 4.8/4.9/4.11）。

    四个字段全部可选，且**「字段不出现」与「显式给 null」是两件不同的事**：
      - 字段不出现 → 该列保持原值
      - 字段显式 null → 该列清空
    service 靠 `model_fields_set` 判，**不能**写成 `if v is not None`——那会把两者
    混成一种，「清空某个字段」就永远做不到（spec 3.2）。

    四个字段都不出现（`{}`）也合法，语义是「一键通过」：只推进状态，一个内容列都
    不动（spec 3.5，对应 mobile 文档的「一键通过（终审保留）」）。
    """

    teacher_score: float | None = None
    teacher_comment: str | None = None
    voice_comment_text: str | None = None
    voice_comment_audio_id: int | None = None

    @field_validator("teacher_score")
    @classmethod
    def _score_in_range(cls, v: float | None) -> float | None:
        """终审分限 0–100（前端 `#finalScore` 的 min/max 就是这个范围）。

        不用 `Field(ge=0, le=100)`：`app/common/errors.py` 的 `_MSG_CN` 只有
        missing / string_too_short / string_too_long / int_parsing 四条，**没有**
        `greater_than_equal` / `less_than_equal`，用 Field 越界时回的是 pydantic 的
        英文原文。这里抛中文，`_format_validation_error` 会去掉 "Value error, "
        前缀后原样展示（同 app/schemas/demo.py 的 `AnnotationIn._known_tag`）。

        另：给非数字（如 `"abc"`）时会在到达这里之前就被 pydantic 挡下，报的是
        英文的 `float_parsing`——`_MSG_CN` 同样没有这个键。照实接受，理由见 spec 3.7。
        """
        if v is not None and not 0 <= v <= 100:
            raise ValueError("终审评分必须在 0 到 100 之间")
        return v


class SubmissionReviewResponse(BaseModel):
    """F6 出参：**只回本接口写下去的那几个字段**，不是 F5 的全量详情。

    不复用 F5 的 `SubmissionDetailResponse`：那个带着 lyrics / cdm_tags / bkt /
    feature_matrix 等一堆本接口用不上的形状，复用它会让 F6 的契约跟着 F5 一起变。
    前端写完要拿全量详情，再调一次 F5（spec 4.4）。
    """

    # from_attributes 在本模型上其实**用不到**——service 是用关键字参数构造的
    # （submission_id 与 ORM 的 row.id 不同名，`model_validate(row)` 走不通）。
    # 留着是为了与本文件另外 8 个响应模型一致：9 个里 8 个有它，独缺这个才是会
    # 被挑出来的不一致。
    model_config = ConfigDict(from_attributes=True)

    submission_id: int
    status: str | None
    reviewed_at: datetime | None
    teacher_score: float | None
    teacher_comment: str | None
    voice_comment_text: str | None
    voice_comment_audio_id: int | None
