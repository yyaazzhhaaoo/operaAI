# F6 `POST /api/submissions/<id>/review` 设计（教师终审批改）

> 本文只覆盖**后端**。前端 `homework.html` 的终审区（`submitReview` / `saveDraft` /
> `playVoiceComment` 三个 alert 桩）本轮不动，属另一轮。

## 1 背景、目标与非目标

### 1.1 目标

实现《5-接口清单》F6：教师对一条提交做终审——写终审分、终审评语、语音点评，并把该条
从「待批改」推进到「已终审」。落地后**全项目第一次有代码把 `submissions.status` 写成
`'reviewed'`**。

这条不只是补一个写接口。DOC_ISSUES 第 25 条（`:622`）与第 34 条（`:1039`）都记着同一个
连带表现：作业列表的「批改中」判据是 `submissions.status != 'reviewed'`，而此前**没有任何
代码会写这列**，所以一份作业只要有提交就永远显示「批改中」，教师无从消除。两处原文都写着
「等 F6 落地即自动恢复」。F6 是本项目里第一个能让这个状态真正流转起来的接口。

### 1.2 非目标

- 不动 `homework.html`（前端终审区仍是三个 alert 桩）。
- 不实现 F7（`/calibration`）、不写 `score_calibrations`。
- 不做「保存草稿」语义（见 §3.1）。
- 不做退回 / 撤销终审（见 §3.9）。
- 不引入 pytest、不加分页、不改 `schema.sql`、不新增 DDL。
- 不抽公共模块：`_payload()` 按既有两份逐字复制第三份（§4.2）。
- 不动 `app/common/errors.py` 的 `_MSG_CN`（理由见 §3.7）。

---

## 2 文档真源与现状

### 2.1 文档给了一行

《5-接口清单-V1.0》2.6 作业批改，F6 一行的全部内容：

```
F6 | POST /api/submissions/<id>/review | 教师 | 终审评分/点评/语音点评（audio_id + text）（功能 4.8/4.9/4.11）
```

《3-功能清单-V1.0》模块 4 里，被点名的三个功能点各也只有表格里一行：

| 编号 | 功能点 | 说明（全文） |
|---|---|---|
| 4.8 | 老师终审评分 | 终审分数 |
| 4.9 | 老师终审点评 | 文本建议 |
| 4.11 | 语音点评 | **语音识别转文字** |

同文档「五、移动端支持」的手机端裁剪表另有一行：

```
作业批改 | ✅ 裁剪版 | 语音批改+快捷评语+一键通过（终审保留）
```

请求体字段名、字段可空性、状态流转、幂等语义、错误码——**文档一个字都没写**。

### 2.2 与 F4 / F5 的关系

三个接口咬在同一批数据上，边界要划清：

- **F4** `GET /api/homeworks/<id>/submissions` 列「待批改」提交，判据
  `status IS NULL OR status <> 'reviewed'`（DOC_ISSUES 第 35 条 `:1089`）。
  **F6 是唯一会改变这个判据结果的接口**——终审一条，F4 的列表就少一条。
- **F5** `GET /api/submissions/<id>/detail` 已经把 F6 要写的六列全部出参了
  （spec §3.9 明确写了「这些是 F6 写入的列，放进来是因为没有它们本接口不可用」）。
  所以 F6 不需要动 F5。
- **F7** 读 `score_calibrations`。F6 不碰它（§3.10）。

### 2.3 真库基线（2026-10-08 写本设计时实测，验证时逐条对照）

`submissions` 全 5 行，逐列快照（`∅` = NULL）：

| id | hw | stu | ai_score | teacher_score | teacher_comment | voice_audio | voice_text | status | submitted_at | reviewed_at |
|---|---|---|---|---|---|---|---|---|---|---|
| 23 | 12 | 48 | 82.5 | 82.5 | 音准整体良好，拖腔处理有进步。建议在'雷'字拖腔时加强气息支撑，保持音高稳定。继续练习！ | ∅ | ∅ | ai_scored | 2026-08-02 00:00:00 | ∅ |
| 24 | 12 | 50 | 75.2 | 75.2 | 音准偏差较大，建议先进行单音模唱训练。 | ∅ | ∅ | ai_scored | 2026-08-01 00:00:00 | ∅ |
| 25 | 12 | 53 | 78.9 | ∅ | ∅ | ∅ | ∅ | ai_scored | 2026-08-02 00:00:00 | ∅ |
| 26 | 12 | 55 | 71.3 | ∅ | ∅ | ∅ | ∅ | ai_scored | 2026-08-01 00:00:00 | ∅ |
| 27 | 12 | 52 | 85.7 | ∅ | ∅ | ∅ | ∅ | ai_scored | 2026-08-01 00:00:00 | ∅ |

