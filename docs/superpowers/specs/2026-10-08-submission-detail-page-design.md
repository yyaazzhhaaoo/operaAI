# 批改详情（F5）前端接入设计

日期：2026-10-08
接口 spec：`docs/superpowers/specs/2026-10-08-submission-detail-api-design.md`
接口：`GET /api/submissions/<int:submission_id>/detail`（已上线，见 commit `a58e9eb`）
页面：`homework.html`
DOC_ISSUES：第 36 条（§36.1 4.4 无源 / §36.2 4.5 无源与权重 / §36.4 BKT 数据不全 / §36.6 批改页 CDM 不套 0.7 阈值）、第 37 条（本次新登记的 4.10 校准项缺口）
前置：F4 前端已单独提交（`1d1dced` 代码 + `6e870f2` 文档）

---

## 1 背景、目标与非目标

### 1.1 目标

把 `homework.html` 右侧批改面板从 mock 常量 `SUBMISSIONS` 换成 F5 真接口，并删掉页面上最后两个 mock 常量。接完之后这一页**全部是真数据**。

### 1.2 非目标

- **不改任何后端文件。** F5 已上线，本次是纯前端接入。
- **不新增 HTML 元素、不新增 CSS 规则。** 面板的七个区块、槽位与配色都已存在，缺的只是数据。本次唯一的标记改动是删掉/改正两句**已经说错的静态文案**（§3.10）；`#emptyState` 的三态复用也不新增元素（做法见 §3.3）。
  - 特别地：**不给 CDM 标签加 `category` 胶囊**。真值拿到了（音准/节奏/气息/发声/咬字），但要显示就得新增一个胶囊元素加一套配色，那是新一轮设计决定，不属于「接入」。
- **不写终审提交（F6）、不做校准写入（F7）。** CDM 的 ✓/✗ 两个按钮与终审区的三个按钮维持现状（alert 桩）。终审区**只回显**库里的现值，见 §3.7。
- **不给没有槽位的数据补槽位。** `category` / `features` / `feature_matrix` / `overall_confidence` / `status` / `student_level` / 语音点评一律不上屏，清单与理由见 §3.11。
- **不做「布置新作业」（F2）。** `showAssignModal()` 维持 alert 桩。

---

## 2 现状与真源

### 2.1 F5 出参（真库实测，hw12 的 5 份提交）

| 提交 | 学生 | `ai_score` | `teacher_score` | `teacher_comment` | CDM 全量 | F4 卡片可见 | BKT |
|---|---|---|---|---|---|---|---|
| 24 | 刘思琪 | 75.2 | 75.2 | 有 | **4** | 3 | 2 条 |
| 26 | 孙志远 | 71.3 | — | — | **3** | 2 | `[]` |
| 27 | 赵雨桐 | 85.7 | — | — | 1 | 1 | `[]` |
| 23 | 李小燕 | 82.5 | 82.5 | 有 | **3** | 2 | 3 条 |
| 25 | 周明轩 | 78.9 | — | — | 2 | 2 | `[]` |

多出来的三条正是接口 spec §36.6 点名的：24 的 `0.52`「气息支撑不足」、26 的 `0.65`「声带紧张」、23 的 `0.45`「归韵口型保持不足」。**验证时要专门确认它们出现在批改面板上而不在左侧卡片上**——这正是 F5 与 F4 的口径差。

其余实测事实：

- `lyrics` **5 份全是 `[]`**；`dimensions` **5 份全是 `null`**。
- `feature_matrix` 5 份都齐（9 个驼峰键）；`overall_confidence` 依次 0.68 / 0.81 / 0.55 / 0.72 / 0.75。
- BKT 只有 23（3 条）、24（2 条）非空，其余 3 份是 `[]`。
- `audio_id` 5 份全 `null`；`status` 5 份全 `ai_scored`；`reviewed_at` 5 份全 `null`。
- `severity` 真值只出现 `high` / `medium` / `low`，**没有 `unknown`**（后端只在取不到 `status` 时才给 `unknown`）。
- `teacher_score` 有值的那两份恰好与 `ai_score` 相等（75.2 / 82.5）。
- 23 的 BKT 里「拖腔」是 `0.28 → 0.28`（`delta = 0.0`），是唯一的 `flat` 档样本。

