# F7 `POST /api/submissions/<id>/calibration` 设计（教师 AI 评分校准）

> 本文一份覆盖三处改动：**后端 F7（写）**、**F5 出参增量（读）**、**`homework.html`
> 校准区块（显示）**。合成一份是因为三者共用同一个核心口径——「校准项取值集合」，
> 拆成三份文档会把这个口径各写一遍，改的时候必然漏一处。
>
> 本文**推翻**了 `2026-10-08-submission-detail-page-design.md` §6.1 里
> 「F5 不出校准——那是 F7 的读职责」的说法：F7 在清单里只有 POST，读职责没有落点。
> 那份文档要同步改。

## 1 背景、目标与非目标

### 1.1 目标

实现《5-接口清单》F7：教师对一条提交勾选「AI 评分偏差模式」，写 `score_calibrations`，
供系统学习该教师的评分偏好（功能 4.10「偏差模式勾选，数据回流」）。

落地后**全项目第一次有代码把 `score_calibrations` 写成非种子数据**。这张表从 V1.0 建库
起就存在，模型 `app/models/calibration.py` 也已映射，但 service / repo / schema / 路由
四层全是空的，`app/api/homeworks.py:78-82` 那个视图从建起就是 `return ok(id)`。

同时把读侧补上：F5 详情出参加一个 `calibration` 字段，页面 `homework.html` 的
「🎯 AI 评分校准」区块从空态（`renderDetailCalib` 现在恒出 `emptyBlock`）改成三选一
回显。此前该区块的注释写着「要显示得先等 F7 定下校准项的取值集合」——本次就是这个
取值集合。

### 1.2 非目标

- **不改 `schema.sql`、不加 DDL**（粒度选了「整体偏差模式」，与现有列一一对应，见 §3.1）。
- 不做按维度的校准（音准/气息/咬字）——现存表结构装不下，见 §2.5。
- 不做校准历史的保留与查询：`(submission_id, teacher_id)` 上做 upsert，**只留当前值**。
- 不做「数据回流」的消费方（谁读这张表去调模型）——本次只保证写得进去、读得出来。
- 不动 F6 的入参与落库（校准走独立接口，不塞进 `review` 的请求体，见 §3.9）。
- 不引入 pytest、不分页、不抽公共模块。

---

## 2 文档真源与现状

### 2.1 文档给了两行

《3-功能清单V1.0》模块 4 第 4.10 条，整行内容：

```
4.10 | AI 评分校准 | 偏差模式勾选，数据回流
```

《5-接口清单-V1.0》2.6 作业批改，F7 一行的全部内容：

```
F7 | POST /api/submissions/<id>/calibration | 教师 | 评分校准勾选（功能 4.10），写 score_calibrations
```

两行加起来没有规定：**有哪些可勾的项**、请求体长什么样、勾选与终审的先后关系、
重复提交是新增还是覆盖、怎么撤销、「数据回流」由谁触发。

### 2.2 与 F5 / F6 的关系

- **F6（`/review`）**：本次前端把校准**串在 F6 之后**发（§3.9）。后端两个接口彼此
  不感知——F7 不知道 F6 存不存在，只读 `submissions` 的当前值。
- **F5（`/detail`）**：本次给它加一个出参字段（§4.5）。F5 原本明确不出校准，理由记在
  `DOC_ISSUES` 第 37 条与 F5 的 spec 里；本次推翻，理由见本文头部。
- **F4（待批列表）**：不涉及。校准不是「待批」的判据。

### 2.3 真库基线（2026-10-08 写本设计时实测，验证阶段逐条对照）

```
users:                teacher01 = id 2 (王老师)   stu001 = id 3   李小燕 = id 50
submissions:          id 23 (hw12, stu 48, ai 82.5, teacher 82.5, reviewed)
                      id 24 (hw12, stu 50, ai 75.2, teacher 75.2, ai_scored)   ← 种子校准行指向它
                      id 25 (hw12, stu 53, ai 78.9, teacher NULL, ai_scored)
                      id 26 (hw12, stu 55, ai 71.3, teacher NULL, ai_scored)
                      id 27 (hw12, stu 52, ai 85.7, teacher 85.7, reviewed)
score_calibrations:   全表 1 行 ——
                      id=4, submission_id=24, teacher_id=2, bias_mode='high',
                      ai_score=75.2, teacher_score=75.2, created_at=2026-09-22 17:38:28.746872
```

