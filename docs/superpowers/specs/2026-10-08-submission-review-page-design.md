# F6 教师终审批改前端接入（`homework.html` 终审区）设计

## 1 背景、目标与非目标

### 1.1 目标

把 `homework.html` 右侧批改详情面板的终审区接到已经落地的 `POST /api/submissions/<id>/review`
（F6，后端设计见 `2026-10-08-submission-review-api-design.md`，代码见 `app/api/homeworks.py:62`）。

本轮只接**一个按钮**：`✅ 通过并发布`。接完之后教师能在页面里真的完成一次终审，并且
批完的条目会从左侧待批列表消失、作业列表的待批数与状态跟着变。

### 1.2 非目标

- **不接「💾 保存草稿」**（用户本轮决定）：`submissions.status` 没有 `draft` 档，F6 的
  「调用即 `reviewed`」也表达不了草稿。保留 alert 桩，登记 `DOC_ISSUES`。
- **不接「🎙️ 语音」**（用户本轮决定）：4.11 要的是语音转文字，项目里没有 ASR 组件；教师语音
  点评音频的上传口径、学生能不能播（B5 的 `access`）也都没定。保留 alert 桩，登记 `DOC_ISSUES`。
- 不做 F7（`POST /api/submissions/<id>/calibration`），`#calibGrid` 维持空态。
- 不改后端任何文件（F6 后端已交付并验过）。
- 不动 `#cdmList` 里 `confirmCDM` / `rejectCDM` 两个 alert 桩、不动 `showAssignModal`。

### 1.3 与 F5 那一轮的关系

F5 把右侧面板接到了 `GET /api/submissions/<id>/detail`，终审区当时**只做回显**
（`homework.html:1110-1115`），并且刻意**不按 `status`/`reviewed_at` 推断「还能不能改」**——
页面上那两个输入框现在永远可编辑，本轮沿用这个口径（见 3.9）。

F6 后端那一轮的设计里写过「不动 `homework.html`（三个 alert 桩原样留着）」。本设计**取代
那句话**，范围限于 `submitReview` 一个函数。

---

## 2 文档真源与页面现状

### 2.1 文档只说了功能点，没说过交互

《PRD》里这一块对应三个功能点：

| 功能 | 描述 | 本轮 |
|---|---|---|
| 4.8 | 教师终审：点评 + 终审评分 | 接 |
| 4.9 | 快捷评语 / 一键通过 | 只接「写分数与评语」，**一键通过没有独立入口**（3.3） |
| 4.11 | 语音点评（语音识别转文字） | 不接（1.2） |

三个功能点都只有一句话，**没有任何一条规定按钮文案、字段必填性、成功后的页面行为**。
本轮自拟的部分全部列在第 3 节。

### 2.2 页面现状（`homework.html`，1250 行）

终审区 markup 在 `:579-595`：

```html
<textarea id="teacherComment" placeholder="在此输入您的终审点评..."></textarea>
<input type="number" id="finalScore" value="82.5" min="0" max="100" step="0.1">
<span class="hint">AI建议: <span id="aiSuggestedScore">82.5</span>分（可修改）</span>
<button class="btn-success" onclick="submitReview()">✅ 通过并发布</button>
<button class="btn-secondary" onclick="saveDraft()">💾 保存草稿</button>
<button class="btn-secondary" style="flex:0.6" onclick="playVoiceComment()">🎙️ 语音</button>
```

三个处理函数都在 `:1145-1156`，都是单纯的 `alert`：

| 函数 | 行 | 现状 |
|---|---|---|
| `submitReview()` | 1145 | `alert("✅ 终审已发布\n终审评分: ${score}分\n点评已保存，BKT 状态已更新")` |
| `saveDraft()` | 1150 | `alert("💾 草稿已保存")` |
| `playVoiceComment()` | 1154 | `alert("🎙️ 语音点评录制中...（需接入音频录制 API）")` |

**注意 `submitReview` 现在那句 alert 是假的**——它宣称「点评已保存，BKT 状态已更新」，而实际上
什么都没发生（BKT 更不归本接口管）。接上真接口后这句文案连同 alert 一起消失。

回显侧在 `fillDetail`（`:1101-1123`）：

```js
document.getElementById("teacherComment").value = d.teacher_comment || "";
document.getElementById("finalScore").value = (d.teacher_score ?? d.ai_score ?? "");
document.getElementById("aiSuggestedScore").textContent = (d.ai_score == null) ? "—" : d.ai_score;
```