### 2.2 页面现状（改动锚点）

| 锚点 | 现状 |
|---|---|
| `:522-597` | 右侧 `.review-panel`：`#emptyState`（`:526`）与 `#reviewContent`（`:533`）互斥两块 |
| `:536-546` | 学生信息头：`#detailAvatar` / `#detailName` / `#detailMeta` / `#detailScore` |
| `:550` | `#lyricsCompare`（4.4） |
| `:554-561` | `#fusionGrid` / `#fusionTotal` / `#fusionPass` + `:561` 的权重公式行（4.5） |
| `:565-566` | `#cdmList` + 置信度说明（4.6） |
| `:570` | `#bktList`（4.7） |
| `:575` | `#calibGrid`（4.10，F7 的地盘） |
| `:581-591` | 终审区：`#teacherComment` / `#finalScore` / `#aiSuggestedScore` + 三个按钮 |
| `:604-680` | 段头注释 + `HOMEWORKS`（`:613-617`）+ `SUBMISSIONS`（`:619-680`），页面最后的两个 mock |
| `:685` | `API_BASE = ""`（同源，走 nginx `/api` 代理） |
| `:696` | `let currentSubId = null` —— **写入过但从没被读过**（§3.8） |
| `:842-849` | `selectHomework()` 只复位左下，右侧一行不动（§3.9） |
| `:864-915` | `renderSubmitList()`，F4 的渲染函数；不产生 `active` 类 |
| `:917-1009` | `selectSubmission(id)` 目前是「`SUBMISSIONS.find` → 找不到 return → 填面板」 |
| `:255` | `.submit-item.active` 样式**已写好**，从没被加上过 |
| `:346` / `:350-351` | `.cdm-item` 基类 + `.high` / `.medium` 两档修饰类，**没有 `.low`** |
| `:353` / `:356-358` | `.conf` 基类 + `.high` / `.medium` / `.low` **三档都有** |
| `:1055-1058` | 首段脚本末尾：`renderSubmitList()` + 一段「右侧不做」的注释 |

### 2.3 与 F4 前端落地的关系

同构处：新增 `fetch*()` 函数、按 `currentUser.role` 分支、`API_BASE` 保持空串、所有进 `innerHTML` 的字段过 `esc()`、状态用「`null` / `[]` 两态 + 提示文案」区分。

三处不同：

1. F4 的列表只有「加载中 / 有数据 / 空 / 提示」四态，且**数据在响应里就定型了**；F5 多一层「点了谁」的选中状态，以及由此引出的竞态（§3.4）。
2. F4 落地时两处 mock 常量**仍然有用**（右侧在读），所以当时明确不删；本次 `selectSubmission` 重写后它们**没有任何使用点**，整块删除（§3.12）。
3. F4 的 §3.2 把「卡片高亮」留给了 F5（当时 `currentSubId` 恒为 null）。本次把它接上（§3.8）——这是 F4 遗留的唯一一处死状态。

---

## 3 自拟口径

以下都是接口 spec 与《5-接口清单》未定义、由本次前端落地自定的。

### 3.1 七个区块一律保留，没数据源的出显式空态

| 区块 | 功能 | 接口字段 | 真库现状 | 本次渲染 |
|---|---|---|---|---|
| 学生信息头 | — | `student_*` / `homework_title` / `submitted_at` / `ai_score` | 齐 | 真渲染 |
| 🎵 歌词级偏差对比 | 4.4 | `lyrics` | 恒 `[]` | 空态 |
| ⚖️ 多维加权融合 | 4.5 | `dimensions` / `feature_matrix` / `overall_confidence` | `dimensions` 恒 `null`（另两个有值但无槽位，§3.11） | 空态 |
| 🔍 CDM 归因诊断 | 4.6 | `cdm_tags` | 齐（全量共 13 条） | 真渲染 |
| 📈 BKT 状态更新 | 4.7 | `bkt` | 2/5 有值 | 真渲染；`[]` → 空态 |
| 🎯 AI 评分校准 | 4.10（**F7**） | **接口不出** | 表里 1 行 | 空态 |
| ✏️ 老师终审 | 4.8/4.9/4.11（**F6**） | `teacher_score` / `teacher_comment` / `ai_score` | 2/5 有值 | 只回显（§3.7） |