### 2.4 库表事实（`schema.sql:157-165`，与真库 `\d` 一致）

```sql
CREATE TABLE score_calibrations (
  id SERIAL PRIMARY KEY,
  submission_id INT REFERENCES submissions(id),
  teacher_id INT REFERENCES users(id),
  bias_mode VARCHAR(10),                   -- high(偏高)/low(偏低)/ok
  ai_score FLOAT,
  teacher_score FLOAT,
  created_at TIMESTAMP DEFAULT NOW()
);
```

- 除 `id` 外**全部可空**，包括 `submission_id` 与 `teacher_id`。
- **索引只有主键**（`score_calibrations_pkey`），两个外键有 FK 约束但**没有唯一约束**，
  `(submission_id, teacher_id)` 上也没有。
- 模型 `app/models/calibration.py` 已完整映射，已注册进 `app/models/__init__.py`。

### 2.5 硬缺口（`DOC_ISSUES` 第 37 条，本次只能部分消解）

第 37 条记了两件事：

**其一：校准项没有取值集合。** 本次自拟为 `high/low/ok` 三值整体模式（§3.1）——依据是
DDL 注释里 `bias_mode` 的值域就是这三个词，且 4.10 用的词是「偏差**模式**」（单数）。
缺口本身仍在（文档没写），本次是自拟后登记。

**其二：表结构装不下「按维度勾三项」。** 页面早期的 mock（`SUBMISSIONS[].calib`）是
按维度勾「AI 音准评分偏高 / AI 气息评分偏高 / AI 咬字评分偏低」，一个提交多条。而表只有
一列 `bias_mode`、**没有维度列**，「音准偏高」+「气息偏高」同时勾选存不下。

**本次的处置：不扩表，改页面。** 页面改成三选一（§4.7），与表一一对应。第 37 条 ②
「若按维度，需要加维度列」这个分支**本次不选**——加了维度列就得分清「一个维度一行」，
`submission_id` 上还得补唯一约束（现在是零约束，同一教师对同一提交可插任意多行），
是一次会波及既有种子数据的 DDL 变更。留作文档方后续决定。

---

## 3 自拟口径

### 3.1 粒度：整体偏差模式（`high` / `low` / `ok`），零 DDL

一个提交一个教师**一行**，`bias_mode` 取 `high`（AI 偏高）/ `low`（AI 偏低）/ `ok`
（合适）。三值直接复用 DDL 注释里给 `bias_mode` 的值域，不新增列。

依据：4.10 的用词是「偏差**模式**」（单数）；页面上原有的提示语是「帮助系统学习**您的
评分偏好**」——偏好是教师整体的松紧倾向，不是某一维度；DDL 注释也已把这三个词写死。

代价：页面现在要按维度勾三项的设计作废，改成三选一。

### 3.2 请求体只带 `bias_mode`，分数由服务端取

```
{"bias_mode": "high"}        # high / low / ok
{"bias_mode": null}           # 撤销（见 §3.4）
```

`ai_score` 取 `submissions.ai_score`，`teacher_score` 取 `submissions.teacher_score`，
`teacher_id` 取当前登录用户（路由从 session 读出后作为参数传进 service，见 §4.3）。
**三者都不由客户端传。**

理由：这三列是「留证据」用的（AI 给了几分、老师给了几分、偏差是什么），客户端传就可能
与库里不一致；而三者服务端都拿得到，没有传的必要。

### 3.3 upsert：按 `(submission_id, teacher_id)` 先查后写

因为 §2.4 的表上**没有唯一约束**，只能在应用层做：

1. 查 `(submission_id, teacher_id)` 有没有行
2. 有 → 更新 `bias_mode` / `ai_score` / `teacher_score`，并把 `created_at` 刷到本次
3. 无 → 插入一行

`created_at` 刷新是必须的：F5 的读侧取「最新一条」（§3.6），不刷新的话「最新」就锁定在
第一次勾选的时间上，后续改值不会改变排序，多行的历史数据会读出旧值。