派生量：`status` 取值分布 `ai_scored`×5；hw12 按 F4 判据的条数 = **5**；全 5 行
`audio_id` 与 `voice_comment_audio_id` 均为 NULL。

另：**`audio_files` 的 id 从 74 起**（实测 `min(id) = 74`，最小的几行是示范库音频
74–82）。验证里要拿一个真实存在的音频 id 时用 **74**，`1` 在库里不存在——写 `1` 会落到
§5.3 第 9 条的 422 分支上去，验不出 `200`。

**这条基线就是 §5.4 的复原依据。** 23/24 有 `teacher_score` 但 `status` 仍是 `ai_scored`、
`reviewed_at` 仍是 NULL，是种子里「写了分数但没走终审」的状态（F5 spec §3.9 已记）。
F6 不做任何推断去「纠正」它——只有真被调用的那一条才会变。

### 2.4 库表事实

`schema.sql:128-144` 的 `submissions` 与《4-数据库设计》逐字一致。本接口相关列：

| 列 | 类型 | 可空 | 默认 | 备注 |
|---|---|---|---|---|
| `teacher_score` | FLOAT | 是 | — | |
| `teacher_comment` | TEXT | 是 | — | 无长度上限 |
| `voice_comment_audio_id` | INT → `audio_files(id)` | 是 | — | 注释「功能4.11语音点评」 |
| `voice_comment_text` | TEXT | 是 | — | |
| `status` | VARCHAR(10) | 是 | `'ai_scored'` | 行尾注释 `submitted/ai_scored/reviewed` |
| `reviewed_at` | TIMESTAMP | 是 | — | |

三条要记住的事实：

1. **`status` 没有 CHECK 约束，也没有枚举类型。** 三个取值只活在行尾注释里。全文 `CHECK`
   只出现两次（`users.role`、`annotations.tolerance`）。`VARCHAR(10)` 够装三个取值。
2. **`submissions` 上没有 `reviewer_id`，也没有任何指向 `users(id)` 的外键。**
   `student_id` 指向 `students(id)`。所以**本接口无法记录「是谁批的」**——这不是遗漏，
   是表里没有这个位置（§2.5）。
3. **`audio_files` 只有 `uploader_id` + `access`，没有 `purpose` / `kind`。** 无法从表结构
   区分一条音频是「学生作业录音」还是「教师语音点评」；用途靠 `submissions` 这一侧的两个
   外键列承载（方向是「业务表 → audio_files」，`audio_files` 没有反向列）。

### 2.5 三个硬缺口

**缺口一：4.11 的「语音识别转文字」在本项目没有实现组件。**
功能清单写的是「语音识别转文字」，但项目里没有任何 ASR。DOC_ISSUES 第 20 条与第 439 行
都记着同一件事：要从音频得到汉字需要语音识别，而解析链路没有这一环（这也是
`segments.lyrics_json` 恒为 NULL 的原因）。**所以 `voice_comment_text` 服务端造不出来**，
本接口只能把它当客户端给的普通字符串收下（§3.4）。

**缺口二：无法记录批改人。** 见 §2.4 第 2 点。F6 只能改「这份提交的状态」，改不了
「谁改的」。

**缺口三：没有教师归属模型。** `schema.sql` 里没有 `classes` 表，`students` 只有
`user_id / level / avatar / enrolled_at`，`users` 只有 `role`——**任何教师与任何学生之间
没有任何归属边**。所以「这位教师能不能批这条提交」在库里无据可查（§3.6）。

---

## 3 自拟口径

### 3.1 只做终审，不做草稿（`status` 恒为 `'reviewed'`）

