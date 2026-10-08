# F5 `GET /api/submissions/<id>/detail` 设计（批改详情）

日期：2026-10-08
文档真源：《5-接口清单-V1.0》F5、《3-功能清单V1.0》4.4–4.7、《6-登录与数据隔离方案-V1.0》
代码：`app/api/homeworks.py` / `app/services/homework_service.py` / `app/repositories/homeworks_repo.py` / `app/schemas/homework.py`
DOC_ISSUES：本次新增第 36 条；另更正 §34.3 结尾的错误判断

---

## 1 背景、目标与非目标

### 1.1 目标

实现 F5 `GET /api/submissions/<id>/detail`——教师批改一份作业提交时的详情接口，交付《3-功能清单》模块 4 的四块内容：

| 编号 | 功能点 | 文档说明 |
|---|---|---|
| 4.4 | 歌词级偏差对比 | 逐字音分偏差 |
| 4.5 | 多维加权融合评分 | 40/30/20/10 加权 |
| 4.6 | CDM 归因诊断标签 | 规则引擎+置信度 |
| 4.7 | BKT 状态更新对比 | P(L) 前后变化 |

### 1.2 非目标

- **不改前端。** `homework.html` 右侧批改面板仍是 mock（F4 前端接入时的既定范围，见 `2026-10-08-homework-submissions-page-design.md` §3.3）。
- **不实现 F6（终审）/ F7（校准）。** 相关桩维持 `return ok(id)`。（2026-10-08 说明：F6 与 F7 后来各自实现；F7 落地时**撤销了本文下面「校准现状不出」那条**——见 §3.9 末尾的更新。）
- **不补数据源。** 不写 `ai_detail`、不改种子数据、不实现 F3（学生提交作业）。见 §3.1——4.4 与 4.5 在本次交付里是**空位**，这是本次最重要的一个事实。
- **不做多提交聚合、不分页、不截断。**
- **不引入 pytest。** 本仓库无测试框架，验证靠 `/tmp` 临时脚本 + curl + psql（既有做法）。
- **不新增 CSS / HTML。**

---

## 2 文档真源与现状

### 2.1 文档给了一行

《5-接口清单》2.6 作业表：

```
F5 | GET /api/submissions/<id>/detail | 教师 | 歌词级偏差对比 + 加权评分 + CDM 标签 + BKT 前后对比（功能 4.4-4.7）
```

**没有字段契约、没有示例、没有错误码。** 《2-系统设计说明》里没有「批改详情」一节；《1-PRD》只有一句「多维加权融合评分 — 音准40%/节奏30%/气息20%/咬字10% 加权计算」（PRD 第 204 行），**没有任何映射定义**。三个关键 JSON 契约（《5-接口清单》第 3 节）里也没有它。

所以本接口的字段面**全部是自拟的**，逐条记在 §3。

### 2.2 与 F4 的关系

F4（`GET /api/homeworks/<id>/submissions`）与本接口是同一份数据的两种投影——列表给「批谁」，详情给「怎么批」。两处必须对齐的地方：

1. **`severity` 一律透传语义值**（F4 spec §3.11），不映射 CSS 类。
2. **学生字段平铺**，不做嵌套对象（F4 spec §3.9）。
3. **姓名必须经 `students.user_id` 拐一次取**（`users.display_name`），不能拿 `student_id` 当 `users.id` 用——DOC_ISSUES 第 21 条，直接当 users.id 会静默取到另一个人的名字。
4. `model_dump(mode="json")`——出参里有 `datetime`。

**一处刻意不同**：F4 的 `tags` 只取 `confidence > 0.7`，F5 的 `cdm_tags` **取全量**。理由见 §3.2。

### 2.3 真库基线（验证时逐条对照）

`submissions` 共 5 行，全属 hw12《穆桂英挂帅》· 辕门外三声炮：

| id | 学生 | student_id | level | avatar | ai_score | teacher_score | status | teacher_comment | audio_id | reviewed_at |
|---|---|---|---|---|---|---|---|---|---|---|
| 23 | 李小燕 | 48 | 初学 | 🎭 | 82.5 | 82.5 | ai_scored | 有 | NULL | NULL |
| 24 | 刘思琪 | 50 | 初学 | 🎵 | 75.2 | 75.2 | ai_scored | 有 | NULL | NULL |
| 25 | 周明轩 | 53 | 初学 | 🎹 | 78.9 | NULL | ai_scored | NULL | NULL | NULL |
| 26 | 孙志远 | 55 | 初学 | 🥁 | 71.3 | NULL | ai_scored | NULL | NULL | NULL |
| 27 | 赵雨桐 | 52 | 进阶 | 🎼 | 85.7 | NULL | ai_scored | NULL | NULL | NULL |

**`ai_detail` 只有三个键**（5 行一致）：`defects` / `featureMatrix` / `overallConfidence`。

`defects[]`（已按 confidence 降序排）：