**已知残余风险**：应用层 upsert 在并发下可能插重（两个请求同时查不到、同时插）。本项目
没有并发场景（教师单人操作），本次不为此加唯一约束——加了就是 DDL 变更，与 §1.2 冲突。
登记进 `DOC_ISSUES`（§7）。

### 3.4 显式 `null` = 删除该行（撤销校准）

`{"bias_mode": null}` 时**删掉** `(submission_id, teacher_id)` 那一行，而不是写一行
`bias_mode IS NULL`。

理由：`bias_mode` 可空，写一行 null 会留下一条无意义的记录，且 F5 读侧「取最新一条」
会读到它、把有值的旧行盖掉。删除后读侧回到「没校准过」的 `null`，语义干净。

这是本项目**第一个删除语义的写接口**。触发条件与 F6 的「显式 `null` = 清空」同源——
都是「显式给出的 null」而非「字段缺省」。但 F7 **不需要** `model_fields_set`：它只有
一个字段且该字段必填，缺省会先被 pydantic 判 400，所以 `bias_mode` 拿到 `None` 只可能
是显式传的。落点也不同：F6 是清空列值，F7 是删除行。

前端**不发** `null`（§3.9）：教师在三个 radio 上只能选一个，没有「取消选择」的交互。
`null` 只对直接调接口的调用方有意义。

### 3.5 不限制 `submission.status`

可以对任何状态的提交写校准，不要求 `status = 'reviewed'`。

理由：表结构上没有状态耦合，文档也没把两者绑起来。正常路径下前端总是在 F6 之后调用
（那时已是 `reviewed`），但接口本身不该依赖调用顺序。对一条 `ai_scored` 的提交写校准，
`teacher_score` 会取到 `NULL`（该列还没被 F6 写过）——这是调用方自己的选择，服务端不拦。

### 3.6 F5 的 `calibration` 取「最新一条」

一个提交可能有多行（历史数据、多个教师、或 §3.3 的并发漏网），F5 出参只出一个对象，
取 `created_at DESC, id DESC LIMIT 1`。`id` 做第二排序键是为了 `created_at` 相同时
（同一秒内的两次写）结果稳定。

### 3.7 权限：教师即可，不校验归属

`@login_required` + `@teacher_required`。不检查该教师是否「负责」这个学生或这份作业——
本项目没有「教师-班级」归属表，F6 也是同一口径（F6 spec §3.6）。

### 3.8 错误码

沿用 `DOC_ISSUES` 第 9 条：`code` 与 HTTP 状态码一致。

| 情形 | 状态码 | message |
|---|---|---|
| 未登录 | 401 | （走既有 `login_required`） |
| 已登录但非教师 | 403 | （走既有 `teacher_required`） |
| 提交不存在 | 404 | `提交不存在` |
| `bias_mode` 非三值之一 | 400 | pydantic 校验信息（`Literal` 不给过） |
| `bias_mode` 键缺失 | 400 | pydantic「字段必填」 |

`bias_mode: null` 是合法输入（撤销），**不是** 400。

### 3.9 前端：随终审提交，F7 失败不回滚终审

`submitReview()` 里 F6 返回成功后才发 F7，串行：

```
F6 成功 → 读当前选中的 radio → 有值才发 F7
F6 失败 → 不发 F7，走既有「终审发布失败」提示
F6 成功、F7 失败 → 提示「终审已保存，校准未保存」，不回滚、不重发
```

选「串行、F6 先」的理由：`teacher_score` 由 F7 从 `submissions` 读，而那一列正是 F6 刚
写的——F7 必须先于它发就没值可读（结果是一个 `teacher_score = NULL` 的校准行，「偏差
对比」失去意义）。

「不回滚」的理由：F6 已经落库并且列表已经刷新，这时报「发布失败」是在说谎；教师会重复
点击，而 F6 是覆盖语义（重复点不产生第二条），但会白刷一次 `reviewed_at`。

**没选任何一项时 F7 不发**——不制造 §3.4 的删除。

### 3.10 「数据回流」没有消费方

4.10 的「数据回流」在代码里没有任何落点：没有定时任务、没有训练脚本、没有任何地方读
`score_calibrations`。本次只保证写得进、读得出。这不是本次的欠账，是需求侧缺一环
（第 37 条 ③ 已记，本次维持）。

---