**保留区块，不删掉。** 删掉等于替产品决定「这一页不做这三块」，而 4.4 / 4.5 / 4.10 在文档里都是正式需求。保留 + 显式空态，教师看到的是「这里还没接入」，而不是「这功能不存在」——同一页里「没数据」与「没这功能」必须能分辨。

「（数据源待接入）」这个后缀**只给歌词 / 融合 / 校准三块**——它们的空是因为数据源不存在。BKT 与 CDM 的空态是**真数据条件下的「本次没有」**（`bkt: []` 是真库常态、「暂无归因标签」是这份提交确实没标签），说成「数据源待接入」是错的。两组文案必须能区分：一组是「这功能还没接」，一组是「这次没有」。

空态的样式**复用页面既有写法**（内联 `text-align:center;color:var(--text-muted);font-size:11px`，与 `fetchHomeworks` / `renderSubmitList` 的空态同一套），**不新增 CSS**。五个区块的空态（三处空位 + BKT 与 CDM 的「本次没有」）都由一个 `emptyBlock(text)` 出，避免同一串内联样式抄五遍。

### 3.2 四个状态：idle / loading / error / content

```js
let detailState = "idle";   // idle | loading | error | content
```

| state | `#emptyState` | `#reviewContent` |
|---|---|---|
| `idle` | 显示首帧原文 | 隐藏 |
| `loading` | 显示 `⏳ 加载中…` | 隐藏 |
| `error` | 显示 `⚠️ 加载失败` + 原因 + 「重试」按钮 | 隐藏 |
| `content` | 隐藏 | 显示，内容由 `detailData` 填 |

**每个状态都完整渲染两块，不做「状态没变就跳过」的优化。** 从 `content` 切到 `loading` 时必须**先把 `#reviewContent` 藏起来**，否则点第二名学生的瞬间，右侧还挂着上一名的分数与评语，而加载态又已经显示——教师会读成「这名学生的数据正在刷新」，那是错的。

`loading` / `error` 两态用到的都是**已有元素**：`#emptyState` 里的 `.icon` / `.title` / `.desc`（`:527-529`）与终审区同款样式的 `.btn-secondary`（`:590`）。不新增元素、不新增 CSS。

### 3.3 三态共用 `#emptyState`，用首帧快照还原 idle

`#emptyState` 与 `#reviewContent` 是面板里互斥的两块，而 `idle` / `loading` / `error` 三者都属于「没有内容可显示」，天然是 `#emptyState` 的三种样子。所以只改写 `#emptyState` 的 `innerHTML`，不新增元素。

代价是 `idle` 那段原文会被覆盖掉，回 `idle` 时得还原。还原用**首帧快照**，不在 JS 里再抄一份文案：

```js
// 首帧原文（idle 态），必须在任何代码改写 #emptyState 之前抓。
// 回 idle 时原样写回，这样「选择左侧提交进行批改」那段文案只有一个来源（HTML）。
const DETAIL_IDLE_HTML = document.getElementById("emptyState").innerHTML;
```

取的位置是首段 `<script>` 顶层——那时还没有任何代码动过 `#emptyState`（首段末尾才第一次调 `renderDetail()`）。

**不把 idle 文案抄成 JS 常量**：那样 HTML 与 JS 各有一份同样的三行标记，改一处忘一处，页面会在两种「空状态」之间跳。快照只有一个来源。

### 3.4 竞态守卫用自增序号，不用 id 比较

```js
let detailSeq = 0;
// 请求前
const seq = ++detailSeq;
// await 之后
if (seq !== detailSeq) return;      // 已被更晚的点击或切作业作废
```