| id | label | status | confidence |
|---|---|---|---|
| 23 | 气息支撑不足 | high | 0.82 |
| 23 | 拖腔时值偏短 | high | 0.78 |
| 23 | 归韵口型保持不足 | low | **0.45** |
| 24 | 音准偏差随机 | high | 0.85 |
| 24 | 听辨能力弱 | high | 0.76 |
| 24 | 拖腔不足 | medium | 0.71 |
| 24 | 气息支撑不足 | medium | **0.52** |
| 25 | 节奏感知弱 | high | 0.80 |
| 25 | 气息不稳定 | high | 0.74 |
| 26 | 整体音准偏低 | high | 0.88 |
| 26 | 调门不准 | high | 0.82 |
| 26 | 声带紧张 | medium | **0.65** |
| 27 | 收尾偏急 | medium | 0.72 |

加粗的三条 `confidence ≤ 0.7`，**F4 会把它们滤掉，F5 必须出**。条数对照：23→3（F4 出 2）、24→4（F4 出 3）、25→2（F4 出 2）、26→3（F4 出 2）、27→1（F4 出 1）。

`featureMatrix` 9 个键（5 行一致）：`pitchStd` / `energyStd` / `pitchMean` / `pitchTrend` / `lowPitchBias` / `vibratoDepth` / `highPitchBias` / `rhythmAccuracy` / `durationMeanDiff`。
`overallConfidence`：23→0.72、24→0.68、25→0.75、26→0.81、27→0.55。

`bkt_before` / `bkt_after`（扁平字典「技法名 → P(L)」）：

| id | before | after |
|---|---|---|
| 23 | `{拖腔:0.28, 气息支撑:0.51, 音准控制:0.72}` | `{拖腔:0.28, 气息支撑:0.53, 音准控制:0.74}` |
| 24 | `{气息支撑:0.42, 音准控制:0.48}` | `{气息支撑:0.40, 音准控制:0.46}` |
| 25/26/27 | **NULL** | **NULL** |

### 2.4 前端 mock 与真库的对应关系（本次查明）

`homework.html` 的 `SUBMISSIONS[0]`（李小燕）**就是 submission 23**，`SUBMISSIONS[1]`（刘思琪）**就是 submission 24**——`ai_score`（82.5 / 75.2）、`bkt`（3 个技法 0.72/0.51/0.28、2 个技法 0.48/0.42）、`teacher_comment`（逐字相同）全部对得上。

**mock 只在四块上凭空编造**：`dimensions`、`fusion`、`lyrics`、`calib`。其余都是从真行里抄的。这也解释了为什么 4.4/4.5 在库里查不到——它们从来只存在于 mock。

### 2.5 两个硬缺口

1. **4.4 无处可查。** `submissions` 没有逐字列，`ai_detail` 没有 `lyrics`/`words` 键。而 `schema.sql:127` 的列注释写的是「逐字偏差 + CDM 归因标签」——**列注释与真数据不符**。B 组分析确实算得出逐字偏差（`analyze_service._words()`），但它只活在 redis 任务结果里（TTL 1 小时），且要求 `segments.lyrics_json` 当输入，而解析产出的段落该列恒为 NULL（DOC_ISSUES 第 20 条，没有 ASR）。这 5 条提交的 `audio_id` **全是 NULL**，等于连分析链路都没挂上。
2. **4.5 无处可查。** `featureMatrix` 是 9 个**原始声学量**，不是四个维度分。40/30/20/10 这套权重只出现在《3-功能清单》一行与前端 mock 的硬编码里，**没有任何映射定义**；而且 9 个特征里 5 个属音准、2 个属气息、2 个属节奏，**没有对应「咬字」的量**——四维里的咬字维度拿不到任何输入。

补充：`ai_detail` 是**手搓种子数据**（来源 `/tmp/seed_cdm_report.sql`，DOC_ISSUES 第 24 条），不是分析管线产物。

### 2.6 待修的错桩

`app/api/homeworks.py:39`：

```python
@api_bp.route("/homeworks/<id>/detail", methods=["GET"])   # ← 文档里没有这条路径
@login_required
@teacher_required
def homeworks_detail(id):
    return ok(id)
```

**地址错了。** 文档里 F5 是 `/submissions/<id>/detail`。DOC_ISSUES §34.3 结尾断言「F3–F7 的另外 5 个桩地址正确」，**那句话本身不成立**——这一个就是错的，要在本次一并更正。

---

## 3 自拟口径

以下都是文档未定义、由本次实现定死的。逐条对应 §7 的 DOC_ISSUES 登记。

### 3.1 4.4 / 4.5 无数据源，出空位而不自造算法

已确认的取舍：**纯透传**——库里有什么出什么。因此：

- `lyrics` 出 `[]`（§3.5）
- `dimensions` 出 `null`（§3.6）