前端有「💾 保存草稿」按钮，但**文档只定义了终审**：F6 一行是「终审…」，4.8/4.9/4.11 三个
功能点里没有草稿。把草稿收进 F6 等于自造一套状态机（`status` 该取什么值？草稿要不要进
F4 的待批列表？`)——这些都是文档没有的问题。

因此：**本接口没有「只存不发布」的语义，一调就是终审。** 前端那个按钮继续留桩，等文档
先定义草稿态。

### 3.2 PATCH 语义：字段缺省 = 不动，显式 `null` = 清空

教师只补一条语音点评时，不该把已填的分数和评语抹掉；反过来，教师确实需要能清空某个字段。
两者用一个规则同时满足：

| 请求体里的形态 | 结果 |
|---|---|
| 字段**不出现** | 该列保持原值 |
| 字段显式给 `null` | 该列置 NULL |
| 字段给值 | 该列写成该值 |

实现靠 pydantic v2 的 `model_fields_set`（`"字段是否被显式提供"`），**不能**用
`if data.teacher_score is not None` 判断——那会把「显式 null」和「没给」混成一种，清空
就永远做不到。

**为什么不是全量替换**：全量替换下，「一键通过」只传分数会把评语清掉、只传语音会把分数
清掉，教师很难预料自己刚才抹掉了什么。

### 3.3 允许覆盖：已终审的再提交就是更新

`status` 已是 `reviewed` 时再调本接口，不报错，直接覆盖，`reviewed_at` 刷新为本次时间。

理由：教师改个错字不该先想办法把状态退回去，而库里**没有任何退回接口**（§3.9）。代价是
`reviewed_at` 的语义从此是「**最近一次**终审时间」，不是「首次终审时间」——这条要写进
DOC_ISSUES（§7）。

### 3.4 `voice_comment_text` 由客户端给，服务端不转写

4.11 要的是「语音识别转文字」，而服务端没有 ASR（§2.5 缺口一）。所以本接口把
`voice_comment_text` 当**普通可选字符串**收下，不校验它跟音频是否对得上、也不尝试生成它。

教师只传音频不传文字时，`voice_comment_text` 保持原值（PATCH 语义）——结果是
「有音频、无文字」的一条语音点评，前端靠 `voice_comment_audio_id` 走 B5 播出音频即可，
文字位留空。这是**当前唯一可实现的形态**，不是设计取舍。

### 3.5 空 body 合法 = 「一键通过」

`{}` 是合法请求：只把 `status` 推到 `reviewed`、`reviewed_at` 落 `NOW()`，四个内容列
一个都不动（PATCH 语义下缺省即不动）。mobile 文档里的「一键通过（终审保留）」就是它。

此时 `teacher_score` 保持它原来的值：新提交上是 NULL。**不把 `ai_score` 抄进
`teacher_score`**——那等于替教师的评分背书，而 `ai_score` 本身可空（真库有 NULL 的先例）。
`(teacher_score IS NULL AND status='reviewed')` 这个组合的语义就是「教师原样认可 AI 的
结果」，前端 F5 已经写着 `teacher_score ?? ai_score`，显示上自然落到 AI 的分。

### 3.6 权限：教师即可，不校验归属

`@login_required` + `@teacher_required`（依据同 F5：清单权限列写「教师」，《6-登录与数据
隔离方案》权限矩阵里「布置/批改作业」学生 ❌）。

**不校验「这条提交是不是这位教师的学生的」**——库里没有可依据的归属边（§2.5 缺口三）。
这与 F4/F5 现状一致（那两个接口同样不按教师过滤）。任何教师登录后都能批任何提交，这是
**当前库表结构下的必然结果**，登记进 DOC_ISSUES。

### 3.7 `teacher_score` 范围用局部 validator，不动 `_MSG_CN`

范围定 **0 ≤ x ≤ 100**：前端 `#finalScore` 就是 `min="0" max="100" step="0.1"`，这是
页面上唯一的分数输入框。

校验**不用** `Field(ge=0, le=100)`，改用 `@field_validator` 抛中文 `ValueError`——
因为 `app/common/errors.py` 的 `_MSG_CN` 里只有 `missing` / `string_too_short` /
`string_too_long` / `int_parsing` 四条，**没有** `greater_than_equal` / `less_than_equal`，
用 `Field` 约束越界时回的是 pydantic 的英文原文（C5 的 `AnnotationIn.tolerance` 今天就是
这样）。局部 validator 抛的 `ValueError` 会被 `_format_validation_error` 去掉
`"Value error, "` 前缀后原样展示，是中文——与 `AnnotationIn._known_tag` 同一套做法。

**不改 `_MSG_CN`**：那个 dict 是所有接口共用的，加键会顺带改掉其它接口（含 C5）现在的
报错文案，属于本任务范围外的行为变更。

**残留的英文一处**：`teacher_score` 给的是非数字（如 `"abc"`）时，pydantic 抛
`float_parsing`，而 `_MSG_CN` 没有这个键 → 回退英文原文。**照实接受**，不改共享 dict；
这条记进 DOC_ISSUES。

### 3.8 `voice_comment_audio_id` 只校验存在性

给的值必须在 `audio_files` 里有对应行，查不到回 **422 `语音点评音频不存在`**。

用 422 而不是 404：404 在本项目里留给「URL 里的那个具名资源不存在」（F4/F5 的
`作业不存在` / `提交不存在`），而这里是**请求体里引用了一个不存在的资源**，属于请求体
不合法。用 404 会让前端分不清「我调的地址不对」还是「我传的 id 不对」。