**为什么不像 F4 那样比 id**（F4 的 `fetchSubmissions` 用 `currentHwId !== hwId`）：教师**双击同一张卡片**会发两个请求，两次的 id 相同，用 id 比较两个都会通过，后回来的那个直接覆盖——若两次响应不同（比如期间 F6 写了库），面板会停在「先发后到」的那份上，而它是更旧的。自增序号能区分同一 id 的两次请求。

它顺带覆盖了「切作业」的情形：`selectHomework` 里 `detailSeq++` 一句就把在飞的详情请求全部作废（§3.9），不用再单独判作业。

### 3.5 CDM：severity 要两套映射，`item` 与 `conf` 的可用档位不同

| `severity` | `.cdm-item` 的类 | `.conf` 的类 | 观感 |
|---|---|---|---|
| `high` | `cdm-item high` | `conf high` | 绿描边 + 绿胶囊 |
| `medium` | `cdm-item medium` | `conf medium` | 赭黄描边 + 赭黄胶囊 |
| `low` | `cdm-item`（**无修饰类**） | `conf low` | **中性描边** + 蓝胶囊 |
| 其它（含后端给的 `unknown`） | `cdm-item` | `conf` | 中性描边 + 中性胶囊 |

依据是真库里现成的 CSS：`.cdm-item` 只定义了 `.high` / `.medium` 两档边框色（`:350-351`），而 `.conf` 三档都有（`:356-358`）。

**不给 `.cdm-item` 补 `.low` / `.unknown` 的规则。** 低档与未知档共用基类的中性描边够用；真正需要区分的是胶囊（低档是蓝的），那里已有现成的 `.conf.low`。补规则属于 §1.2 说不做的样式改动。若评审认为低档也该有专属描边，再单独提。

真库 23 的第三标签（`low` / 0.45）正好走这条路径，验证时专门看它。

**不做白名单过滤**：取到不认识的档照渲，不能让它凭空消失（与 F4 §3.4 同）。

`label` / `evidence` 一律过 `esc()`（都来自数据库）。

`confidence` 为 `null` 时胶囊显示 `—`，**不能 `.toFixed()`**——F5 刻意不丢这类元素（接口 spec §36.6），而 `null.toFixed` 会抛 TypeError 打断整个 `map`，一条坏数据让整块渲染不出来。这条与 `demo_library.html` 的「待校准」判定是同一类防御。

`cdm_tags` 为 `[]` → 「暂无归因标签」。

### 3.6 BKT：`before` / `after` / `delta` 都可能为 null

| 字段 | 为 `null` 时 |
|---|---|
| `before` / `after` | 数值位显示 `—`；该侧条形宽度按 `0` 渲染（`(null).toFixed(0)` 会抛，必须先判数值再算宽度与 `toFixed`） |
| `delta` | 走 `flat` 档（灰色、无箭头） |
| 颜色档（`:985` 那串按 `after` 分档的阈值） | `after` 为 `null` 时取不到输入，用 `var(--text-muted)` 兜 |

**`delta` 为 `null` 必须显式判，不能靠 `null > 0` 为假落到 `flat`。** 那只是巧合：`null < 0` 同样为假，正好落到 `flat` 那一支，看起来「能跑」；将来那串三目一改（比如先判 `< 0`）立刻变成未定义行为。

`bkt` 为 `[]` → 「本次无 BKT 状态变化」。**这是真库的常态（5 份里 3 份）**，不是边缘情况，文案要写清「本次没有」，不能与「加载失败」共用一句话。

**顺序照接口给的顺序**（后端按 skill 名升序排好了）。**不要按 `delta` 或 `after` 重排**：接口 spec 明确说排序口径将来可能改成「最弱技法在前」，页面自己再排一次，等后端一改两边就打架。

### 3.7 终审区只回显，不判「还能不能改」

| 槽位 | 取值 | 兜底 |
|---|---|---|
| `#teacherComment`.value | `d.teacher_comment \|\| ""` | `null` → 空串（`placeholder` 自己会显示） |
| `#finalScore`.value | `d.teacher_score ?? d.ai_score ?? ""` | 都没值 → 空 |
| `#aiSuggestedScore` | `d.ai_score == null ? "—" : d.ai_score` | `null` → `—` |