**不自造映射。** 把 9 个声学特征折成四个维度分意味着替文档定义算法，而该算法既无依据也无从验证（咬字维度更是无输入）。一个诚实的空位比一个编出来的分数好——教师看到 `null` 知道「这块还没数据」，看到 62 分却会当真。

### 3.2 4.6 CDM：取**全量** defects，不套 F4 的 0.7 阈值

F4 的 `tags` 只取 `confidence > 0.7`，那条阈值的依据是**待批卡片自己的文案**（F4 spec §3.5）。F5 是教师做判断的地方，口径必须与卡片不同：

- 卡片是「快速扫一眼批谁」，标签少而准；
- 批改页是「逐条判断 AI 对不对」，**低置信度的标签恰恰是最该被教师质疑、因而最该被看见的那一条**。

真库里有三条会被 0.7 滤掉：23 的 0.45「归韵口型保持不足」、24 的 0.52「气息支撑不足」、26 的 0.65「声带紧张」。把它们藏起来，等于教师永远不知道 AI 曾经这样判断过，也就永远无法通过 F7 校准去纠偏——那正是 4.10「数据回流」的前提。

**不截断条数**（同 F4 §3.6）。

### 3.3 `severity` 透传语义值

`severity` = `defects[].status` 原文（`high`/`medium`/`low`），**不是** CSS 类名（`.cdm-item.high` 之类）。同 F4 spec §3.11：出表现层词汇等于把「这个页面用这套配色」写进接口契约。取不到就给 `"unknown"`，前端按中性色渲染；**不做白名单过滤**，滤掉一个未预期的分级会让标签凭空消失。

### 3.4 CDM 的字段面

`{id, label, severity, confidence, category, evidence, features}` 全出。

`category` / `evidence` / `features` 是 AI 侧写入、F4 **刻意不出**的字段——F4 spec 第 1090 行已声明「同为 AI 写入的 `category`/`evidence`/`features` 是批改详情页（F5）的内容，不属于列表卡片」。本接口就是来收这三样的。

`id`（如 `"d1"`）一并透传：它是 `defects[]` 元素自身的标识，将来的 CDM 逐条确认/驳回需要它定位，凭空丢弃不划算。

### 3.5 4.4 `lyrics` 出 `[]`，但元素契约现在就定死

元素契约**对齐 B 组 `words[]` 的子集**（`analyze_service._words` 的产出）：

```
{ "index": int, "word": str|null, "start": float|null, "end": float|null,
  "deviation_cents": float|null, "warning": bool|null }
```

理由与 §2.2 的第 1 条同源：**同一份逐字偏差在 B4 与 F5 两条接口上形状必须一致**。将来 F3 把 B 组结果落进 `ai_detail` 时，本接口直接读同一批键，不再做一次翻译。

字段名用 **`word`**（B 组的名），不用 mock 的 `char`。

**不着色、不出 `st`**：`excellent`/`good`/`fair`/`punct` 是展示层词汇，《5-接口清单》3.2 的原文就是「着色规则在**前端**按 `regions.level` 渲染」。后端只出 `deviation_cents` 与 `warning`（B 组已按红黄阈值算好）。

B 组 `words[]` 的另外三个字段 `teacher_freq` / `student_freq` / `octave_fixed` 本次**不出**——它们服务于音准曲线对比图，不是「歌词级偏差对比」的最小集；将来要加是非破坏性变更。

### 3.6 4.5 `dimensions` 出 `null`，**不出 `fusion` 键**

`dimensions: null` 是**显式空位**，不是省略键：「这块还没数据」与「后端没实现这个字段」对前端是两回事。

`fusion` 键**整个不出**。前端 mock 的 `fusion.total`（0.72）按 40/30/20/10 加权它自己的 `dimensions`（`{pitch:84, rhythm:84, breath:86, articulation:80}`）算出来是 **0.84**，两个数对不上；真实语义文档里从未定义。凭空造一个 `fusion` 只会把 mock 的错误固化进契约。总分由 `ai_score` 承担——它本来就是融合后的结果。

40/30/20/10 这套权重**不进接口**：没有任何数据能与它相乘，出参里带一组悬空的权重只会让人以为 `dimensions` 本该有值。

### 3.7 `feature_matrix` / `overall_confidence` 原样透传

`ai_detail.featureMatrix` 与 `ai_detail.overallConfidence` 逐键透传，键名**保留 AI 侧的驼峰**（`pitchStd` 等），不做 snake_case 转换——这是 AI 内部特征包，改名会让它和写入方对不上，查问题时两边对不上号。

两者都可以是 `null`（`ai_detail` 可空，或该键缺失）。**不做结构校验**：不是 dict 就出 `null`，不抛错。

`featureMatrix` 是 4.5 的四块里唯一能交出的完整数据（9 个声学量足以让后续自行推维度分）。风险已知：把它固化进对外契约后，改动即破坏性变更——登记在 DOC_ISSUES。

### 3.8 4.7 BKT：合并成数组，`delta` 由后端算

`bkt_before` / `bkt_after` 是两个扁平字典，合并成 `[{skill, before, after, delta}]`：