**不校验归属**（不比较 `audio_files.uploader_id` 与当前教师）——同 §3.6，库里没有归属模型，
单独在这一处引入归属判断会与 F4/F5 的口径不一致。副作用是教师可以把语音点评指向任意一条
音频 id，包括别人的私有录音；那条音频能不能播由 B5 自己的权限判定管，不由本接口管。

### 3.9 不做退回 / 撤销终审

文档没有这个功能点（4.8/4.9/4.11 都不含），清单里也没有对应接口。终审后想把一条改回
「待批改」目前**做不到**——本接口只能把它继续保持 `reviewed`（覆盖即等于改内容，不改状态）。

这是有意的：加一个「退回」需要先定义状态机（退回后 `teacher_score` 留不留？再造一个
`returned` 档？），而那需要文档先说话。登记进 DOC_ISSUES 的待确认项。

### 3.10 不写 `score_calibrations`

4.10「AI 评分校准」是 F7 的职责（`POST /api/submissions/<id>/calibration`），它写
`score_calibrations`（该表已有 1 行：`submission_id=24`）。F6 终审时**不替 F7 写这张表**：
「教师把分从 75.2 改成 90」并不自动等于「AI 评分偏低」这个校准结论——那是教师在 F7 页面上
显式勾选的动作。两个接口各写各的表。

### 3.11 内容字段不设长度上限

`teacher_comment` / `voice_comment_text` 都是 TEXT（PG 上限约 1GB）。不设 `max_length`：
文档没给上限，而且给一个拍脑袋的数字（比如 500 字）会把教师写的长评语变成 422。

### 3.12 `submitted` 档不写

`status` 行尾注释列了 `submitted / ai_scored / reviewed` 三档，但**全项目没有任何代码写
`submitted`**（F3 提交接口还是空桩）。本接口只写 `reviewed`，不碰另外两档。登记进 DOC_ISSUES。

---

## 4 实现设计

### 4.1 分层与落点

沿用 F1/F4/F5 的四层，文件名与函数名：

| 文件 | 改动 | 说明 |
|---|---|---|
| `app/api/homeworks.py:49-53` | 桩换成真实现 | 改路由转换器 + 校验 + 调 service |
| `app/schemas/homework.py` | **新增两个模型** | `SubmissionReviewIn`（本文件第一个请求体模型）、`SubmissionReviewResponse` |
| `app/services/homework_service.py` | **新增 `review_submission`** | 判 404、校验音频、写列、commit |
| `app/repositories/homeworks_repo.py` | **新增两个函数** | `get_submission`（轻量取行）、`apply_review`（标脏） |

复用 `app/repositories/audio_repo.py:36` 的 `get_by_id` 做音频存在性校验，不新写。

### 4.2 路由（`app/api/homeworks.py`）

把 `:49-53` 的桩整段替换（保留两个装饰器不动）：

```python
def _payload() -> dict:
    """取 JSON 请求体。

    客户端没带 Content-Type: application/json 时 get_json() 会抛 415；
    silent=True 把它压成 None，这里再兜成 {}，让 pydantic 报「字段必填」
    而不是让 Flask 抛一个前端看不懂的 415。
    """
    return request.get_json(silent=True) or {}


@api_bp.route("/submissions/<int:submission_id>/review", methods=["POST"])
@login_required
@teacher_required
def submissions_review(submission_id):
    # mode="json"：出参里有 datetime（reviewed_at）。默认 model_dump()
    # 会给 Flask 一个 datetime 对象，而它按 RFC-822 序列化成
    # "Thu, 08 Oct 2026 00:00:00 GMT"；mode="json" 出的是 ISO-8601。同 F1/F4/F5。
    data = SubmissionReviewIn.model_validate(_payload())
    return ok(homework_service.review_submission(
        get_db(), submission_id, data).model_dump(mode="json"))
```

四点说明：

1. **`<int:submission_id>` 替换 `<id>`**：`<id>` 是字符串转换器，会把
   `/submissions/abc/review` 也匹配进来、进到视图里再去查库；`<int:...>` 让 Werkzeug 在
   路由层就挡掉（`IntegerConverter` 正则 `\d+`，连负数都不收），走 `errors.py` 的统一
   404 `{"code":404,"message":"接口不存在"}`。同文件 F1/F4/F5 全是 `<int:...>`。
2. **路由层不写 `try/except`、不写 `fail(...)`**：所有失败由 service 抛
   `BusinessError`，全局 handler 转。`homeworks.py` 现在通篇没有失败分支，保持这样。
