# AI 教练对话（`AI_teacher.html`）接入本地 LLM 实现设计

日期：2026-10-13 ｜ 状态：待实现 ｜ 关联：《1-PRD-V1.0》4.3；《3-功能清单》模块3；《5-接口清单》2.5 / 3.3；《2-系统设计说明》5.3；《10-后续工作计划》57-58 / 151-153；`DOC_ISSUES.md`（本次新增 4 条）

## 1. 背景与目标

`AI_teacher.html` 是《功能清单》**模块3「AI 教练对话」**的页面。它左侧「🔒 客观数据区」的数据是写死的 HTML（10 个字的偏差表、4 个 BKT 维度、2 个 CDM 标签），中间对话区由页面内 `RESPONSES` 常量（`:837`）按关键词查表冒充 AI 回复，`sendMessage` 用 `setTimeout`（`:1018`）演 1 秒延迟。**没有任何一行是真的。**

后端这边，`app/api/coach.py` 只有 18 行，三条路由全是桩：`coach_context` 返回 `ok(student_id)`、`coach_chat` 返回 `ok()`、`coach_history` 同样只回显入参。数据库 `chat_messages` 表已建好（`schema.sql:147`）且已有 1 行数据。

**目标**：把这三条接口按文档契约实现，让页面左侧读真库、右侧接真模型，跑通「客观数据 → 注入 prompt → LLM 生成 → 落库」这条链路。

**模型**：公司内网自部署的 vLLM 服务，`http://192.168.36.208:8007/v1`，OpenAI 完全兼容，模型 `Qwen3.6-27B-FP8`（MoE，权重 `/models/Qwen3.6-35B-A3B-FP8`，上下文 65536），**内网裸跑、无需 API Key**。实测首字节 9ms、300 token 完整回复 1.7–2.2s。

**不做**（见 §11）：不定 RAG、不建 CDM 数据源、不做流式、不改其余 11 个页面、不做全局悬浮助手。

## 2. 已确认的口径决策

以下五条在评审中逐条确认，是本设计其余部分的约束：

| # | 议题 | 决策 | 理由 |
|---|---|---|---|
| 1 | 接入形态 | **只打通 `AI_teacher.html` 一个页面**，其余 11 个页面不动 | 用户选定。也因此**不引入共享 JS**——项目至今没有自己的共享 JS（`common/` 8 个文件是 0 字节占位），不必为一个页面破例 |
| 2 | 左侧客观数据区范围 | **真库能撑的接、无源的显式空位**：BKT 接真数据、演唱摘要部分接、**逐字偏差 / CDM / RAG 一期一律显式空位**（返回 `null` + 页面标「待接入」） | 逐字偏差在库中**完全无源**（§2.1）；`homework_service.py:360` 已有「无数据源 → 显式空位」的先例。**不编造数据** |
| 3 | `student_id` 的确定 | **绑定登录人**：后端从 session 的 `user_id` 反查 `students.id`，与路径参数不一致则 403；**教师访问该页回 403「仅学生可用」** | 页面定位是「学生练习端」；数据隔离最干净，不必新增「可访问学生列表」接口 |
| 4 | 同步还是流式 | **一期非流式** | 《5-接口清单》3.3 原文：「LLM 同步调用，超时 3 秒；流式二期再考虑」 |
| 5 | 超时取 2 秒还是 3 秒 | **按系统设计取 3 秒** | PRD 3.2 写「2 秒内生成回复」、系统设计 5.3 写「超时 3 秒」，两者冲突；3 秒是工程口径，实测 300 token 约 2 秒，留出余量。冲突登记为 `DOC_ISSUES` 缺口（§10） |
| 6 | 演示走哪个账号 | **`s01`（`students.id=48`，李小燕）**——页面默认演示的学生就是她，且她是唯一有 BKT + `chat_messages` 数据的学生；`stu001` / `stu002` 保持空态 | 见 §2.1：`stu001` 名下 0 条数据、`stu002` 没有学生档案 |

### 2.1 数据现状（实现前逐行实测，非文档推断）