**`??` 与 `\|\|` 的选择是有意的**：`teacher_score` 与 `ai_score` 都可能是合法的 `0`，用 `\|\|` 会把 0 当成没值。字符串那一格用 `\|\|` 是因为 `""` 与 `null` 在 textarea 里没有区别。

**不按 `status` / `reviewed_at` 禁用或改写这三个控件。** F5 出的 `status` 5 份全是 `ai_scored`、`reviewed_at` 全是 `null`，而 23/24 已经有 `teacher_score` 与评语了（「写了分数但没走终审」的反常数据，接口 spec 已说明照实透传）。页面若自己按 `status` 推断「还没批过」并把已存在的评语盖掉，就等于替 F6 定终审状态机。

三个按钮（通过并发布 / 保存草稿 / 语音）**一行不改**，维持 alert 桩。

### 3.8 卡片高亮：把 `currentSubId` 从死状态接上

F4 spec §3.2 明确写了「`currentSubId` 永远是 null，没有任何卡片会高亮」，把高亮留给 F5。现在 F5 到位，`renderSubmitList` 补一行：

```js
const active = it.submission_id === currentSubId ? " active" : "";
```

理由：点开一张卡片后右侧换了内容，**左侧看不出点的是哪一名**；面板比列表长，滚下去再回来就找不到当前这条。`.submit-item.active` 的样式（`:255`）本来就照可点击设计写好了，与 F1 的 `.hw-item.active` 同款，接线即可。

注意顺序：`selectSubmission` 必须**先设 `currentSubId` 再调 `renderSubmitList()`**，否则高亮慢一拍。

### 3.9 切换作业必须复位右侧（修 F4 的遗留缺陷）

`selectHomework()` 现在只复位左下（`submitItems = null`），**右侧一行不动**。F4 时这不可能出问题（右侧永远是空状态）；F5 落地后它就是实缺陷：开过 hw12 的刘思琪，再点左侧 hw13，右侧还挂着刘思琪的分数与评语，而左下的待批列表已经换成 hw13 的（空的）。教师会以为 hw13 里有一份刘思琪的提交。

本次在 `selectHomework` 里补：

```js
currentSubId = null;      // 取消左下高亮
detailSeq++;              // 作废在飞的详情请求
detailData  = null;
detailState = "idle";     // 回空状态，**不是**回「加载中」——没有新提交要加载
renderDetail();
```

**回到 `idle` 而不是 `loading`**：切作业后没有任何提交被选中，显示加载中会让教师以为右侧在等他点的那一份。

### 3.10 两句静态文案要改（本次唯一的标记改动）

| 位置 | 原文 | 改为 | 为什么 |
|---|---|---|---|
| `:561` | `公式: Σ(wᵢ × dimᵢ_score) ≥ 0.6 ? "通过" : "未通过" · 当前权重: 音准40% 节奏30% 气息20% 咬字10%` | **整行删除** | 它描述的 `dimensions` 与 `fusion` 接口都不出（§36.2），照渲会在一排「—」底下摆一个具体公式。40/30/20/10 与 0.6 这两个数文档从未定义、接口也刻意不带，留在页面上等于页面自己发明了一套算法 |
| `:566` | `只展示置信度 > 0.7 的标签 · 老师可修正，数据回流优化模型` | `按置信度降序展示全部标签（不筛阈值） · 老师可修正，数据回流优化模型` | 后半句仍然成立；前半句在 F5 上是**反的**——批改页刻意不筛（§36.6），真库有 3 条 ≤ 0.7 的标签会出现在这里 |

两处都是删/改一句已经说错的静态文本，**不新增任何元素**。