- 取**两侧 key 的并集**；一侧没有的技法给 `null`。
- `delta = after - before`，**后端算**（教师端只做展示，不该在前端算业务量）。仅两侧都是数值时才算，否则 `null`。
- `delta` **`round(..., 4)`**：`0.48 - 0.46` 在浮点下是 `0.020000000000000018`，直接出会给前端一个 18 位小数。
- **只放行真正的数值**，字符串 `"0.82"`、`True` 一律当无值处理（同 `homework_service._num`，`bool` 要单独排除——`isinstance(True, int)` 是 `True`）。
- 两侧都无值 → `bkt: []`（真库 25/26/27 就是这种）。**不是 `null`**：空数组表示「查了，没有」，与 §3.6 的 `dimensions: null`（表示「这块没实现」）语义不同。
- 任一侧不是 dict（脏数据）→ 该侧按无值处理；两侧都不是 dict → `[]`。
- **排序：按 `skill` 名升序**。不依赖 JSONB 的键序——PostgreSQL 的 jsonb 有规范键序（短键先、同长按字节序），当前真库里恰好与技法的教学顺序观感一致，但那是实现细节，不该被契约依赖。要改成「最弱技法在前」（按 `before` 升序）只需动这一行。

### 3.9 批改现状

出 `status` / `teacher_score` / `teacher_comment` / `voice_comment_text` / `voice_comment_audio_id` / `reviewed_at`。

这些是 F6（终审）写入的列，严格说不属功能 4.4–4.7。放进来是因为**没有它们本接口不可用**：

- `status`（`submitted`/`ai_scored`/`reviewed`）是判「这份还批不批」的唯一依据。真库 5 行全是 `ai_scored`，教师打开面板必须知道这一点。
- 一个「批改详情」GET 若不回当前批改结果，F6 提交完还得再调一个接口才知道自己刚写了什么。
- `voice_comment_audio_id` 是 §3.9 里唯一有连带关系的一列：F6 写 `voice_comment_text` **和** `voice_comment_audio_id`（功能 4.11 语音点评），前端要播那段语音得走 B5 `GET /api/audio/<file_id>`。只给文字不给 id，语音就取不回来。

**真库里的一个反常**：23/24 的 `teacher_score` 与 `teacher_comment` 已有值，但 `status` 仍是 `ai_scored`、`reviewed_at` 仍是 NULL——即「写了分数但没走终审」。本接口照实透传，不替它推断状态。（DOC_ISSUES 第 622 行记过：全项目还没有任何代码把 `status` 写成 `reviewed`，F4 因此一直把它们列为待批。终审接口 F6 落地后才谈得上修正。）

**校准现状（`score_calibrations`）不出。** 它是 F7 的读职责，本次不把 F7 的回显口径提前拉进 F5。

> **2026-10-08 更新（本条已被推翻）**：F7 落地时改为**出**——出参加 `calibration` 字段（`{bias_mode, ai_score, teacher_score, created_at} | null`），同一提交多行时取**最新一条**（`created_at DESC, id DESC`）。推翻的理由：F7 在《5-接口清单》里只有 POST，读职责没有落点，「F7 的读职责」这句话本身指不到任何接口。新口径见 `2026-10-08-submission-calibration-design.md` §3.6 与 §4.5，以及 `DOC_ISSUES.md` 第 37 条。

### 3.10 头部字段与空值兜底

头部：`submission_id` / `homework_id` / `homework_title` / `student_id` / `student_name` / `student_avatar` / `student_level` / `submitted_at` / `audio_id`。

| 字段 | 可能的值 | 处理 |
|---|---|---|
| `student_name` | `null`（`students.user_id` 指向不存在的 user，DOC_ISSUES 第 21/24 条） | 出 `null`，前端兜「未知学生」 |
| `student_avatar` | `null` **或空串**（`students.avatar` 可空；F4 里张三那个种子是空串） | 出原值，前端用 `\|\|` 兜，**不能用 `??`**（兜不到空串） |
| `student_level` | `null` | 出 `null` |
| `homework_title` | `null`（`submissions.homework_id` 可空，LEFT JOIN 后取不到） | 出 `null` |
| `submitted_at` | `null`（列可空） | 出 `null`，ISO-8601 格式 |
| `audio_id` | `null`（真库 5 行全是 NULL） | 出 `null` |
| `ai_score` | `null` | 出 `null` |

`model_dump(mode="json")` 必须加：出参里有 `datetime`（`submitted_at`/`reviewed_at`），默认 dump 会按 RFC-822 序列化成 `"Sat, 01 Aug 2026 00:00:00 GMT"`。

### 3.11 坏数据一律兜住，不让整个请求 500

`ai_detail` / `bkt_*` 是 JSONB，结构由 AI 侧写入、不受本服务约束。**一条坏数据不该让教师打不开批改面板**：`defects` 不是 list、元素不是 dict、`label` 缺失或空串 → 跳过该元素/整块出 `[]`，请求**仍是 200**。