**踩过的坑**：设计初期曾按页面 mock 推断「逐字偏差来自 `practice_records.dimensions_json`」，实测后证伪——该列 6 行**全为 NULL**，且其语义是 `{音准,节奏,气息,咬字,拖腔}` 五个**维度分数**（`app/models/practice.py:30` 注释），不是逐字音高。`annotations` 表（5 行）是教师技法标注（`强音`/`换气`/`归韵` + `tolerance`），同样不是逐字音高。**逐字偏差在库中没有任何数据源。**

| 左侧区块 | 真库能否支撑 | 依据 |
|---|---|---|
| 演唱摘要 | ⚠️ 部分 | `practice_records` 6 行中 `ai_score` 有 4 行为 NULL、`segment_id` 有 5 行为 NULL（取不到曲目名）；**且这 6 行全部属于 `students.id` 50–55，与演示学生 48 无关** |
| **逐字偏差** | ❌ **完全无源** | `dimensions_json` 全 NULL 且语义不符；`annotations` 是技法标注 |
| BKT 能力状态 | ✅ 真数据 | `bkt_history` 196 行 = 8 名学生 × 8 技法；**`students.id=48` 名下 28 条** |
| CDM 归因 | ❌ 无源 | 无对应表；`score_calibrations` 仅 1 行且语义不同 |

**账号 ↔ 学生映射**（`students.user_id → users.id`）：

| 登录账号 | `users.id` | `students.id` | 数据情况 |
|---|---|---|---|
| `stu001` | 3 | 2 | 0 条 practice_records / bkt_history |
| `stu002` | 4 | **无** | 没有学生档案 |
| `s01` | 50 | **48（李小燕）** | 28 条 bkt_history、`chat_messages` 唯一那行 |
| `s02`–`s08` | 51–57 | 49–55 | 各 24 条 bkt_history |

**`chat_messages` 现有那行是 E1 的现成契约参考**：`student_id=48` 的 `context_snapshot` 记录了上下文应有的形状——

```json
{"学生画像":"李小燕 · 初级 · 1.5年 · 畏难倾向 0.32",
 "薄弱技法":"气息支撑(0.51) · 拖腔(0.28)",
 "本次偏差":"\"炮\"-35c · \"雷\"-42c · 拖腔偏短",
 "RAG 检索":"拖腔练习技巧 · 气息支撑训练",
 "约束条件":"禁止编造数值 · 苏格拉底式 · 水平适配",
 "strategy":"苏格拉底式引导", "strategy_desc":"…",
 "emotion":"平稳 · 积极参与", "emotion_score":72}
```

前四项与页面左侧写死的值完全吻合，说明**当初就是照着左侧面板手工写的**。本设计的 E1 结构照它对齐，但**只填有真源的部分**：`学生画像`（取 `students.level` + `users.display_name`）、`薄弱技法`（取 `bkt_history` 中 `p_l` 最低的几项）、`约束条件`（静态常量）；`本次偏差` 与 `RAG 检索` 一期为 `null`。

## 3. 文档契约原文

《5-接口清单》2.5 节，三条权限均为「登录」：

| 编号 | 接口 | 说明 |
|---|---|---|
| E1 | `GET /api/coach/context/<student_id>` | 客观数据区（功能 3.1）：摘要 / 逐字偏差 / BKT / CDM |
| E2 | `POST /api/coach/chat` | 发消息 → AI 回复（契约见 3.3），双写 `chat_messages` |
| E3 | `GET /api/coach/history/<student_id>` | 历史对话 |

E2 契约（《5-接口清单》3.3 节）：

```
// 请求
{"student_id":1, "message":"这一句总是唱不准"}
// 响应（LLM 同步调用，超时 3 秒；流式二期再考虑）
{"reply":"我们把第一段'海'字的曲线放大看看，你的音高和老师差在哪一段？",
 "strategy":"引导", "emotion":"neutral",
 "quick_replies":["再看一遍曲线","换个说法","直接告诉我问题"]}
```

数据流（《2-系统设计说明》5.3）：

```
GET /api/coach/context/<student_id> 组装客观上下文（画像/薄弱技法/本次偏差/RAG 检索）
POST /api/coach/chat → LLM 调用（超时 3 秒）→ 回复 + 策略 + 情绪
→ 双写 chat_messages（含 context_snapshot）→ 前端渲染对话与引导区
```