`:`574` 的「勾选 AI 评分偏差模式，帮助系统学习您的评分偏好：」**保留不动**：它下面那格虽然出空态，但这句是对「校准」这个功能块的说明，删了区块就只剩标题。读起来是「勾选…：」+「暂无校准项（数据源待接入）」，可接受。

### 3.11 出参里页面不显示的字段

| 字段 | 为什么不显示 |
|---|---|
| `cdm_tags[].category` | 没有槽位。真值是「音准/节奏/气息/发声/咬字」，要显示就得给每个标签加一个胶囊——新元素 + 新配色（§1.2） |
| `cdm_tags[].features` | AI 内部特征包，与 `feature_matrix` 同类（见下） |
| `cdm_tags[].id` | 是 F6「逐条确认/驳回」的定位用（今天两个按钮还是 alert 桩），页面没有对应槽位 |
| `feature_matrix` | 9 个**驼峰**键名（`pitchStd`…），没有任何中文标签。要显示就得替 AI 内部字段名定一套对外文案，那是新设计。接口 spec §36.2 已把它「该不该进对外契约」列为待确认 |
| `overall_confidence` | 最接近的槽位是 `#fusionTotal`，但那格写的是「加权总分」，而它是**置信度不是分数**——放进去就是错标 |
| `status` | 面板没有状态位。它判的是「这份还批不批」，而能点开就说明这份在待批列表里（F4 的口径） |
| `student_level` | 左下卡片（F4）也没显示，列表与面板都没有这一格 |
| `homework_id` | 与 `homework_title` 重复；右上的标题用后者 |
| `voice_comment_text` / `voice_comment_audio_id` | 语音点评（4.11）的槽位只有一个 `playVoiceComment()` 按钮，真播放要接音频接口（未排期） |
| `reviewed_at` | 同 `status` |

**「接口出了但页面不显示」不是遗漏。** 接口的出参面是给将来的写入回显（F6）与校准（F7）用的，接口 spec 已逐字段说明理由；页面只消费自己有槽位的那部分。要新增槽位请先改设计，不要在接入轮里顺手加。

### 3.12 两个 mock 常量整块删除

`HOMEWORKS`（`:613-617`）与 `SUBMISSIONS`（`:619-680`）删除，`:604-612` 的「模拟数据」段头注释一并改写。删完之后**这一页没有 mock 数据了**。

删得掉的前提已核实：**两个常量各只有 1 个使用点**，都在 `selectSubmission` 里（`SUBMISSIONS.find`、`HOMEWORKS[0].title`）。本次 `selectSubmission` 整体重写，两处自动消失；其余函数一个都没引用它们（`renderSubmitList` 在 F4 已改完）。

**保留 `confirmCDM` / `rejectCDM` / `submitReview` / `saveDraft` / `playVoiceComment` / `showAssignModal` 六个桩函数**——它们是 F6/F2 的落点，不是 mock 数据，别一起清掉。

---

## 4 实现设计

改动全部在 `homework.html` 的首段 `<script>` 内（另有两句静态文案与两个常量，见 §3.10 / §3.12）。

### 4.1 状态

```js
const DETAIL_IDLE_HTML = document.getElementById("emptyState").innerHTML;  // 首帧快照（§3.3）

let currentSubId = null;    // 选中的提交 id。F4 引入但从未被读，本次接上高亮（§3.8）
let detailState  = "idle";  // idle | loading | error | content
let detailData   = null;    // content 态的数据（接口 data 原样）
let detailError  = "";      // error 态的原因文案
let detailSeq    = 0;       // 自增序号，作废在飞的请求（§3.4）
```

`detailData` 与 `detailState === "content"` 必须同进同出：`renderDetail` 只在 `content` 态读 `detailData`，其余三态根本不读。

### 4.2 函数