`label` 缺失或空串的 CDM 元素整条丢弃（同 F4 `_tags_of`）：构造不出标签文字，前端会渲染成一个空胶囊。

**但 `confidence` 取不到的元素不丢**——这与 F4 不同。F4 是拿 confidence 排序筛选的，缺了它就没法定位；F5 只是把它带出去，缺了就给 `null`（那条排在末尾，见下）。藏起来比带个 `null` 严重。

CDM 排序：有 `confidence` 的按降序在前，无 `confidence` 的按**原始数组序**沉底（Python 的 `sort` 是稳定排序，同 key 保持原序）。

### 3.12 权限

`@login_required` + `@teacher_required`。

依据：《5-接口清单》F5 权限列写的就是「教师」；《6-登录与数据隔离方案》权限矩阵里「布置/**批改**作业」学生 ❌、「查看任意学生数据」学生 ❌。

| 情形 | 结果 |
|---|---|
| 未登录 | 401（`login_required`） |
| 学生登录 | 403（`teacher_required`） |
| `submission_id` 不存在 | 404 `{"code":404,"message":"提交不存在"}`（`BusinessError`，service 层抛） |
| `/submissions/abc/detail` | 404 `{"code":404,"message":"接口不存在"}`（路由未匹配，走 `errors.py` 的统一信封） |

后两条同为 `code:404`，**只能靠 message 区分**（F4 §5 第 4 点已确认这是本项目既有形态）。

---

## 4 实现设计

### 4.1 分层

```
app/api/homeworks.py                submissions_detail(submission_id)   ← 换掉错桩（§2.6）
app/services/homework_service.py    submission_detail(db, submission_id)
app/repositories/homeworks_repo.py  get_submission_detail(db, submission_id)
app/schemas/homework.py             CdmTag / BktChange / LyricWord / SubmissionDetailResponse
```

`submission_detail` 与 `list_pending_submissions` 同放 `homework_service.py`：两者是同一份提交数据的两种投影（列表 / 详情），共用一个模块比拆文件更贴近调用方的认知——与 F1/F4 同处一个文件的理由一致。

### 4.2 路由

`app/api/homeworks.py` 里把 §2.6 的错桩**整条替换**：

```python
@api_bp.route("/submissions/<int:submission_id>/detail", methods=["GET"])
@login_required
@teacher_required
def submissions_detail(submission_id):
    # mode="json"：出参里有 datetime（submitted_at / reviewed_at）。默认 model_dump()
    # 会给 Flask 一个 datetime 对象，而它按 RFC-822 序列化成
    # "Sat, 01 Aug 2026 00:00:00 GMT"；mode="json" 出的是 ISO-8601。同 F1/F4。
    return ok(homework_service.submission_detail(
        get_db(), submission_id).model_dump(mode="json"))
```

**不留 `/homeworks/<id>/detail` 别名**：文档里没有这条路径，留一个别名等于凭空多一条接口。函数名同时从 `homeworks_detail` 改为 `submissions_detail`（旧名与地址一样是错的）。

注意 `@api_bp.route` 的装饰器**必须在 `register_blueprint` 之前执行**（本文件所有路由都在模块顶层，天然满足，见 `app/api/__init__.py` 的注册清单）。

### 4.3 出参

以真库 submission 24 为准：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "submission_id": 24,
    "homework_id": 12,
    "homework_title": "《穆桂英挂帅》· 辕门外三声炮",
    "student_id": 50,
    "student_name": "刘思琪",
    "student_avatar": "🎵",
    "student_level": "初学",
    "submitted_at": "2026-08-01T00:00:00",
    "audio_id": null,

    "ai_score": 75.2,
    "overall_confidence": 0.68,
    "feature_matrix": {
      "pitchStd": 32, "energyStd": 0.38, "pitchMean": -5, "pitchTrend": "random",
      "lowPitchBias": -18, "vibratoDepth": 8, "highPitchBias": 2,
      "rhythmAccuracy": 0.65, "durationMeanDiff": -0.12
    },
    "dimensions": null,

    "lyrics": [],

    "cdm_tags": [
      {"id": "d1", "label": "音准偏差随机", "severity": "high", "category": "音准",
       "confidence": 0.85,
       "evidence": "整句音高偏差无系统性倾向，-30~+20 cents 随机波动，标准差 28cents。",
       "features": {"趋势": "随机波动", "标准差": "28c", "偏差均值": "-5c"}},
      {"id": "d2", "label": "听辨能力弱", "severity": "high", "category": "音准",
       "confidence": 0.76, "evidence": "音高偏差随机分布，无明显偏高/偏低趋势，提示听辨感知能力不足。",
       "features": {"偏低比例": "42%", "偏高比例": "35%", "准确比例": "23%"}},
      {"id": "d3", "label": "拖腔不足", "severity": "medium", "category": "节奏",
       "confidence": 0.71, "evidence": "'帅'字拖腔仅 0.4s < 标准 0.7s，气息不足以支撑完整拖腔。",
       "features": {"实际": "0.4s", "标准": "0.7s"}},
      {"id": "d4", "label": "气息支撑不足", "severity": "medium", "category": "气息",
       "confidence": 0.52, "evidence": "长音段能量衰减明显，'炮'字后半段能量下降 18%。",
       "features": {"阈值": "10%", "能量衰减": "18%"}}
    ],

    "bkt": [
      {"skill": "气息支撑", "before": 0.42, "after": 0.40, "delta": -0.02},
      {"skill": "音准控制", "before": 0.48, "after": 0.46, "delta": -0.02}
    ],

    "status": "ai_scored",
    "teacher_score": 75.2,
    "teacher_comment": "音准偏差较大，建议先进行单音模唱训练。",
    "voice_comment_text": null,
    "voice_comment_audio_id": null,
    "reviewed_at": null
  }
}
```

## 4.4 出参模型（`app/schemas/homework.py`）

```python
class CdmTag(BaseModel):
    """4.6 CDM 归因诊断标签的一条（批改详情用）。

    与 F4 的 SubmissionTag **不是同一个模型**：F4 只出 label + severity，这里出全字段。
    刻意不合并——F4 是卡片，本接口是批改页，两者的字段面会各自演化；共用一个模型会
    逼着两处同步，而它们需要的本来就不是一回事。
    """

    model_config = ConfigDict(from_attributes=True)
    id: str | None                # defects[].id 原名透传（如 "d1"），不改成 skill_id
    label: str
    severity: str                 # defects[].status 原文；取不到为 "unknown"
    confidence: float | None      # 取不到为 None，**不因此丢元素**（spec 3.11）
    category: str | None
    evidence: str | None
    features: dict | None


class BktChange(BaseModel):
    """4.7 BKT 前后对比的一条。delta 由后端算并 round(...,4)（spec 3.8）。"""

    model_config = ConfigDict(from_attributes=True)
    skill: str
    before: float | None
    after: float | None
    delta: float | None


class LyricWord(BaseModel):
    """4.4 歌词级偏差对比的一个字。

    **当前恒为空数组**：库里无数据源（spec 2.5）。契约**对齐 B 组 words[] 的子集**
    （analyze_service._words），字段名用 B 组的 `word` 而非 mock 的 `char`——同一份
    逐字偏差在 B4 与 F5 两条接口上形状必须一致。不出展示层的 st/excellent 着色档。
    """

    model_config = ConfigDict(from_attributes=True)
    index: int
    word: str | None
    start: float | None
    end: float | None
    deviation_cents: float | None
    warning: bool | None


class SubmissionDetailResponse(BaseModel):
    """F5 批改详情（功能 4.4-4.7）。

    学生字段平铺不嵌套（同 F4 spec 3.9）。
    `dimensions` 恒为 None——四维分无数据源，是显式空位不是省略键（spec 3.6）。
    `lyrics` 恒为 []——逐字偏差无数据源（spec 3.5）。
    4.5 的四块里唯一有数据的是 feature_matrix 与 overall_confidence，原样透传（spec 3.7）。
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
    # 4.5
    ai_score: float | None
    overall_confidence: float | None
    feature_matrix: dict | None
    dimensions: dict | None       # 恒为 None
    # 4.4
    lyrics: list[LyricWord]       # 恒为 []
    # 4.6
    cdm_tags: list[CdmTag]
    # 4.7
    bkt: list[BktChange]
    # 批改现状
    status: str | None
    teacher_score: float | None
    teacher_comment: str | None
    voice_comment_text: str | None
    voice_comment_audio_id: int | None
    reviewed_at: datetime | None
```

`CdmTag.id` 直接叫 `id`，与 `defects[].id` 同名透传，不做 `skill_id` 之类的改名——pydantic v2 允许 `id` 作字段名（`BaseModel` 自身没有该属性，只有 `model_` 前缀受保护）。

## 4.5 SQL

一条 join 取完，不在 Python 里逐条回查（同 F4 §4.3）：

```sql
SELECT submissions.*, students.level, students.avatar,
       users.display_name, homeworks.title
FROM submissions
LEFT JOIN students  ON students.id  = submissions.student_id
LEFT JOIN users     ON users.id     = students.user_id
LEFT JOIN homeworks ON homeworks.id = submissions.homework_id
WHERE submissions.id = :submission_id
```

**三层 join 全必须 LEFT**：

- `submissions.student_id` / `submissions.homework_id` 列本身可空，INNER 会让这两种提交整条 404——教师点开一个真存在的提交却被告知「不存在」。
- `students.user_id` 那层用 LEFT，保证 `students` 有行而 `users` 缺失时至少还能出 `student_id` 与头像。
- 姓名**必须**经 `students.user_id` 拐一次取 `users.display_name`，**不能** `db.get(User, student_id)`——`submissions.student_id` 指的是 `students.id`，与 `users.id` 只是偶尔数值相同，直接当 `users.id` 用会静默取到另一个人的名字（DOC_ISSUES 第 21 条）。

`db.get(Submission, submission_id)` **不够**：本接口要三张表的字段，单独 get 会触发三条懒加载 SQL，不如一条 join。

仓储层返回的元组顺序**必须与 `SELECT` 逐列一致**：`(提交, 等级, 头像, 姓名, 作业标题)`。**解包顺序写错不会报错**——等级、头像、姓名、标题四个都是 str，pydantic 照收，只是字段对调了，页面把头像显示成姓名。F4 的仓储函数末尾专门写了同一条警告（`homeworks_repo.py:171`）。

### 4.6 service 装配

```
submission_detail(db, submission_id):
    row = homeworks_repo.get_submission_detail(db, submission_id)
    if row is None:
        raise BusinessError(404, "提交不存在")
    (sub, level, avatar, name, hw_title) = row   # 顺序见 4.5 的 SELECT，别写错
    return SubmissionDetailResponse(
        ...,
        feature_matrix = _feature_matrix(sub.ai_detail),
        dimensions     = None,
        lyrics         = [],
        cdm_tags       = _cdm_tags(sub.ai_detail),
        bkt            = _bkt_changes(sub.bkt_before, sub.bkt_after),
        ...
    )
```

三个私有辅助函数（`_cdm_tags` / `_bkt_changes` / `_feature_matrix`）放 `homework_service.py`：

- `_cdm_tags(ai_detail)`：复用 `_num` 校验 confidence；按 §3.2/§3.4/§3.11 取值与排序。
- `_bkt_changes(before, after)`：按 §3.8 合并并集、算 delta、排 skill 名。
- `_feature_matrix(ai_detail)`：`ai_detail` 不是 dict 或该键不是 dict → `None`；否则原样返回该 dict（键名保持驼峰）。

`_overall_confidence` 不单独写函数，在装配处取 `ai_detail.get("overallConfidence")` 并过一遍 `_num`（`"0.68"` 这种字符串要挡掉）。

---

## 5 验证方案

无测试框架（`requirements.txt` 里没有 pytest，不引入），按既有做法用 `/tmp` 临时脚本 + curl + psql。

起服务：项目根目录、激活 venv 后 `python app-d.py`（端口 8877），经 nginx 访问。

1. **教师（teacher01）`GET /api/submissions/24/detail`** → 200。
   - `cdm_tags` **4 条**，顺序 `0.85 / 0.76 / 0.71 / 0.52`。**0.52 那条必须在**——这是「不套 0.7 阈值」的反证；若只出 3 条，说明误用了 F4 的阈值。
   - 每条 7 个字段齐全，`category` / `evidence` / `features` 非空。
   - `bkt` 2 条，`[{气息支撑, 0.42, 0.40, -0.02}, {音准控制, 0.48, 0.46, -0.02}]`，**delta 恰好是 `-0.02` 而不是 `-0.020000000000000018`**。
   - `lyrics: []`、`dimensions: null`。
   - `feature_matrix` 9 个键且**键名是驼峰**（`pitchStd` 等）；`overall_confidence` = 0.68。
   - `student_name` 刘思琪、`student_avatar` 🎵、`student_level` 初学、`homework_title` 《穆桂英挂帅》· 辕门外三声炮。
   - `teacher_comment` 非空、`status` = `ai_scored`、`reviewed_at` = null、`audio_id` = null。
   - `submitted_at` 出的是 ISO-8601（`"2026-08-01T00:00:00"`），**不是** `"Sat, 01 Aug 2026 ..."`。
2. **全量条数锚点**：五条依次 `cdm_tags` 条数 = `23→3 / 24→4 / 25→2 / 26→3 / 27→1`。与 F4 对照，23/24/26 三处**必须比 F4 多**（F4 出 2/3/2），25/27 与 F4 相同。
3. **`/api/submissions/23/detail`** → `bkt` **3 条**（`拖腔` / `气息支撑` / `音准控制`，按 skill 名升序即此顺序），`拖腔` 的 delta 是 `0.0`（0.28→0.28）不是 `null`。
4. **`/api/submissions/25/detail`** → 200 且 `bkt: []`（该行两侧 BKT 均 NULL），`cdm_tags` 照常 2 条。**不是 404、不是 null。**
5. **404 两种**：`/api/submissions/999/detail` → 404 `"提交不存在"`；`/api/submissions/abc/detail` → 404 `"接口不存在"`。
6. **旧地址必须失效**：`/api/homeworks/12/detail` → 404 `"接口不存在"`（证明没留别名）。
7. **权限**：`stu001` → 403；不带 Cookie → 401。
8. **坏数据兜底**（按抓到的 id 逐列改，改完逐列复原）：
   - 某条 `ai_detail` 改成 `{"defects": "坏数据"}` → 200 + `cdm_tags: []` + `feature_matrix: null`。
   - `defects` 里塞一个 `{"label": ""}` 与一个 `{"label": "X"}`（缺 confidence）→ 前者被丢弃、**后者保留且 `confidence: null` 排在末尾**，请求仍是 200。
   - 某条 `bkt_before` 改成 `"坏数据"` 且 `bkt_after` 保持 → `before` 全 null、`after` 有值、`delta` null。
   - 两侧都改成 `"坏数据"` → `bkt: []`。
9. **清理**：`python scripts/check_db.py` 只应报**既有漂移**（`demo_versions` 表 + `teacher_demos` 三列），不引入新的。本次不动库，应与基线一致。

**脏数据临时改动纪律**（DOC_ISSUES 第 35.5 条）：**只能按抓到的 id 改回**，绝不 `DELETE FROM <表> WHERE <别的列>`。

---

## 6 明确不做

- 不动 `homework.html`（右侧面板仍是 mock，等 F5 前端接入的另一轮）。
- 不实现 F6 / F7。
- 不补数据源：不写 `ai_detail`、不改 `seed.sql`、不实现 F3。
- 不出 `fusion`、不出 40/30/20/10 权重、不出 `score_calibrations` 现状。
- 不引入 pytest、不加分页、不新增 CSS/HTML。

---

## 7 要登记进 `DOC_ISSUES.md` 的

**新增第 36 条**（F5 批改详情落地），含六点：

1. **4.4 逐字偏差无数据源**：`submissions` 无列、`ai_detail` 无键；而 `schema.sql:127` 的列注释写的是「逐字偏差 + CDM 归因标签」——**列注释与真数据不符**。B 组算得出（`analyze_service._words`）但只活在 redis（TTL 1h），且要求 `segments.lyrics_json` 非空，而解析产出的段落该列恒 NULL（第 20 条）。本次 5 条提交的 `audio_id` 全为 NULL。
2. **4.5 四维分数无数据源**：`featureMatrix` 是 9 个原始声学量，不是维度分；40/30/20/10 只在《3-功能清单》一行与前端 mock 里，无映射定义；9 个特征里**没有对应「咬字」的量**（5 音准 / 2 气息 / 2 节奏），咬字维度拿不到任何输入。
3. **`ai_detail` 是**手搓种子数据**（来源 `/tmp/seed_cdm_report.sql`，第 24 条），不是分析产物；`featureMatrix` / `overallConfidence` 的语义同样未经算法验证。
4. **4.7 BKT 严重不全**：只有「音准控制 / 气息支撑 / 拖腔」三个技法名，5 行里 3 行两侧皆 NULL。
5. **`fusion.total` 语义未定义**：前端 mock 的 `fusion.total`（0.72）按 40/30/20/10 加权它自己的 `dimensions`（84/84/86/80）算出来是 0.84，两数不符；文档从未定义融合分的算法。本接口因此不出 `fusion` 键。
6. **桩地址修正 + §34.3 更正**：`app/api/homeworks.py:39` 的桩原本挂在 `/homeworks/<id>/detail`，而文档里 F5 是 `/submissions/<id>/detail`。§34.3 结尾「F3–F7 的另外 5 个桩地址正确」的说法**不成立**，需一并更正。

另记一条**本次自拟、需文档方确认**的口径：**F5 的 CDM 列表不套 F4 卡片的 `confidence > 0.7` 阈值**（§3.2）。真库里有三条（0.45 / 0.52 / 0.65）会因此出现在批改页而不出现在卡片上——这是有意的，但文档未规定批改页的标签筛选口径。

---

## 8 待文档方确认

1. **批改页的 CDM 标签是否也该按置信度筛选**（§3.2 选了不筛）。若不筛，教师会看到 0.45 这种低置信度标签；若筛，阈值取多少、以及 4.10「评分校准数据回流」靠什么触发。
2. **4.4 逐字偏差的数据源何时补齐**：需要先有戏词录入入口（DOC_ISSUES 第 20 条已提），再让 B 组结果落进 `ai_detail`。在此之前本接口的 `lyrics` 恒为 `[]`。
3. **4.5 的四个维度分由谁算、按什么算**：文档只给了权重（40/30/20/10），没给「每个维度怎么从声学量算出来」。特别是**咬字维度没有任何对应的 `featureMatrix` 特征**，需要先定义它的输入。
4. **`feature_matrix` 是否该进对外契约**（§3.7 选了透传）。它是 AI 内部特征包，固化后改动即破坏性变更。
5. **BKT 技法的全集是什么**：库里只有三个技法名，而系统其它地方（知识图谱、能力追踪）的技法维度远多于此。本接口按「库里有什么出什么」处理，不补全。
6. **`lyrics` 元素契约**（§3.5 选了「对齐 B 组 `words[]` 的子集」）。若文档方希望批改页的逐字数据与 B4 不同形，需要现在提出。