也就是说：**打开一条待批提交时，终审分预填的是 `teacher_score`，没有才退到 `ai_score`**，
评语预填已有的 `teacher_comment`。本设计不改这三行。

### 2.3 F6 后端已定的契约（复述，前端按这个写）

`POST /api/submissions/<int:submission_id>/review`，`@login_required` + `@teacher_required`，
统一信封 `{"code","message","data"}`。请求体四个字段**全部可选**：

| 字段 | 说明 |
|---|---|
| `teacher_score` | float，0–100 |
| `teacher_comment` | str |
| `voice_comment_text` | str |
| `voice_comment_audio_id` | int，必须能在 `audio_files` 里查到 |

**PATCH 语义**（后端 spec 3.2）：字段**不出现** = 不动该列；字段**显式给 `null`** = 清空该列。
`{}` 合法，等于「一键通过」——只把 `status` 推成 `reviewed`、写 `reviewed_at`，一个内容列都不碰。

响应 `data` 是**只含本接口写下去的那几个字段**的小对象（不是 F5 的全量详情）：

```
submission_id, status, reviewed_at, teacher_score, teacher_comment,
voice_comment_text, voice_comment_audio_id
```

失败（后端 spec §5.3 实测）：

| 场景 | HTTP | `message` |
|---|---|---|
| 未登录 | 401 | `未登录` |
| 学生登录 | 403 | `需要教师权限` |
| 提交不存在 | 404 | `提交不存在` |
| 路径 id 非数字 / 负数 | 404 | `接口不存在`（`<int:...>` 在路由层挡掉） |
| `teacher_score` 越界（101 / -0.5） | **422** | `teacher_score: 终审评分必须在 0 到 100 之间` |
| `teacher_score` 非数字 | 422 | 英文原文（`float_parsing` 未映射，后端 spec 3.7） |
| `voice_comment_audio_id` 查不到 | 422 | `语音点评音频不存在` |

**越界回 422 而不是 400**——这是核对后纠正的一处：本项目的 422 是「入参能解析但语义不合法」，
400 留给「缺文件」那类（B1）。

### 2.4 两处已经送到页面、但页面从没渲染的东西

1. **`voice_comment_text` / `voice_comment_audio_id`**：F5 的出参里有这两列
   （`app/schemas/homework.py:269-270`，F5 spec 还专门写了「不给的话功能 4.11 的音频就取不回来」），
   但全文件 grep `voice_comment` 的结果是**零处渲染**。也就是说 4.11 的读侧在页面上也没有出口，
   不只是写侧没有。
2. **作业状态 `closed` 的中文文案**：`HW_STATUS_TEXT = { grading: "批改中", ongoing: "进行中",
   closed: "已截止" }`（`:664`）。F6 之前 `closed` 只可能来自「截止时间已过」；F6 之后它
   第一次可以因为**批改完成**而出现（后端实测：hw12 的 5 条全批完后 `GET /api/homeworks`
   返回 `status="closed"`、`pending_review_count=0`）。页面会把一份刚批完、截止日期还没到的
   作业显示成「已截止」。这是文案问题，登记 `DOC_ISSUES`（第 7 节），本轮不改映射。

---

## 3 自拟口径（文档均未定义）