| 函数 | 职责 |
|---|---|
| `selectSubmission(id)` | 重写。设 `currentSubId` → `renderSubmitList()`（刷高亮）→ `detailState="loading"; renderDetail()` → `fetchDetail(id)` |
| `fetchDetail(id)` | 新增。`const seq = ++detailSeq` → 角色分支（学生不发请求）→ `GET ${API_BASE}/api/submissions/${id}/detail` → `seq !== detailSeq` 则丢弃 → 置 `content` + `detailData` → `renderDetail()`；失败置 `error` + 原因 → `renderDetail()` |
| `retryDetail()` | 新增。`currentSubId == null` 直接 return；否则重走 `selectSubmission(currentSubId)` |
| `renderDetail()` | 新增。按 `detailState` 四分支：写 `#emptyState` 的 `innerHTML` / 切两块显隐 / `content` 态转 `fillDetail(detailData)` |
| `fillDetail(d)` | 新增。学生信息头 + 终审区回显（§3.7），再依次调下面五个区块渲染 |
| `renderDetailLyrics(d)` | 新增。4.4 空位 → 空态（§3.1） |
| `renderDetailFusion(d)` | 新增。4.5 空位 → 空态 + `#fusionTotal` / `#fusionPass` 都置 `—` |
| `renderDetailCdm(d)` | 新增。4.6 真渲染（§3.5） |
| `renderDetailBkt(d)` | 新增。4.7 真渲染（§3.6） |
| `renderDetailCalib(d)` | 新增。F7 空位 → 清空 `#calibGrid` + 空态 |
| `emptyBlock(text)` | 新增。区块级空态的一行 HTML（内联样式，不新增 CSS） |
| `selectHomework(hwId)` | 改。追加 §3.9 的五行右侧复位 |
| `renderSubmitList()` | 改。加 §3.8 的 `active` 一行 |

另加一处初始化：首段脚本末尾在 `renderSubmitList()` 那一句旁边补 `renderDetail()`（同时改写 `:1056-1058` 那段已经过时的注释），让两个面板各自只有一个绘制入口。

七个 detail 函数**只写自己那一块，互相不认识**（与 F4 的 `renderSubmitList` 同风格）：一块里的坏数据或异常不会让其它块渲染不出来，调试时也能只看一个函数。

`fetchDetail` 的角色分支与 F4 同源——接口挂 `@teacher_required`，学生调必 403，明知会被拒就不发：

```js
if (!currentUser || currentUser.role !== "teacher") {
  detailState = "error";
  detailError = "批改详情仅教师可见";
  renderDetail();
  return;
}
```

这条分支**在当前页面走不到**（学生看不到待批卡片，没有可点的入口），是照 F4 的「明知会 403 就不发」原则加的防御：万一将来列表对学生开放，右侧第一句该说的是权限，而不是让它去撞 403。

### 4.3 时序

```
页面加载
 └ 首段 <script> 顶层：抓 DETAIL_IDLE_HTML 快照
                       renderSubmitList()             // 左下「加载中…」
                       renderDetail()                 // 右侧 idle
 └ 第二段 <script>：/api/auth/me → currentUser = user → fetchHomeworks()
                     → selectHomework(第一份作业)
                        → 右侧复位（§3.9）
                     → fetchSubmissions(hwId)          // 左下真数据

点一张卡片
 → selectSubmission(id)
    → currentSubId = id; renderSubmitList()           // 高亮跟过来
    → detailState = "loading"; renderDetail()         // 先藏旧内容，再显示加载态
    → fetchDetail(id)
       → seq = ++detailSeq
       → GET /api/submissions/<id>/detail
       → seq !== detailSeq ? 丢弃 : 置 content + detailData + renderDetail()
```

### 4.4 HTML / CSS

- 删除 `:561` 整行（§3.10）。
- 改 `:566` 一句（§3.10）。
- 改写 `:604-612` 的段头注释，删除 `:613-617` 与 `:619-680`（§3.12）。
- 改写 `:1056-1058` 的注释，并补 `renderDetail()`。
- **不新增元素、不新增 CSS 规则。**

---

## 5 验证

本仓库无测试框架（无 `tests/`、`requirements.txt` 无 pytest），验证靠真接口 curl + 浏览器实操 + `check_db.py`。