**响应信封**：按项目约定走 `app/response.py` 的 `ok(data)`，即 `{"code":0,"message":"ok","data":{...}}`，契约里的四个字段在 `data` 内。

## 4. 架构与新增文件

```
app/services/llm_client.py      新增  全项目唯一的 LLM 出口
app/services/coach_service.py   新增  组装 context / 拼 prompt / 落库
app/api/coach.py                改    填实三条桩路由
app/repositories/chat_repo.py   改    加「落库」与「读历史」两个函数
app/repositories/bkt_history_repo.py     改  加「按学生取每技能最新」
app/repositories/practice_records_repo.py 改  加「按学生取最新一条」
app/repositories/user_repo.py   改    加「user_id → students.id」
app/config.py                   改    加 4 个 LLM 配置项
.env / .env.example             改    加 4 个配置值
AI_teacher.html                 改    左侧改动态渲染 + 右侧接真接口
```

`llm_client.py` 单独成模块，是为了让「怎么调模型」与「教练业务逻辑」分开——将来换模型、加限频、改超时、开流式都只动这一个文件，`coach_service` 不用碰。

现有 `chat_repo.py` 里已有 `count_user_messages`，但它是给班级看板用的聚合查询，与本设计需要的「按学生落库 / 读历史」不是一回事，**不改动它**，新增函数并列放在同一文件。

**页面注册**：`AI_teacher` 已在 `app/pages.py` 的 `PROTECTED_PAGES` 列表中，本次不新增页面，无需改动。

## 5. E1 数据流

```
session["user_id"]
  → user_repo 反查 students.id 得到 own_student_id
  → 与路径 <student_id> 比对：不一致则 BusinessError(403, "无权访问该学员数据")
  → users.display_name + students.level               → 学生画像
  → practice_records_repo 取该生最新一条
       ai_score / duration_sec / created_at / segment_id
       （该生无记录时整块为 null）
  → bkt_history_repo 取该生每个 skill 的 recorded_at 最新一行
       skill / p_l / confidence                        → 能力状态
       按 p_l 升序取最低若干项                            → 薄弱技法
  → segment_id 非空时关联 segments 取段落名（5/6 行为 NULL，取不到就填 null）
  → ok({...})
```

返回结构（`data` 内）：

```json
{
  "student": {"id":48, "display_name":"李小燕", "level":"初学"},
  "last_practice": {                      // 该生无记录时整块为 null
    "segment_id":null,
    "segment_title":null,
    "ai_score":null,
    "duration_sec":15.0,
    "recorded_at":"2026-08-05 14:32:00"
  },
  "bkt": [{"skill":"音准控制","p_l":0.72,"confidence":0.85}, ...],
  "weak_skills": [{"skill":"拖腔","p_l":0.28}, ...],
  "deviations": null,   // 显式空位：无数据源，见 §2.1
  "cdm": null,          // 显式空位：无数据源
  "rag": null           // 显式空位：无数据源
}
```

**三项空位一律返回 `null` 而非 `[]` 或省略字段**：`null` 表达「这块没有数据源」，`[]` 表达「查了，结果为空」——两者语义不同，项目在 `app/services/homework_service.py:334` 已经确立了这条区分（原文：「`lyrics` 与 `dimensions` 是**显式空位**……与 `dimensions` 的 None（表示「这块没实现」）语义不同」）。字段**保留在响应里**，前端据 `null` 渲染「待接入」占位，将来补上数据源时前端判断不用改。

**`student.display_name` 取自 `users` 而非 `students`**：`students` 表没有姓名字段（只有 `id/user_id/level/avatar`），姓名在 `users.display_name`。

**`last_practice` 取「最新一条」的排序键**：`created_at DESC`，与 `idx_practice_student_time`（`student_id, created_at DESC`）这个既有索引一致。注意该列存的是**北京时间**（`postgres-stores-beijing-time`），不要套 `AT TIME ZONE`。

**学生无练习记录不是错误**：`last_practice` 为 `null`，接口照常 200。演示账号 `stu001` 就是这个情况，前端要能渲染空态。

## 6. E2 数据流