| # | 事项 | 本轮口径 | 理由 |
|---|---|---|---|
| 3.1 | 接哪些按钮 | **只接「✅ 通过并发布」** | 用户本轮决定；另两个缺承载物（1.2） |
| 3.2 | 请求体发什么 | **两个字段都发**（`teacher_score` + `teacher_comment`），不发语音两个 | 终审区的语义就是「以页面上的值为准」，页面预填了 `teacher_score ?? ai_score`，教师点按钮即确认这个分。见 4.2 |
| 3.3 | 「一键通过」入口 | **不提供独立入口** | 4.9 的「一键通过（终审保留）」在页面上没有对应控件；页面只有一个按钮，它总会把终审分写下去。要真做就得加第二个按钮，属需求方决定（第 8 节） |
| 3.4 | 成功后的页面 | 左侧待批列表 + 作业列表**都刷新**；右侧**复位回 idle** | 用户本轮选定「刷新两条列表」。右侧复位是因为被批的那条已离开待批列表，留着内容会让左下没有对应的高亮卡片 |
| 3.5 | 刷作业列表时不抢选中 | 给 `fetchHomeworks` 加 `keepSelection` 参数，刷新时设为 `true` | `fetchHomeworks` 结尾是 `selectHomework(items[0].homework_id)`——直接复用会把教师看的作业**跳回第一份**（4.4） |
| 3.6 | 提交期间教师切了别的提交 | **只刷左侧，不动右侧** | 否则会把教师刚点开的另一名学生清成空态。同 F5 `detailSeq` 那条竞态的口径 |
| 3.7 | 防双击 | 按钮 `disabled` + 文案改「⏳ 发布中…」，`finally` 里复位 | 页面其它按钮都没防，但本按钮会写库，重复点击就是两次终审 |
| 3.8 | 错误呈现 | `alert` 后端 `message`；**401 例外，直接跳 `/login.html`** | `alert` 是本页动作类反馈的既有形态（`confirmCDM`/`rejectCDM`/`showAssignModal`）。401 是「会话没了」不是「操作错了」，本页第二段 `<script>` 对 `/api/auth/me` 失败的既有处理就是 `location.replace('/login.html')` |
| 3.9 | 前端要不要做范围校验 | **不做**，交给后端 422，原样显示它的中文 message | `input[type=number][min][max]` 只约束上下箭头，手输 101 时 `.value` 仍是 `"101"`、也不会有 form 提交拦它。范围规则的真源在后端，前端再写一遍就是两处漂移。终审区「永远可编辑」的口径也照 F5 不动（`:1110` 那段注释） |
| 3.10 | 空值怎么发 | 输入框内容 **trim 后为空 → 发 `null`**；否则`teacher_score` 走 `Number()`、`teacher_comment` 发 trim 后的原串 | 空串会往 TEXT 列写一个长度 0 的字符串，「没写点评」与「写了个空」在库里成了两种值。`teacher_score` 尤其不能把 `""` 喂给 `Number()`——那是 **0 分**，等于替教师打了一个 0 |
| 3.11 | 用不用响应体 | **不用**，只看 `res.ok` | 两条列表刷完就是最新的；拿响应去改 DOM 得再定义一套「回显优先还是列表优先」 |

---

## 4 实现设计

### 4.1 落点

**只改一个文件：`homework.html`。** 没有新文件、没有新 CSS、没有新依赖。

| 位置 | 改动 |
|---|---|
| `:591` | 按钮加 `id="btnSubmitReview"`（3.7 要拿它改 `disabled` 与文案） |
| `:728` | `fetchHomeworks` 加形参 `keepSelection = false` |
| `:751` | `if (items.length)` → `if (items.length && !keepSelection)` |
| `:1125-1127` 之间 | 新增两个纯函数 `textOrNull` / `scoreOrNull` |
| `:1145-1148` | `submitReview` 整个替换成真实现 |

`saveDraft` / `playVoiceComment`（`:1150-1156`）**一行不动**。

### 4.2 请求体构造（为什么两个字段都发）

页面上的终审区是「一份要点确认的稿子」：打开时就预填了 `teacher_score ?? ai_score` 与已有的
`teacher_comment`。教师点「通过并发布」的语义是**认可屏幕上这两个值**，而不是「我只改了其中
一个」。所以两个字段都发，走后端 PATCH 的「显式给出」分支。

这带来一个与「一键通过」的差别，需要写明：把终审分留空（输入框清空）再点按钮，发的是
`{"teacher_score": null, "teacher_comment": null}`，后端会把 `teacher_score` 写成 `NULL`。
这是**符合页面语义**的——教师确实把分删了——不是 bug。要「保留原分只推进状态」得走 `{}`，
而页面上没有这个入口（3.3）。

### 4.3 两个纯函数（`:1125-1127` 之间，交互操作区开头）

```js
// 终审区两个输入框的空值口径（spec 3.10）。都 trim 后判空、一律发 null 而不是空串：
// 空串会往 TEXT 列里写一个长度 0 的字符串，「老师没写」与「老师写了个空」在库里
// 就成了两种值，而后端 PATCH 的「显式 null」正好是清空。
function textOrNull(v) {
  const s = (v || "").trim();
  return s === "" ? null : s;
}

// #finalScore 是 <input type="number">，清空时 .value 是**空串**（不是 "0"）。
// 空串不能喂给 Number()——那得到的是 0，等于替教师打了一个 0 分。
// 越界（手输 101）不在这里拦，交给后端 422（spec 3.9）。
function scoreOrNull(v) {
  const s = (v || "").trim();
  return s === "" ? null : Number(s);
}
```