## 4 实现设计

### 4.1 分层与落点

| 层 | 文件 | 改动 |
|---|---|---|
| 路由 | `app/api/homeworks.py` | `submissions_calibration` 的桩体换成真实现 |
| 入参/出参 | `app/schemas/homework.py` | 新增 `SubmissionCalibrationIn` / `SubmissionCalibration`；`SubmissionDetailResponse` 加一个字段 |
| repo | `app/repositories/homeworks_repo.py` | 新增两个查询 + 一个插入 |
| service | `app/services/homework_service.py` | 新增 `calibrate_submission`；`submission_detail` 装配新字段 |
| 前端 | `homework.html` | 校准区块 markup + CSS + `renderDetailCalib` + `submitReview` |

F7 的路由与 F6 同在 `homeworks.py`（两个接口操作同一个资源 `submissions`，且都是教师侧
批改动作），不新开文件。

### 4.2 repo（`app/repositories/homeworks_repo.py`）

```python
def get_calibration(
    db: Session, submission_id: int, teacher_id: int
) -> ScoreCalibration | None:
    """取某教师对某提交的校准行，没有返回 None。供 F7 判「更新还是插入」。"""
    return db.scalar(
        select(ScoreCalibration).where(
            ScoreCalibration.submission_id == submission_id,
            ScoreCalibration.teacher_id == teacher_id,
        )
    )


def get_latest_calibration(
    db: Session, submission_id: int
) -> ScoreCalibration | None:
    """取某提交最新的一条校准行，没有返回 None。供 F5 出参。

    为什么是「最新一条」而不是「唯一一条」：本表在
    (submission_id, teacher_id) 上没有唯一约束（spec 2.4），历史数据与并发下都可能
    有多行。id 做第二排序键是为了 created_at 相同时结果稳定（spec 3.6）。
    """
    return db.scalar(
        select(ScoreCalibration)
        .where(ScoreCalibration.submission_id == submission_id)
        .order_by(ScoreCalibration.created_at.desc(), ScoreCalibration.id.desc())
        .limit(1)
    )


def add_calibration(db: Session, row: ScoreCalibration) -> None:
    """插入一行校准记录。不 flush（本次不需要自增 id），commit 交给 service。"""
    db.add(row)
```

更新路径**复用既有的 `apply_review(db, row, changes)`**（`:194`）。它的名字带 `review`
但实现是通用的「把 changes 里的列写到 row 上」；它自己的文档字符串也说了「本函数不做
缺省 vs 显式 null 的区分，给什么写什么」。不在本次为它改名——改名会波及 F6，与 §1.2 冲突。

`ScoreCalibration` 需加进 `homeworks_repo.py` 的 import（现在只 import 了作业域那几个模型）。

### 4.3 service（`app/services/homework_service.py`）

```python
def calibrate_submission(
    db: Session, submission_id: int, data: SubmissionCalibrationIn, teacher_id: int
) -> SubmissionCalibration | None:
    """F7 教师 AI 评分校准（功能 4.10）。

    提交不存在抛 404。按 (submission_id, teacher_id) upsert：有则更新并刷新
    created_at，无则插入（spec 3.3）。bias_mode 显式给 null = 删除该行（spec 3.4）。

    ai_score / teacher_score 从 submissions 读，teacher_id 由调用方传入
    （路由用 `current_user_id()` 取）——三者都不由客户端传（spec 3.2）。

    **本函数不碰 flask.session**：`app/api/auth.py` 的模块文档把「session 的读写只
    在认证文件发生」列为不变量，为的是 service 层能脱离请求上下文测试。既有先例是
    `demos_segments_annotations.py:114` 的 `teacher_id=current_user_id()`。
    """
    sub = homeworks_repo.get_submission(db, submission_id)
    if sub is None:
        raise BusinessError(404, "提交不存在")

    row = homeworks_repo.get_calibration(db, submission_id, teacher_id)

    if data.bias_mode is None:
        # 撤销：删行而不是写一行 null（spec 3.4）。
        if row is not None:
            db.delete(row)
            db.commit()
        return None

    if row is None:
        row = ScoreCalibration(submission_id=submission_id, teacher_id=teacher_id)
        homeworks_repo.add_calibration(db, row)

    homeworks_repo.apply_review(db, row, {
        "bias_mode": data.bias_mode,
        "ai_score": sub.ai_score,
        "teacher_score": sub.teacher_score,
    })
    # 刷新到本次，否则 F5 的「取最新一条」永远排到第一次勾选（spec 3.3）。
    # 不用 func.now()：赋进属性后拿到的是表达式对象而不是 datetime，
    # 拿去装出参会炸。同 F6 对 reviewed_at 的处理。
    row.created_at = datetime.now()

    # 出参在 commit 之前组装：commit 会让 ORM 实例属性过期，之后再读会多发
    # 一条 SELECT 把整行拉回来。同 F6。
    out = SubmissionCalibration(
        bias_mode=row.bias_mode,
        ai_score=row.ai_score,
        teacher_score=row.teacher_score,
        created_at=row.created_at,
    )
    db.commit()
    return out
```