3. **`_payload()` 逐字复制第三份**，不抽公共模块。`demos_segments_annotations.py:18-25`
   与 `app/api/auth.py:27-34` 已有两份逐字相同的私有 helper，这是本项目的既有形态；
   把它提到 `app/common/` 属于无关重构。**`silent=True` 不能省**。
4. **`import` 增补**（已核对现状：本文件现在只 import 了 `api_bp`、三个装饰器、
   `get_db`、`ok`、`homework_service`，**`request` 与 schemas 都没有**）：
   补 `from flask import request` 与
   `from app.schemas.homework import SubmissionReviewIn`。

### 4.3 入参模型（`app/schemas/homework.py`）

```python
class SubmissionReviewIn(BaseModel):
    """F6 入参（`POST /api/submissions/<id>/review`）。

    四个字段全部可选，且**缺省与显式 null 不是一回事**：
    字段不出现 = 该列保持原值；显式给 null = 该列清空。service 靠
    `model_fields_set` 区分，不能用 `is not None` 判——那会把两者混成一种，
    清空就永远做不到（spec 3.2）。

    四个都给/都不给都合法：`{}` 就是「一键通过」（spec 3.5）。
    """

    teacher_score: float | None = None
    teacher_comment: str | None = None
    voice_comment_text: str | None = None
    voice_comment_audio_id: int | None = None

    @field_validator("teacher_score")
    @classmethod
    def _score_in_range(cls, v: float | None) -> float | None:
        # 不用 Field(ge=0, le=100)：errors.py 的 _MSG_CN 没有
        # greater_than_equal / less_than_equal，用 Field 越界回的是 pydantic
        # 的英文原文。这里抛中文 ValueError，_format_validation_error 去掉
        # "Value error, " 前缀后原样展示（同 AnnotationIn._known_tag，spec 3.7）。
        if v is not None and not (0 <= v <= 100):
            raise ValueError("终审评分必须在 0 到 100 之间")
        return v
```

`float | None` 允许 `82`（int 会被 pydantic 收成 float），不需要额外处理。

**`import` 增补**：`app/schemas/homework.py` 现在只有
`from pydantic import BaseModel, ConfigDict`，**没有 `field_validator`**，要补上
（`from pydantic import BaseModel, ConfigDict, field_validator`）。`datetime` 已在
文件头第一行 import 过，不用再补。

**不设 `max_length`**（§3.11）。**不在这里校验音频存在性**——那要查库，属 service。

### 4.4 出参模型（`app/schemas/homework.py`）

```python
class SubmissionReviewResponse(BaseModel):
    """F6 出参。**只回本接口写的那几个字段**，不是 F5 的全量详情。

    F5 的 SubmissionDetailResponse 含 lyrics / cdm_tags / bkt 等本接口用不上的
    形状，复用它会让 F6 的契约跟着 F5 变（spec 4.4）。
    """

    # from_attributes 在本模型上是**用不到的**：service 用关键字参数构造
    # （submission_id 与 ORM 的 row.id 不同名，model_validate(row) 走不通）。
    # 保留它是为了与本文件另外 8 个响应模型一致——9 个里 8 个有它，
    # 独缺这一个才是会被 review 挑出来的不一致。
    model_config = ConfigDict(from_attributes=True)

    submission_id: int
    status: str | None
    reviewed_at: datetime | None
    teacher_score: float | None
    teacher_comment: str | None
    voice_comment_text: str | None
    voice_comment_audio_id: int | None
```

`reviewed_at` 是 `datetime`，**路由层必须 `.model_dump(mode="json")`**（§4.2 注释）。

### 4.5 repo（`app/repositories/homeworks_repo.py`）

```python
def get_submission(db: Session, submission_id: int) -> Submission | None:
    """按 id 取提交行，不存在返回 None。供 F6 判 404 与标脏。

    **不复用 get_submission_detail**：那个要四张表的字段、走三段 LEFT JOIN，
    而 F6 只需要 Submission 本身（要改它的列）。用那个会白查三条 join，
    且它返回的是元组（改不了 ORM 属性）。
    """
    return db.get(Submission, submission_id)


def apply_review(db: Session, row: Submission, changes: dict) -> None:
    """把 changes 里的列写到 row 上。只标脏，提交交给 service 层。

    changes 的 key 必须是 model_fields_set 里出现过的字段名——调用方（service）
    负责区分「缺省」与「显式 null」，本函数不做判断，给什么写什么。
    """
    for field, value in changes.items():
        setattr(row, field, value)
```

`apply_review` 不收 id 而收 ORM 对象：service 已经为了判 404 把行取出来了（同
`annotations_repo.remove` 的约定）。**repo 不 commit**（`app/repositories/__init__.py:1-9`）。