### 4.4 `fetchHomeworks` 加参数（`:728` 与 `:751`）

```js
async function fetchHomeworks(keepSelection = false) {
  ...
    // keepSelection：终审成功后刷新用。默认（页面加载）要自动选中第一份；
    // 刷新时若照做，教师正看着 hw13 会被跳回 hw12（F1 排序里第一份），
    // 因为 items[0] 与 currentHwId 无关。renderHwList 自己会按 currentHwId
    // 刷选中态，所以只重渲列表就够。
    if (items.length && !keepSelection) selectHomework(items[0].homework_id);
```

页面加载时那一句 `fetchHomeworks()`（`:1208`）**不改**——默认值 `false` 就是原来的行为。

### 4.5 `submitReview` 实现（替换 `:1145-1148`）

```js
// 教师终审：POST /api/submissions/<id>/review（F6，统一信封）。
// 只发终审区那两个字段——语音点评本轮不做（spec 3.1）。
async function submitReview() {
  // 没有选中提交就不发。按钮在 #reviewContent 里，idle/error/loading 三态整块
  // 是 display:none，正常点不到；这一句防的是从控制台直接调，口径同 retryDetail。
  if (currentSubId == null) return;

  // 记下本次提交的目标 id：await 期间教师可能已经点了别人（spec 3.6）。
  const id = currentSubId;
  const btn = document.getElementById("btnSubmitReview");
  const payload = {
    teacher_score: scoreOrNull(document.getElementById("finalScore").value),
    teacher_comment: textOrNull(document.getElementById("teacherComment").value),
  };

  if (btn) { btn.disabled = true; btn.textContent = "⏳ 发布中…"; }
  try {
    const res = await fetch(`${API_BASE}/api/submissions/${id}/review`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    // 401 单独走：会话失效不是「操作错了」，弹一句「未登录」会让人以为是自己点错。
    // 本页对 401 的既有处理就是跳登录页（第二段 <script> 的 /api/auth/me 失败）。
    if (res.status === 401) {
      location.replace("/login.html");
      return;
    }
    if (!res.ok) {
      // 错误信封里后端自己写了 message（404「提交不存在」/ 422「终审评分必须在
      // 0 到 100 之间」），原样显示比自己拼一句 HTTP xxx 有用——口径同 fetchDetail。
      const b = await res.json().catch(() => null);
      throw new Error((b && b.message) || `HTTP ${res.status}`);
    }

    // 成功。响应体不用（spec 3.11）：两条列表刷新完就是最新的。
    if (currentSubId === id) {
      // 教师还停在被批的那条 → 右侧整块复位回 idle（spec 3.4）。selectHomework
      // 会顺带重拉一次 F4，所以这条分支里不再单独调 fetchSubmissions。
      selectHomework(currentHwId);
    } else {
      // 提交期间教师已经点了别人或换了作业 → 只刷左侧，别把他正在看的那一份清掉。
      fetchSubmissions(currentHwId);
    }
    fetchHomeworks(true);        // F1 的待批数与作业状态（spec 3.5）
  } catch (e) {
    alert(`❌ 终审发布失败\n${e.message || "网络异常"}`);
  } finally {
    // 复位按钮。上面可能已经把右侧复位成 idle，#reviewContent 整块藏了起来
    // （按钮不可见），但元素还在、文案照样写回，下次进 content 态时是正常样子。
    if (btn) { btn.disabled = false; btn.textContent = "✅ 通过并发布"; }
  }
}
```

三点要说明：

- `selectHomework(currentHwId)` 与 `fetchSubmissions(currentHwId)` 都**不 await**——与
  `selectHomework` 内部调 `fetchSubmissions` 的写法一致，二者各自管自己的竞态
  （`fetchSubmissions` 有 `currentHwId !== hwId` 的兜底）。
- `selectHomework` 里那句 `renderHwList(hwItems)` 用的是**旧缓存**，会先画一帧旧数据，
  紧接着 `fetchHomeworks(true)` 用新数据重画。多一帧，不闪错值。
- `submitReview` 不碰 `detailSeq`。右侧的复位走 `selectHomework`，那里本来就 `detailSeq++`。