```
校验身份（同 E1）
  → 组装 context（复用 E1 的内部函数，不走 HTTP）
  → 取 chat_messages 中该生最近 N 轮历史（N=10）
  → 拼 prompt：system（教练人格 + 输出 schema）+ context 注入 + 历史 + 本次 message
  → llm_client.chat(messages, timeout=3)
  → 解析 reply / strategy / emotion / quick_replies（§8）
  → 双写 chat_messages：
       role='user'      content=message, context_snapshot=NULL
       role='assistant' content=reply,   context_snapshot={策略, 情绪, 上下文快照}
  → ok(四字段)
```

`context_snapshot` 照 §2.1 里那行既有数据的形状组织（中文键），至少含：`strategy` / `strategy_desc` / `emotion` / `emotion_score` / 学生画像 / 薄弱技法 / 本次偏差 / RAG 检索 / 约束条件。**无源的三项写 `null`**，与 E1 一致——快照要如实记录「当时 AI 用了什么上下文」，写假值会让它失去审计价值。

**双写在一个事务内**：用 `app/db.py` 的 `with session_scope() as s:`，两条要么都进要么都不进。半截对话（只有 user 没有 assistant）会让 E3 读出来的历史轮次错乱。

**失败不落库**：LLM 超时或返回异常时**一条都不写**（§9），避免用户重试后历史里堆积孤立提问。

**历史轮数 N=10**：文档未规定。取 10 轮是因为 `max_model_len` 有 65536、远不是瓶颈，真正约束是延迟——历史越长 prompt 越长、首字节越慢。实现时可调，写死在 `coach_service` 顶部一个常量。

## 7. Prompt 设计

`system` 消息承担三件事：

1. **人格**：戏曲演唱 AI 教练，苏格拉底式引导（《3-功能清单》3.2 原文「苏格拉底式引导」），不直接给答案；语言风格按学生水平适配（功能 3.6，初级班用更口语的表达）
2. **输出 schema**：要求只输出一个 JSON 对象，字段为 `reply` / `strategy` / `emotion` / `quick_replies`，并给一个完整示例
3. **策略与情绪的取值范围**：`strategy` ∈ {引导, 提示, 鼓励, 降难度}（功能 3.7 原文「在引导/提示/鼓励/降难度间切换」），`emotion` ∈ {positive, neutral, concerned}

**客观数据注入**：把 E1 的 context 序列化成紧凑 JSON 放进 user 消息开头，并明确写「以下为程序计算的客观数据，数值以此为准，不要编造」——对应页面已有的「数据/生成分离」设计（`AI_teacher.html:577` 的说明文字）。

**鼓励模式**：功能 3.8 要求输入「太难/算了」时切换为鼓励模式。**这条交给模型判断，不在后端做关键词硬匹配**——后端做的话，前端 `:963` 那段 `frustrationKeywords` 就成了第二份真源，两边规则迟早漂移。由 prompt 明示「学生若表达挫败（如『太难』『算了』『不想练』），必须切到鼓励模式并降低难度建议」。

## 8. LLM 输出解析（本设计的核心风险点）

文档契约要模型**同时返回 4 个结构化字段**，而聊天模型默认只吐一段文本。两条路，按顺序尝试：

**路线一：guided decoding。** vLLM 支持 `response_format={"type":"json_schema", ...}` 强制按 schema 解码。**实现第一步就是实测这个部署有没有开**——`curl` 打一次带 `response_format` 的请求即可判定。

**路线二（兜底）：prompt 约束 + 容错解析。** 在 `system` 里给死 schema 和示例，后端 `json.loads` 解析。解析失败时**降级而非报错**：

```
reply         = 模型原始输出全文
strategy      = "引导"
emotion       = "neutral"
quick_replies = []
```

降级路径必须走通——模型偶发不守格式是常态，不能因为一次格式抖动就让整个对话不可用。**降级时也要照常落库**（内容仍是有效的教练回复）。

**取值校验**：解析出的 `strategy` / `emotion` 若不在 §7 的枚举内，一并按上表降级处理，避免页面上出现渲染不了的标签。

## 9. LLM 接入要点

### 9.1 必须关闭思考模式