1. **接口侧回归**（确认没碰后端）：起 `python app-d.py`，`teacher01` 登录取 5 份 detail——CDM 条数 `4/3/1/3/2`、BKT 条数 `2/0/0/3/0`；`/api/submissions/999/detail` 得 404；`stu001` 取 detail 得 403。
2. **教师端逐份核对**（`teacher01` 打开 `homework.html`，左侧 5 条待批）：
   - **24 刘思琪**：CDM **4** 条（含 0.52 那条「气息支撑不足」，胶囊显示 `52%`）、BKT 2 条（都为负向，箭头 ↘，条形在缩）、终审框预填 `75.2` + 评语。
   - **26 孙志远 / 27 赵雨桐 / 25 周明轩**：BKT 出「本次无 BKT 状态变化」；终审评语框为空（显示 placeholder）、评分预填各自的 `ai_score`（71.3 / 85.7 / 78.9）。
   - **23 李小燕**：CDM 3 条，第三条是 `low` / 0.45 → **卡片描边回落中性、胶囊是蓝的**（`conf low`）；BKT 3 条，其中「拖腔」`0.28 → 0.28` 走 `flat`（灰色、无箭头）；终审框预填 `82.5` + 评语。
   - **5 份都要**：🎵 歌词对比、⚖️ 加权融合、🎯 评分校准三块是空态文案；`:561` 那行公式**整行不在**了。
3. **左卡片 vs 右面板的口径差**：24 的卡片上 3 个标签、右侧 4 条；26 卡片 2 个、右侧 3 条；23 卡片 2 个、右侧 3 条——差的那条正是 ≤ 0.7 的三个。
4. **高亮**：点开某条后该卡片描边变蓝；点另一条，高亮跟过去（不残留两个）。
5. **切作业复位**：点开 24 → 点左侧 hw13 → 右侧回「选择左侧提交进行批改」，**不是**刘思琪的详情；点回 hw12 → 右侧仍是 idle（不自动重开 24），左下 5 条回来。
6. **竞态**：快速连点两张不同卡片（24 → 26）→ 右侧最终必须是 26，不能停在 24；连点同一张两次 → 不出现内容闪回。
7. **错误态**：停掉 Flask 后点卡片 → 右侧「⚠️ 加载失败」+「重试」；起回 Flask 点「重试」→ 正常加载。
8. **学生端**：`stu001` 登录 → 左下「待批改提交仅教师可见」、右侧停在 idle、Network 面板里**没有** `/detail` 请求。
9. **mock 残留清零**：控制台里 `SUBMISSIONS` 与 `HOMEWORKS` 均为 `undefined`；全页搜 `sub01` / `h01` 无命中。
10. `python scripts/check_db.py` 与基线一致（本次不动库，也不改模型）。
11. **不改库**：本次全程只读，跳过任何临时改库的兜底测试。

---

## 6 待文档方确认 / 已知但本次不改

1. **功能 4.10 / F7 的校准项取值集合没有定义（本次新发现，已登记为 DOC_ISSUES 第 37 条）。** F7 在《5-接口清单》里的全部描述是「评分校准勾选（功能 4.10），写 `score_calibrations`」，而 `score_calibrations` 只有一列 `bias_mode VARCHAR(10)`（注释给的是 `high`/`low`/`ok`）**且每提交一行**；页面 mock 的校准块是**按维度勾三个框**（音准 / 气息 / 咬字）。两者结构对不上：表里存不下「音准偏高」和「气息偏高」同时勾的情形。真库该表只有 1 行（`submission_id=24, bias_mode='high'`）。F5 按「接口不出校准」处理，本块出空态。
2. **`feature_matrix` 的对外文案与契约地位**：9 个驼峰键没有任何中文标签，本次不显示（§3.11）。接口 spec §36.2 已把它「该不该进对外契约」列为待确认——两个问题要一起答：进不进契约、进的话键名与中文文案谁定。
3. **「通过并发布」按钮现在会说假话。** `submitReview()` 是 alert 桩，文案却写「BKT 状态已更新」；而 F5 实测 `reviewed_at` 5 份全为 `null`、`status` 5 份全是 `ai_scored`——库里**没有任何提交被终审过**。本次不改（改它就是替 F6 写交互），登记在此。
4. **4.4 逐字偏差的交付时点**：接口 spec §36.1 已登记。本次前端的落点是 `renderDetailLyrics` 里那段空态；**非空分支故意不写**——从当前接口拿到非空 `lyrics` 是不可能的（backend 里写死 `[]`），为看不见的形状写渲染代码只会写错。F3 把 B 组结果落进 `ai_detail` 后，在那里补真渲染。