### 4.6 状态变化后的页面表现（实测预期）

教师批掉 hw12 的最后一条时：

| 位置 | 变化 |
|---|---|
| 左侧待批列表 | 该条消失；全员批完时整块显示「暂无待批改提交」 |
| 右侧面板 | 复位回「选择左侧提交进行批改」 |
| 作业列表 hw12 | 待批数 5→4→…→0；状态由「批改中」变「已截止」（文案问题见 2.4） |
| 顶部计数 | 「N项进行中」只数 `ongoing`，批改中与已截止都不算，所以批 hw12 **不会**改这个数 |

---

## 5 验证方案

本项目没有测试框架（不装 pytest，前端也没有 jest）。沿用 F5 前端那一轮建好的夹具：
`/tmp/f5fe/harness.mjs` + `api.mjs`（`node:vm` 的 `createContext` + `runInContext` 跑页面里
**真正的那个 `<script>` 块**，配一个极简假 DOM，零依赖、node 直接跑）。本轮新建
`/tmp/f6fe/`，从 `harness.mjs` 复制（假 DOM 要补两样：`HTMLInputElement.value` 的读写、
`location.replace` 的桩）。

### 5.1 纯函数与分支（夹具，不碰真库）

| # | 用例 | 期望 |
|---|---|---|
| 1 | `scoreOrNull("")` | `null`（**不是 0**） |
| 2 | `scoreOrNull("  ")` | `null` |
| 3 | `scoreOrNull("88.25")` | `88.25`（数字，不是字符串） |
| 4 | `textOrNull("   ")` | `null` |
| 5 | `textOrNull(" 拖腔再稳一点 ")` | `"拖腔再稳一点"`（trim 过） |
| 6 | `currentSubId = null` 时调 `submitReview()` | **一次 fetch 都不发** |
| 7 | 成功路径：桩 fetch 回 `200 {code:0,...}` | fetch 的 URL 是 `/api/submissions/<id>/review`；`method` 是 `POST`；`credentials` 是 `same-origin`；`headers["Content-Type"]` 是 `application/json`；body 是 4.2 说的两字段 |
| 8 | 成功且 `currentSubId` 未变 | 右侧回 idle；F4 被重拉（走 `selectHomework`）；F1 被重拉且**不带**自动选中 |
| 9 | 成功但提交期间 `currentSubId` 改成了别的 id | 只重拉 F4；**右侧状态不变**（仍是那名学生的 content） |
| 10 | 桩 fetch 回 `401` | `location.replace` 收到 `"/login.html"`；不弹 alert |
| 11 | 桩 fetch 回 `422 {message:"teacher_score: 终审评分必须在 0 到 100 之间"}` | alert 的正文含这句**后端原话**；左侧列表未被重拉 |
| 12 | 桩 fetch 回 `404 {message:"提交不存在"}` | 同上，alert 含「提交不存在」 |
| 13 | 桩 fetch 抛网络异常 | alert 含「网络异常」 |
| 14 | 飞行中（fetch 未 resolve）读按钮 | `disabled === true` 且文案是「⏳ 发布中…」 |
| 15 | 失败后读按钮 | `disabled === false` 且文案回到「✅ 通过并发布」（`finally` 生效） |
| 16 | `fetchHomeworks(true)` 与 `fetchHomeworks()` | 前者**不调** `selectHomework`；后者调 `selectHomework(items[0].homework_id)` |

用例 8/9 的差别是本轮唯一的竞态点，必须两条都测——只测 8 会让 9 的缺陷（把教师正在看的
内容清掉）露不出来。

### 5.2 真链路（会写库，**必须复原**）

前置：后端 + 教师 Cookie。F6 接口本身已由后端那一轮用 15 条 curl 验过，这轮**只验前端发出去
的请求体对不对**，所以只需两条：

| # | 操作 | 期望 |
|---|---|---|
| 17 | 页面上打开 `submissions.id=25`（真库里它 `teacher_score`/`teacher_comment` 都是 NULL），填入分数与评语，点「通过并发布」 | `POST` 的 body 恰好是 `{"teacher_score":<数字>,"teacher_comment":"<串>"}`（浏览器 Network 面板或后端访问日志核对） |
| 18 | 直接 `psql` 查 25 号 | `status='reviewed'`、`reviewed_at` 非空、两个内容列等于页面填的值、`voice_comment_*` **仍为 NULL**（本轮不发这两个字段） |