`apply_review` 只 `setattr` 不 `flush`：本次没有自增 id 要拿（`annotations_repo.add` 要
`flush` 是为了拿 id），脏对象由 service 的 `commit()` 一并写回。

### 4.6 service（`app/services/homework_service.py`）

```python
# 入参字段名 → submissions 列名。四个字段与四个列现在一一同名，这张表
# 因此看着冗余，但它是**唯一的映射声明点**：将来入参要改名（比如对外叫
# audio_id、对内叫 voice_comment_audio_id）只改这里，不用去 service 里
# 逐个 setattr 找。
_REVIEW_FIELDS = (
    "teacher_score",
    "teacher_comment",
    "voice_comment_text",
    "voice_comment_audio_id",
)


def review_submission(
    db: Session, submission_id: int, data: SubmissionReviewIn
) -> SubmissionReviewResponse:
    """F6 终审：写终审分/评语/语音点评，并把 status 推到 reviewed。

    已 reviewed 的再调用 = 覆盖更新，reviewed_at 刷新（spec 3.3）。
    """
    row = homeworks_repo.get_submission(db, submission_id)
    if row is None:
        raise BusinessError(404, "提交不存在")

    # 只把**显式出现过**的字段写下去：没出现 = 保持原值（spec 3.2）。
    # 不能写 `if getattr(data, f) is not None`——那会让显式 null 清空失效。
    changes = {f: getattr(data, f) for f in _REVIEW_FIELDS
               if f in data.model_fields_set}

    # 引用的音频必须存在。查不到回 422 而不是 404：404 在本项目里留给
    # URL 里的具名资源（spec 3.8）。
    if changes.get("voice_comment_audio_id") is not None:
        if audio_repo.get_by_id(db, changes["voice_comment_audio_id"]) is None:
            raise BusinessError(422, "语音点评音频不存在")

    homeworks_repo.apply_review(db, row, changes)
    row.status = "reviewed"
    row.reviewed_at = datetime.now()

    # 出参在 commit **之前**组装。commit 会让 ORM 实例的属性过期，
    # 之后再读会多发一次 SELECT 把四个字段重新拉一遍（同 C5 的注释）。
    out = SubmissionReviewResponse(
        submission_id=row.id,
        status=row.status,
        reviewed_at=row.reviewed_at,
        **{f: getattr(row, f) for f in _REVIEW_FIELDS},
    )
    db.commit()
    return out
```

四点说明：

1. **`reviewed_at = datetime.now()` 不用 `func.now()`**：`func.now()` 是 SQL 表达式，
   写进属性后 `row.reviewed_at` 拿到的是表达式对象而不是 datetime，拿去组装出参会在
   pydantic 那里炸（或落成一个看不懂的值）。落库格式一致（`TIMESTAMP` 无时区）。
2. **`db.commit()` 在 service**，repo 不 commit。异常时无需显式 `rollback`——本接口只有
   一条 UPDATE，没有 `IntegrityError` 的产生路径（音频 id 已经手动校验过了，不靠 FK 报错）。
   `get_db()` 在 teardown 时只 `close()` 不 `rollback`，但脏数据没有 commit 就不会落库。
3. **`updated_at` 不存在**，所以没有「最后修改时间」可写——`reviewed_at` 是唯一的动作时间。
4. **`import` 增补**（已核对现状：本文件现在有 `from datetime import date,
   datetime`、`BusinessError`、`from app.repositories import homeworks_repo,
   user_repo`，schemas 那串里没有这两个新模型）：
   `homeworks_repo` 已在、`datetime` 已在、`BusinessError` 已在——**只需补两处**：
   `from app.repositories import audio_repo, homeworks_repo, user_repo`（加 `audio_repo`）
   与在 schemas 那串里加 `SubmissionReviewIn, SubmissionReviewResponse`。

---

## 5 验证方案

本项目没有测试框架（无 `tests/`、`requirements.txt` 里无 pytest）。验证靠
`/tmp/*.py` 脚本 + `curl` + `docker exec docker_postgres psql`。