`Qwen3.6-27B-FP8` 是推理模型，**默认把内容全写进 `reasoning` 字段、`content` 返回 `null`**。实测：`max_tokens=32` 直接返回空 `content`；加到 800 仍 `finish_reason: length`（800 token 全耗在思维链上，一个字正文都没出）。

必须在请求体加：

```json
"chat_template_kwargs": {"enable_thinking": false}
```

关掉后 `content` 正常、18 token、`finish_reason: stop`。**这个参数写死在 `llm_client.py` 里并加注释说明原因**——它对本项目所有调用都是必需的，不该由每个调用方各自记得。

### 9.2 配置项

```
LLM_BASE_URL=http://192.168.36.208:8007/v1
LLM_MODEL=Qwen3.6-27B-FP8
LLM_TIMEOUT=3
LLM_API_KEY=            # 内网无需鉴权，留空
```

按 `app/config.py` 既有风格用 pydantic-settings 声明（`llm_base_url: str` / `llm_model: str = "Qwen3.6-27B-FP8"` / `llm_timeout: float = 3.0` / `llm_api_key: str = ""`），`env_file` 已在 `SettingsConfigDict` 里配好，不必额外处理。`LLM_API_KEY` 留空时**不发送 `Authorization` 头**，而不是发一个空的。

### 9.3 HTTP 客户端

用 `requests==2.34.2`（已在 `requirements.txt:101` 钉死），**不引入 `openai` SDK**——那会带进 httpx/anyio/distro/jiter/sniffio/tqdm 等约 8 个新依赖，要按项目规矩逐个钉死版本，而本项目只有一个端点要调。

超时配置为 `(connect, read)` 元组而非单值：连不上是网络问题、应快速失败，生成慢是正常现象、给足余量。

### 9.4 网络可达性（待验证）

内网地址 `192.168.36.208:8007` 是在开发机（macOS）上测通的。**部署到 Ubuntu 目标机后必须重新验证可达性**——若跨网段不通，整个设计需要改走中转。这一条列为实现的第一步验证项。

## 10. 文档缺口（登记到 `DOC_ISSUES.md`）

| # | 缺口 | 处置 |
|---|---|---|
| 1 | **逐字偏差无源**：PRD 3.1 / 功能 3.1 要求展示「歌词级偏差」，页面左侧也有一张逐字音高对照表，但 `practice_records.dimensions_json` 6 行全 NULL 且语义是五维分数、`annotations` 是教师技法标注——**逐字音高在库中没有任何来源** | 一期不实现，E1 的 `deviations` 恒为 `null`；页面对应位置标「待接入」（§2.1） |
| 2 | **RAG 检索无源**：《1-PRD-V1.0》3.9、《2-系统设计说明》5.3、《3-功能清单》3.9 三处都要求注入「RAG 检索结果」，但《4-数据库设计》15 张表中**没有任何知识库或向量表**，也未说明检索什么语料 | 同上，E1 的 `rag` 恒为 `null` |
| 3 | **CDM 归因无源**：左侧面板有「CDM 归因诊断」区（页面现有 2 个硬编码标签），但库中无对应表；`score_calibrations` 只有 1 行且语义不同 | 同上，E1 的 `cdm` 恒为 `null` |
| 4 | **超时口径冲突**：PRD 3.2「发送消息 2 秒内生成回复」vs 系统设计 5.3「超时 3 秒」 | 按 3 秒实现（§2 决策 5） |
| 5 | **接口权限未区分角色**：《5-接口清单》2.5 节 E1/E2/E3 权限均只写「登录」，未规定教师能否查看学生对话 | 按「仅学生」实现（§2 决策 3），并登记 |
| 6 | **演示数据与账号对不上**：`stu001`/`stu002` 是 CLAUDE.md 里写的种子账号，但两者名下都没有可演示的教学数据（`stu002` 甚至没有 `students` 行）；含数据的 `s01`–`s08` 未在任何文档中出现 | 本次演示改用 `s01`（§2 决策 6），并登记，供后续统一种子账号时处理 |

## 11. 前端改造（`AI_teacher.html`）

### 11.1 左侧客观数据区

把写死的 HTML 改为由 E1 结果渲染：