**复原纪律（同 `DOC_ISSUES` 第 35.5 条）**：验之前按 id 抓一份 `submissions` 的
`(teacher_score, teacher_comment, voice_comment_text, voice_comment_audio_id, status, reviewed_at)`
快照，验完**按抓到的 id 逐列改回**。绝不 `DELETE FROM submissions WHERE ...`、绝不整表清空。
本次要动的是 25 号（若 17 号用例选了别的 id，按实际抓到的改）。

### 5.3 人在浏览器里走一遍

用 `/browse` 起真服务走一遍完整流程：教师登录 → 作业列表选 hw12 → 左侧点一条 → 右侧填分与
评语 → 通过并发布 → 确认「该条从左侧消失、右侧回空态、作业列表待批数减 1」。这一步会真写库，
同样按 5.2 的纪律复原。

---

## 6 明确不做

- 不接 `saveDraft()`、不接 `playVoiceComment()`（1.2）。
- 不做 F7、不渲染 `#calibGrid`、不写 `score_calibrations`。
- 不动 `confirmCDM` / `rejectCDM` / `showAssignModal` 三个 alert 桩。
- 不给 `teacher_comment` / `finalScore` 加「已终审则禁用」的逻辑（照 F5 `:1110` 的口径，
  页面不替 F6 定终审状态机）。
- 不渲染 `voice_comment_text` / `voice_comment_audio_id`（F5 已经送来了，但本轮不做 4.11）。
- 不改 `HW_STATUS_TEXT` 的 `closed: "已截止"` 文案（2.4，要改得文档方先定）。
- 不改后端、不改 `schema.sql`、不新增 CSS 类、不引入任何前端依赖。

---

## 7 要登记进 `DOC_ISSUES.md` 的

**新增第 39 条**（F6 前端接入），含四点：

1. **「保存草稿」在文档与库表里都没有承载物**：4.9 列了这个动作，但 `submissions.status`
   只有 `submitted / ai_scored / reviewed` 三档注释（连 `draft` 的影子都没有），F6 的语义
   又是「调用即 `reviewed`」。按钮留在页面上但它做不到名副其实的事——要么定义草稿态，要么
   从需求里去掉。
2. **4.11 的读侧在页面上也没有出口**：F5 的详情出参早就把 `voice_comment_text` /
   `voice_comment_audio_id` 送到了页面（`app/schemas/homework.py:269-270`），而 `homework.html`
   里对这两个名字的渲染是**零处**。加上没有 ASR 组件、没有教师语音的上传口径、B5 的私有
   音频学生能不能播也没定，4.11 目前是「写不了也读不出」。
3. **F6 让 `closed` 这一档第一次可以由「批改完成」产生**：F1 的映射把 `closed` 显示成
   「已截止」，而 F6 之后一份截止日期还没到的作业也会显示成「已截止」（后端实测 hw12 批完
   5 条即转 `closed`）。同一个状态值现在承载两种语义，页面无法区分。
4. **终审完成没有任何通知学生的途径**：清单里没有通知类接口，`submissions` 也没有
   `notified_at` 之类的列。教师点了「通过并发布」，学生在页面上看不到任何变化。

---

## 8 待文档方确认

1. **「保存草稿」是不是一个正式功能点？** 若是，草稿存在哪（`status` 加一档 / 另起一张表 /
   前端本地）？若不是，页面上的按钮该删还是该换个名字？
2. **4.11 的语音转文字用什么组件？** 教师语音点评音频的上传走不走 B1
   （`POST /api/audio/upload`）？`access` 设成什么，学生（非上传者）才播得到？
3. **终审能不能撤回/退回？** F6 只支持继续覆盖成 `reviewed`，改不回待批改。
4. **4.9 的「一键通过」在页面上要不要有独立入口？** 现在只有一个按钮，它总会把终审分写下去，
   与「终审保留」并不等价。
5. **终审评分是否必填？** 4.8 的描述里带分数，4.9 的「一键通过」又暗示可以不打分。本轮口径是
   「留空即清空该列」（3.10）。
6. **批改完成后的作业状态该显示什么？** 现在会显示「已截止」（第 7 节第 3 点）。
7. **教师「通过并发布」之后要不要通知学生？** 当前无任何途径（第 7 节第 4 点）。