`submission_detail`（`:315`）追加一行装配：

```python
        calibration=_calibration_of(db, sub),
```

新增私有函数 `_calibration_of(db, sub) -> SubmissionCalibration | None`：查
`homeworks_repo.get_latest_calibration(db, sub.id)`，没有则返回 `None`，有则转成出参
对象。它对一个提交只发一条 SQL，是 `submission_detail` 里除主键 join 之外的第二条查询
——这个提交下没有校准行时是一次空扫，成本可忽略。

（`sub` 已经在 `submission_detail` 的解包元组里，`sub.id` 直接可用，不需要额外查询。）

### 4.4 入参模型（`app/schemas/homework.py`）

```python
class SubmissionCalibrationIn(BaseModel):
    """F7 入参。只有一项——分数与教师由服务端取（spec 3.2）。

    bias_mode 显式给 null = 撤销该校准（spec 3.4），所以类型要容纳 None，
    且**不能**用 `= None` 当默认值来表达「可空」——那会让字段缺省也变成合法，
    而缺省该报「字段必填」（spec 4.4 开头）。
    """

    bias_mode: Literal["high", "low", "ok"] | None
```

注意用的是**无默认值**的 `bias_mode: ... | None`：字段不出现时 pydantic 报「字段必填」
（400），显式传 `null` 才得到 `None`。这与 F6 四个字段的写法不同（那边四个都是
`= None`，缺省合法），因为 F7 只有一个字段、没有「只改其中一项」的场景。

### 4.5 出参模型（`app/schemas/homework.py`）

```python
class SubmissionCalibration(BaseModel):
    """一条校准记录。F7 的响应体与 F5 详情里的 `calibration` 字段同构，共用本类。"""

    bias_mode: str
    ai_score: float | None
    teacher_score: float | None
    created_at: datetime
```

`SubmissionDetailResponse`（`:209`）新增一个字段：

```python
    calibration: SubmissionCalibration | None   # 功能 4.10；没校准过是 None，不是空对象
```

放在 `reviewed_at` 之后（紧跟 F6 那一批「批改现状」字段，校准是同一屏的下一块）。该类
的文档字符串要同步补一句：原写着「批改现状那六个字段是 F6 写入的列」，`calibration` 是
第七个、且来自另一张表。

**序列化**：`created_at` 是 datetime，F5 与 F7 的路由**都已经**在用
`.model_dump(mode="json")`，出的是 ISO-8601，无需额外处理。

### 4.6 路由（`app/api/homeworks.py`）

```python
@api_bp.route("/submissions/<int:submission_id>/calibration", methods=["POST"])
@login_required
@teacher_required
def submissions_calibration(submission_id):
    data = SubmissionCalibrationIn.model_validate(_payload())
    out = homework_service.calibrate_submission(
        get_db(), submission_id, data, teacher_id=current_user_id())
    # 撤销（bias_mode = null）时 out 是 None，None.model_dump() 会炸，所以这里判空。
    return ok(out.model_dump(mode="json") if out else None)
```

四处与既有写法保持一致：

- 路径用 `<int:submission_id>` 而不是那行桩原来的 `<id>`：`<id>` 是字符串转换器，
  `/submissions/abc/calibration` 也会匹配进来再进视图查库；`<int:...>` 让 Werkzeug 在
  路由层挡掉，走 `errors.py` 的统一 404。**这是本次对那行桩的一处修正**。