### 5.1 起服务

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
.venv/bin/python app-d.py          # 8877
```

F6 不走 redis、不走 celery，**不需要 worker**。

### 5.2 取两个 session（教师 + 学生）

```bash
curl -s -c /tmp/f6/t.jar -X POST http://127.0.0.1:8877/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"teacher01","password":"xiyun@2026"}'
curl -s -c /tmp/f6/s.jar -X POST http://127.0.0.1:8877/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"stu001","password":"xiyun@2026"}'
```

### 5.3 逐条 curl（15 项）

| # | 请求 | 期望 |
|---|---|---|
| 1 | 无 Cookie POST `/api/submissions/24/review`，body `{}` | 401 `{"code":401,"message":"未登录"}` |
| 2 | 学生 Cookie，同上 | 403 `{"code":403,"message":"需要教师权限"}` |
| 3 | 教师 Cookie，`/api/submissions/99999/review` | 404 `{"code":404,"message":"提交不存在"}` |
| 4 | 教师 Cookie，`/api/submissions/abc/review` | 404 `{"code":404,"message":"接口不存在"}` |
| 5 | 教师 Cookie，`/api/submissions/-1/review` | 404 `接口不存在`（`\d+` 不收负号） |
| 6 | body `{"teacher_score": 101}` | 422 含 `终审评分必须在 0 到 100 之间` |
| 7 | body `{"teacher_score": -0.5}` | 422 同上 |
| 8 | body `{"teacher_score": 88.25}` | 200，`data.teacher_score == 88.25` |
| 9 | body `{"voice_comment_audio_id": 999999}` | 422 `语音点评音频不存在` |
| 10 | body `{"voice_comment_audio_id": 74}`（**真实存在的音频 id，见 §2.3**） | 200，`data.voice_comment_audio_id == 74` |
| 11 | body `{"teacher_score": "abc"}` | 422（**英文原文**，`float_parsing` 未映射，spec 3.7） |
| 12 | body 是 JSON 数组 `[1,2]` | 422（`_payload()` 返回 list，`model_validate` 报错） |
| 13 | 无 `Content-Type` 头，body 是 `{}` 文本 | **200 且等同空 body**——`silent=True` 把 `get_json()` 的 415 压成 None，兜成 `{}` 后就是「一键通过」 |
| 14 | body `{}`（一键通过） | 200，`status=="reviewed"`，`reviewed_at` 非空 |
| 15 | 同一 id 再 POST 一次 | 200，`reviewed_at` 比 #14 晚 |

### 5.4 PATCH 语义（3 项，必须用真数据核对）

拿 24 号（有 `teacher_score=75.2` + 评语）当靶子：

| # | 操作 | 期望 |
|---|---|---|
| 16 | 先 POST `{"teacher_score": 90}` → 再 `GET /api/submissions/24/detail` | `teacher_score==90`，**`teacher_comment` 仍是原文**，`status=="reviewed"` |
| 17 | 再 POST `{"teacher_comment": null}` → 再 F5 | `teacher_comment` 变 NULL，`teacher_score` 仍是 90 |
| 18 | 只 POST `{"voice_comment_text": "拖腔再稳一点"}` → 再 F5 | `voice_comment_text` 写入，前两项不动 |

### 5.5 副作用核对（F4 / F1 联动，2 项）

| # | 操作 | 期望 |
|---|---|---|
| 19 | 改前后各调一次 `GET /api/homeworks/12/submissions` | 条数从 **5** 减到 **4**（终审的那条离开待批列表） |
| 20 | 改前后各调一次 `GET /api/homeworks`，看 hw12 | `pending_review_count` 从 5 减到 4；**把 5 条全批完后 hw12 不再显示「批改中」**——这正是 DOC_ISSUES 第 25/34 条说的「等 F6 落地即自动恢复」，值得实测一次再复原 |

### 5.6 复原（必做，纪律同 DOC_ISSUES 第 35.5 条）

**动库前先按 id 抓一份 §2.3 那张表的逐列快照**，验完整列改回：

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -c "
UPDATE submissions SET
  teacher_score = CASE id WHEN 23 THEN 82.5 WHEN 24 THEN 75.2 ELSE NULL END,
  teacher_comment = CASE id WHEN 23 THEN '音准整体良好，拖腔处理有进步。建议在''雷''字拖腔时加强气息支撑，保持音高稳定。继续练习！'
                            WHEN 24 THEN '音准偏差较大，建议先进行单音模唱训练。' ELSE NULL END,
  voice_comment_audio_id = NULL,
  voice_comment_text = NULL,
  status = 'ai_scored',
  reviewed_at = NULL
WHERE id IN (23,24,25,26,27);"
```

**只按抓到的 id 改回，绝不 `DELETE FROM <表> WHERE <别的列>`、绝不整表清空。**
复原后重跑 §2.3 的三个派生量（`status` 分布、hw12 待批条数 = 5），与基线逐字对齐才算验完。

> 注意 `UPDATE ... WHERE id IN (...)` 里 `IN` 的这五个 id 是**本期真库的固定值**，不是
> 按条件筛出来的。若真库后来变了，以 §2.3 重新抓的快照为准。

---

## 6 明确不做