- 保留现有 CSS 类（`.data-section` / `.bkt-bar` / `.cdm-tag` 等），**只把内容变成动态生成的**，设计 token 与观感不变
- **BKT 能力状态**：由 `bkt` 真数据渲染（条宽按 `p_l`，标签显示 `p_l` 与 `confidence`）
- **演唱摘要**：由 `last_practice` 渲染；单个字段为 `null` 时显示 `—`（如曲目名、评分），整块为 `null` 时显示「暂无练习记录」
- **逐字偏差**：`deviations` 为 `null` → 渲染「逐字偏差待接入」占位，**保留表格区块与表头**，不删除版面
- **CDM 归因**：`cdm` 为 `null` → 同上，渲染「CDM 归因待接入」占位
- **RAG 检索**：中间对话区顶部那句「📝 上下文已注入：…」按 `rag` 是否为 `null` 调整文案，不再无条件宣称注入了 RAG
- 所有区块在数据缺失时**显示空态文案，不报错、不中断整页渲染**

### 11.2 右侧对话区

- 删除 `RESPONSES` 常量（`:837`）与 `getResponse` 的查表逻辑（`~:1003`）
- `sendMessage`（`:1006`）/ `sendQuick`（`:1030`）改为 `POST /api/coach/chat`
- 删除 `setTimeout`（`:1018`）的假延迟，改为请求进行中的 loading 态
- 回复渲染时同步更新策略标签（`#currentStrategyTag`）与情绪样式
- `quick_replies` 从响应里取，替换页面上写死的四个按钮（`:699-702`）
- 页面加载时调 `E1`（左侧）+ `E3`（历史对话），E3 为空时显示开场白

### 11.3 身份与 403

- 页面已有的 `/api/auth/me` 调用（`:1080`）拿到 `role`
- `role !== 'student'` → 右侧对话区替换为「AI 教练仅学生可用」，不再发任何请求（与 `demo_library.html` 对教师可见性的处理同构）
- E1/E2/E3 收到 403/401 时 → 沿用页面既有的跳登录页处理

### 11.4 移除的 mock

`STUDENT_PROFILE`（`:807`）、`SESSION_DATA`（`:815`）、`RESPONSES`（`:837`）三个常量在改完后若确定不再被引用，一并删除，不留死代码。

## 12. 验证方式

项目无测试框架，按既有作法「临时脚本 + curl + psql」三件套：

| 层 | 手段 | 验什么 |
|---|---|---|
| 服务层 | 临时 Python 脚本直调 `coach_service` | 以 `students.id=48` 验 context 组装（BKT 28 条能取到、`last_practice` 为 `null`、三项空位为 `null`）；以 `students.id=2` 验无数据学生的空态；LLM 不可达与非法 JSON 两条降级分支 |
| 接口层 | `curl` 打三条接口 | 端到端联通；**403 分支**（教师访问、跨学生访问）；401 分支（未登录）；超时分支（临时把 `LLM_BASE_URL` 指向黑洞地址） |
| 数据层 | `psql` 查 `chat_messages` | 双写各一行；`context_snapshot` 内容完整且**无源项确为 `null`**；失败时**确认一行都没写** |
| 页面 | 浏览器实际操作 | 以 `s01` 登录：左侧 BKT 真数据 + 三项「待接入」占位；对话真实往返；鼓励模式触发（输入「太难了」）。以 `stu001` 登录：全空态不报错。以 `teacher01` 登录：看到「仅学生可用」 |

临时脚本验完即删，不改动 `requirements.txt`。

## 13. 实施顺序

1. **验证内网可达性**（§9.4）+ **实测 guided decoding 是否可用**（§8 路线一）——这两个结论决定后续写法，先做
2. `llm_client.py` + 配置项，用 `curl` 等价的脚本单独验通模型调用
3. `coach_service` 的 context 组装（先不接 LLM），脚本验 E1 数据结构
4. 三条路由填实（含 `student_required` + user→student 解析 + 403 分支）+ 落库
5. 前端改造（左侧动态渲染 + 右侧接真接口 + 非学生角色的提示）
6. 端到端验证（以 `s01` 为主、`stu001` 验空态、`teacher01` 验 403）
7. 登记 `DOC_ISSUES.md` 六条缺口（§10）