- `teacher_id=current_user_id()`：session 只在路由层读，service 不碰（见 §4.3）。需要
  在 `homeworks.py` 的 `from app.common.decorators import ...` 里补上 `current_user_id`。
- `_payload()` 复用本文件既有的那个（`:11`），不新写第四份。
- `mode="json"`：出参里有 `created_at`（datetime）。`ok()` 里若拿到裸 datetime 会被
  Flask 按 RFC-822 序列化。

### 4.7 前端（`homework.html`）

**① 区块 markup（`:577` 的 `<div class="calib-grid" id="calibGrid"></div>` 不动）**，
由 JS 渲染三项，不写死在 HTML 里。

**② CSS（`:397`）**：`.calib-item input[type="checkbox"]` 的选择器扩成同时命中 radio：

```css
.calib-item input[type="checkbox"],
.calib-item input[type="radio"]{width:16px;height:16px;accent-color:var(--primary)}
```

**③ `renderDetailCalib(d)`（`:997-1000`）** 从恒出空态改成渲染三个 radio：

```js
// 功能 4.10：取值集合由 F7 定为 high/low/ok（spec 3.1），与 score_calibrations
// 的 bias_mode 一一对应。d.calibration 为 null = 没校准过 → 三个都不选。
const CALIB_OPTIONS = [
  { value: "high", label: "AI 评分偏高" },
  { value: "low",  label: "AI 评分偏低" },
  { value: "ok",   label: "AI 评分合适" },
];
```

每个 radio 用 `name="calibBias"` 成组（三选一的机制），`value` 取三值，
`checked` 由 `d.calibration?.bias_mode` 决定。区块上方那句提示文案
（`:576`「勾选 AI 评分偏差模式…」）改成单选措辞。

**④ `submitReview()`（`:1168`）**：在 F6 成功的那条分支里、刷新列表**之前**插入 F7 调用：

```js
const bias = document.querySelector('input[name="calibBias"]:checked')?.value;
if (bias) {
  try {
    const r2 = await fetch(`${API_BASE}/api/submissions/${id}/calibration`, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bias_mode: bias }),
    });
    if (!r2.ok) throw new Error(String(r2.status));
  } catch (e) {
    alert("⚠️ 终审已保存，但校准未保存");   // 不回滚、不重发（spec 3.9）
  }
}
```

401 沿用本页既有处理（跳登录页）。F7 的 403/404 在当前链路下不会出现（教师已登录、
id 来自刚成功的 F6），不单独分支。

**⑤ `renderDetailCalib` 的调用点**：保持不变（`renderDetail` 里那一处），因为校准值随
F5 详情一起回来。

---

## 5 验证方案

无测试框架（项目约束：不引入 pytest）。用 `/tmp` 脚本 + 真后端 + curl + psql。