- 不动 `homework.html`（三个 alert 桩原样留着）。
- 不实现 F7、不写 `score_calibrations`。
- 不做草稿态、不做退回/撤销终审（§3.1、§3.9）。
- 不改 `schema.sql`、不加 `reviewer_id` 列、不加 CHECK 约束。
- 不改 `app/common/errors.py` 的 `_MSG_CN`（§3.7）。
- 不抽公共 `_payload()` 到 `app/common/`（§4.2）。
- 不校验教师归属（§3.6）、不校验音频归属（§3.8）。
- 不引入 pytest、不加分页、不新增 CSS/HTML。

---

## 7 要登记进 `DOC_ISSUES.md` 的

**新增第 38 条**（F6 终审批改落地），含六点：

1. **4.11「语音识别转文字」没有实现组件**：项目里没有任何 ASR
   （同第 20 条 / 第 439 行记的「要从音频得到汉字需要语音识别，而解析链路没有这一环」）。
   本接口的 `voice_comment_text` 只能当客户端给的普通字符串收下，服务端不转写、也不校验
   它与音频是否对得上。
2. **`submissions` 没有 `reviewer_id`，也没有任何指向 `users(id)` 的外键**：本接口无法
   记录「是谁批的」。终审这件事在库里只留下「被批过」与「什么时候」，没有「谁」。
   **这不是全项目的惯例，而是一处不对称**：同一批批改功能里的 `score_calibrations`
   就**有** `teacher_id`（真库那唯一一行是 `teacher_id=2`，见第 37 条）。也就是说
   「教师这个身份该不该落在批改结果上」这件事，同一个 DDL 里已经给了两种答案。
3. **`status` 没有 CHECK 约束，也没有枚举类型**：三个取值只活在 DDL 的行尾注释里。
   全文唯二的 `CHECK` 在 `users.role` 与 `annotations.tolerance` 上。
4. **「终审 = `status='reviewed'`」是本项目的推断**（承第 35 条 `:1089` 已记的同一推断）。
   F6 落地后这个推断第一次被执行，此后 `status` 变成 F4 列表与作业「批改中」两处判据的
   唯一输入。
5. **覆盖语义下 `reviewed_at` ≠ 首次终审时间**：已 `reviewed` 的再提交会刷新它。库里没有
   `updated_at`，也没有「首次终审时间」的第二列可存。
6. **没有教师归属模型**：`schema.sql` 里没有 `classes` 表，`students` 只有
   `user_id/level/avatar/enrolled_at`——任何教师都能批任何学生的任何提交。F6 与 F4/F5 一样
   不按教师过滤。

**另记两条本次自拟、需文档方确认的口径**：① `teacher_score` 限定 0–100（§3.7）；
② `voice_comment_audio_id` 不存在时回 **422** 而不是 404（§3.8）。

**更正第 25 条（`:622`）与第 34 条（`:1039`）的连带表现**：两处都写着「当前全项目没有任何
代码会把 `status` 写成 `reviewed`，所以作业恒为『批改中』，教师无从消除……等 F6 落地即自动
恢复」。**本日 F6 已落地**，该连带表现至此消失——按本文档体例**追加更新行、保留原判断**。

**更正 `submitted` 档的记载**：`submissions.status` 行尾注释列了
`submitted/ai_scored/reviewed`，但 `submitted` 全项目无人写（F3 仍是空桩）。本接口也不写。

---

## 8 待文档方确认

1. **4.11「语音识别转文字」由谁实现？** 服务端没有 ASR，本接口的 `voice_comment_text`
   只能由客户端给。若将来要服务端转写，本接口的入参形态要改（客户端就不用传文字了）。
2. **要不要加 `reviewer_id` 列？** 现在无法回答「这条是谁批的」。加列要改 `schema.sql`，
   且历史数据的该列只能为 NULL。
3. **4.8 终审分与 `ai_score` 是否该有相对约束？** 本接口只设 0–100 的绝对范围，不限制
   教师把 75.2 改成 10 或 100。若业务上要求「与 AI 分偏离超过 N 分必须填理由」，那是另一
   套校验。
4. **草稿态要不要做？** 前端有「💾 保存草稿」按钮，文档只定义终审。若要草稿，需要先定
   `status` 的取值与草稿是否进 F4 的待批列表。
5. **退回 / 撤销终审要不要做？** 现在终审后无法把一条改回待批改。要做的话需要新状态档与
   新的接口或参数。
6. **`status` 该不该加 CHECK 约束？** 现在三个取值只活在注释里，写错值不会报错。
7. **教师与学生的归属关系何时进库？** 在 `classes` 之类的表出现之前，任何教师都能批任何
   提交，接口层面无法收紧。