### 5.1 起服务

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
source .venv/bin/activate
python app-d.py            # 8877；F7 不需要 celery worker
```

### 5.2 取两个 session

登录 `teacher01` 与 `stu001`（初始密码 `xiyun@2026`），各存一份 cookie jar 到
`/tmp/f7fe/`。学生那份只用于 403 用例。

### 5.3 curl 清单（后端）

| # | 请求 | 期望 |
|---|---|---|
| 1 | 教师 POST submission 25 `{"bias_mode":"high"}` | 200，`data.bias_mode="high"`，`ai_score=78.9`，`teacher_score` 为 null |
| 2 | 同一请求重发一次 | 200，**表里仍只有一行**（upsert 命中，不是新增） |
| 3 | 教师 POST submission 25 `{"bias_mode":"low"}` | 200，`bias_mode="low"`，`created_at` 已刷新 |
| 4 | 教师 POST submission 25 `{"bias_mode":null}` | 200，`data=null`，表里那一行**消失** |
| 5 | 教师 POST submission 24 `{"bias_mode":"ok"}` | 200，**命中种子行 id=4**（表总行数不变） |
| 6 | 学生 POST submission 25 `{"bias_mode":"high"}` | 403 |
| 7 | 未登录 POST | 401 |
| 8 | 教师 POST submission 99999 | 404 `提交不存在` |
| 9 | 教师 POST submission 25 `{"bias_mode":"x"}` | 400 |
| 10 | 教师 POST submission 25 `{}` | 400（字段必填） |
| 11 | 教师 POST `/api/submissions/abc/calibration` | 404（`<int:>` 在路由层挡掉） |
| 12 | 教师 GET F5 详情（submission 24） | `data.calibration` 非 null，`bias_mode` 与库一致 |
| 13 | 教师 GET F5 详情（submission 25，用例 4 之后） | `data.calibration` 为 `null` |

### 5.4 真数据库核对

每步之后用 psql 查 `score_calibrations` 全表（`select * from score_calibrations order by id`），
确认「重发不新增」「撤销真删行」「种子行被更新而非新增」。

### 5.5 前端

起后端后用 `/browse`（本项目规定：网页浏览一律用该技能，不用 chrome MCP）走一遍：
登录 teacher01 → 打开 homework.html → 选一条待批提交 → 点一个校准 radio →
点「✅ 通过并发布」→ 确认两件事：库里出现/更新了校准行；重新打开该提交时 radio 回显正确。

用 `/tmp/f7fe/` 下的 patch 脚本把 `alert` 改成记录（同 F6 那一轮的做法），否则原生弹窗会
卡住页面。

### 5.6 复原（必做）

本轮只在 **submission 25 / 26** 上造数据（它们没有校准行，撤销用例会删干净）。若碰到
**submission 24 的种子行 id=4**，必须先把原值抓下来：

```
id=4, submission_id=24, teacher_id=2, bias_mode='high', ai_score=75.2, teacher_score=75.2,
created_at=2026-09-22 17:38:28.746872
```

验证完按 **id=4** 改回（`UPDATE ... WHERE id = 4`）。**绝不 `DELETE FROM score_calibrations
WHERE ...` 别的列、绝不整表清空**（项目纪律，同 `DOC_ISSUES` 第 35.5 条）。

---

## 6 明确不做

- 不改 `schema.sql` / 模型 / `check_db.py` 基线（零 DDL）。
- 不做按维度的校准、不加维度列、不加唯一约束。
- 不保留校准历史（upsert 只留当前值）。
- 不做「数据回流」的消费方。
- 不改 F6 的入参、路由、落库。
- 不动 `app/common/errors.py` 的 `_MSG_CN`。
- 不修 `homework.html` 里其它空态区块（四维分、逐字偏差——那些是数据源缺失，不是本次范围）。
- 不做「布置新作业」（F2）与语音点评（4.11）。

---

## 7 要登记进 `DOC_ISSUES.md` 的

第 37 条要**改写**（它现在的「当前处理：F5 不出校准」与本文冲突），并补以下几点：

1. **校准项取值集合**：本次自拟 `high/low/ok`（依据 DDL 注释），文档仍无定义。
2. **`(submission_id, teacher_id)` 无唯一约束**：靠应用层 upsert，并发下可插重。
   本次确认**不加约束**（零 DDL），登记为已知缺口。
3. **撤销语义**：显式 `null` = 删除该行。文档未定义。
4. **F5 出参新增 `calibration` 字段**：推翻第 37 条与 F5 spec §6.1 里「F5 不出校准」。
   取值口径为「最新一条」（`created_at DESC, id DESC`），文档未定义多行时的取法。
5. **不限制 `submission.status`**：可对未终审的提交写校准，此时 `teacher_score` 为 null。
6. **「数据回流」无消费方**（第 37 条 ③ 维持）。
7. **前端口径**：校准随终审串行提交、F7 失败不回滚终审、未选不发（三条都不在文档里）。

---

## 8 待文档方确认

1. 校准项到底是三项整体偏差（本文自拟）还是按维度？若按维度，`score_calibrations`
   要加维度列 + `(submission_id, teacher_id, 维度)` 唯一约束，是一次 DDL 变更。
2. 「偏差模式」要不要保留历史？本文 upsert 只留当前值；若要留，表结构要改（现在没有
   「当前/历史」的区分列）。
3. 4.10 的「数据回流」由谁消费这张表、什么时候消费？今天没有任何代码读它。
4. 校准该不该与终审绑定（只有 `reviewed` 之后才能勾）？本文不限制。
5. 学生的校准结果要不要可见？（本文只在教师端批改页回显，F5 是教师接口。）
