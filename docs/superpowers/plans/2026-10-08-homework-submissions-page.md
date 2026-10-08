# 待批改提交列表（F4）前端接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `homework.html` 左侧「待批改提交」卡片从 mock 常量 `SUBMISSIONS` 换成 F4 真接口 `GET /api/homeworks/<id>/submissions`，并补上接口必需的作业选择交互。

**Architecture:** 纯前端，**只改 `homework.html` 一个文件**，不碰后端。三层：状态变量（`submitItems`/`submitNotice`/`currentHwId`/`hwItems`）→ 渲染层（`renderSubmitList` 改读状态、四态渲染、兜底、severity 映射）→ 数据层（`fetchSubmissions` 拉数据、`selectHomework` 串起作业切换）。右侧批改详情面板**保持 mock 不动**（那是 F5），`SUBMISSIONS`/`HOMEWORKS` 两个常量一行不删。

**Tech Stack:** 原生 HTML/CSS/JS（无框架、无构建、无 npm），ECharts 无关，Flask 后端已就绪。

**依据 spec:** `docs/superpowers/specs/2026-10-08-homework-submissions-page-design.md`

## Global Constraints

- **不新增任何依赖、不新增构建步骤、不引入框架。** 本页面是无构建的纯静态 HTML，改动只允许写进 `homework.html` 内嵌的 `<style>` 与 `<script>`。
- **不新增测试框架。** 本仓库没有 `tests/`、`requirements.txt` 里也没有 pytest。验证一律靠**浏览器实操 + 对真接口的 curl**。不要 `pip install pytest`。
- **`API_BASE` 保持空串**（`homework.html:682`，同源、经 nginx 的 `/api` 代理）。**不要改成 `location.host + ':8877'`**：那是跨源请求，跨源 fetch 默认不带 Cookie，后端 `login_required` 只会看到空 session 并回 401。
- **所有进 `innerHTML` 的字段一律过 `esc()`**（`:699` 已定义）。姓名、标签文字、作业标题都来自数据库。
- **空值兜底用 `||` 不用 `??`**：`students.avatar` 有空串（不是 NULL）。
- **不删 `SUBMISSIONS` / `HOMEWORKS` 两个 mock 常量**，也不要「顺手清理」`selectSubmission` 的函数体、`.submit-item.active` 与 `.hw-item.active` 的样式。它们是 F5 的落点，评审时不要当死代码处理。
- **不改库。** 本次无任何数据库改动；第 3 个任务的 `check_db.py` 应当与基线完全一致。
- 页面中文 UI、代码注释用中文；标识符保持英文。

---

## 文件结构

| 文件 | 职责 | 本次动作 |
|---|---|---|
| `homework.html` | 作业布置与批改页（单文件自包含、无构建） | **修改**，全部改动都在这里 |

无新增文件。

---

### Task 1: 渲染层——`renderSubmitList` 改读状态变量

`renderSubmitList` 现在无参数、直接读 `SUBMISSIONS`。本任务把它改成读两个模块级状态变量，并一次性补齐四态渲染、字段兜底、severity 映射、时间格式化。做完后**页面行为与改前一致**（`submitItems` 还是 null，显示「加载中…」），但渲染层已经能正确渲染 F4 的形状——这是可以单独验证的中间态。

**Files:**
- Modify: `homework.html`（CSS `:272` 附近、HTML `:511`、状态变量 `:687`、`renderSubmitList` `:782-798`）

**Interfaces:**
- Consumes: `esc()`（`homework.html:699`，已存在）
- Produces:
  - `let submitItems` — `null` = 还没拉回来（加载中）；数组 = 已拉回来（可能为空数组）
  - `let submitNotice` — `""` = 正常渲染列表；非空 = 整块替换成这句提示
  - `function renderSubmitList(): void` — 唯一渲染 `#submitList` 的地方，别处只改上面两个变量再调它
  - `function fmtTime(s: string|null): string` — ISO-8601 → `"08-01 00:00"`，null → `"—"`
  - `const SEV_CLS` — `{high:"danger", medium:"warn", low:"info"}`

- [ ] **Step 1: 加 `.tag.neutral` 这一行 CSS**

找到 `homework.html:272`：

```css
.submit-item .tags .tag.info{background:rgba(0,102,179,0.10);color:var(--primary)}
```

在它**下一行**插入：

```css
.submit-item .tags .tag.neutral{background:var(--bg-secondary);color:var(--text-muted)}
```

**为什么要有它**：接口把 `severity` 作为语义值透传（`high`/`medium`/`low`），未知档（含后端在取不到 `status` 时给的 `"unknown"`）需要中性色。现有三档 `danger`/`warn`/`info` 里没有中性色，直接复用 `info` 会把「未知档」和「low」混成一色。若评审认为不值得加这一行，删掉它、并把 Step 4 里 `SEV_CLS[t.severity] || "neutral"` 的兜底改成 `|| "info"`。

- [ ] **Step 2: 给卡片右上角加计数容器**

找到 `homework.html:511`：

```html
            <span style="font-size:11px;color:var(--text-muted)">AI已初评</span>
```

替换为：

```html
            <span style="font-size:11px;color:var(--text-muted)" id="subSummary"></span>
```

与作业列表卡片右上角的 `#hwSummary`（`:497`）对称，由 `renderSubmitList` 填「N条待批」。

**初始内容留空**，不要写「AI已初评」之类的静态文案——那会和「仅教师可见」「加载中…」并排出现，读起来自相矛盾。

- [ ] **Step 3: 加两个状态变量**

找到 `homework.html:687`：

```js
let currentSubId = null;
```

替换为：

```js
let currentSubId = null;
// 待批提交（F4）。这两个变量是 #submitList 的唯一数据源，改完都要调
// renderSubmitList()——渲染逻辑只在那一个函数里，别处不要再直接写 innerHTML。
//   submitNotice 非空 → 整块显示这句提示（仅教师可见 / 加载失败）
//   submitItems 为 null → 「加载中…」
//   submitItems 为 []   → 「暂无待批改提交」
//   submitItems 有元素 → 渲染列表
let submitItems = null;
let submitNotice = "";
```

**`null` 与 `[]` 必须分开**：只用一个变量的话，「还没拉回来」与「拉回来了但是空的」长得一样，切换作业时会先闪一下「暂无待批改提交」再变成真列表。

- [ ] **Step 4: 重写 `renderSubmitList`**

找到 `homework.html:782-798` 整个函数：

```js
function renderSubmitList() {
  const container = document.getElementById("submitList");
  container.innerHTML = SUBMISSIONS.map((sub, idx) => {
    const tagsHtml = sub.tags.map(t => `<span class="tag ${t.cls}">${t.text}</span>`).join("");
    return `
      <div class="submit-item ${sub.id === currentSubId ? 'active' : ''}" onclick="selectSubmission('${sub.id}')">
        <div class="avatar">${sub.student.avatar}</div>
        <div class="info">
          <div class="name">${sub.student.name}</div>
          <div class="sub">${sub.time}</div>
          <div class="tags">${tagsHtml}</div>
        </div>
        <div class="score">${sub.ai_score}</div>
      </div>
    `;
  }).join("");
}
```

替换为：

```js
// severity → CSS 类。接口透传语义值（high/medium/low），配色是页面的事（spec 3.4）。
// 取到不认识的档用 neutral 渲染，**不做白名单过滤**——滤掉一个未预期的分级
// 会让标签凭空消失。
const SEV_CLS = { high: "danger", medium: "warn", low: "info" };

// "2026-08-01T00:00:00" → "08-01 00:00"，null → "—"。
// **不走 new Date()**：串里没有时区后缀，而库里存的本来就是北京时间
// （PostgreSQL server timezone = Asia/Shanghai）。Date 会按浏览器本地时区解析、
// 再按本地时区输出，非 +08:00 的机器上显示会漂。切片没有这个问题（spec 3.5）。
function fmtTime(s) {
  return s ? String(s).slice(5, 16).replace("T", " ") : "—";
}

function renderSubmitList() {
  const container = document.getElementById("submitList");
  const summary = document.getElementById("subSummary");
  if (!container) return;

  // 空态/提示态一律清空右上角计数：留一个数字会与「仅教师可见」并排出现，
  // 读起来像「确实没有待批」，而实际是「没权限看」（与 fetchHomeworks 同源）。
  if (submitNotice) {
    container.innerHTML =
      `<div style="padding:32px;text-align:center;color:var(--text-muted)">${esc(submitNotice)}</div>`;
    if (summary) summary.textContent = "";
    return;
  }
  if (submitItems === null) {
    container.innerHTML =
      `<div style="padding:32px;text-align:center;color:var(--text-muted)">加载中…</div>`;
    if (summary) summary.textContent = "";
    return;
  }
  if (!submitItems.length) {
    container.innerHTML =
      `<div style="padding:32px;text-align:center;color:var(--text-muted)">暂无待批改提交</div>`;
    if (summary) summary.textContent = "";
    return;
  }

  container.innerHTML = submitItems.map(it => {
    // tags 不截断：接口按置信度降序给全量（刘思琪 3 条）。.tags 本就是
    // flex-wrap，让它换行，不要 slice——截掉哪条纯看运气（spec 3.6）。
    const tagsHtml = (it.tags || []).map(t =>
      `<span class="tag ${SEV_CLS[t.severity] || "neutral"}">${esc(t.label)}</span>`
    ).join("");
    // avatar 可能是**空串不是 NULL**（students.id=2 张三那个种子），必须用 ||
    // 兜——?? 只兜 null/undefined，兜不到空串（spec 3.6）。
    const avatar = it.student_avatar || "🎭";
    const name = it.student_name || "未知学生";
    const score = (it.ai_score === null || it.ai_score === undefined) ? "—" : it.ai_score;
    return `
      <div class="submit-item" onclick="selectSubmission(${it.submission_id})">
        <div class="avatar">${esc(avatar)}</div>
        <div class="info">
          <div class="name">${esc(name)}</div>
          <div class="sub">${esc(fmtTime(it.submitted_at))}</div>
          <div class="tags">${tagsHtml}</div>
        </div>
        <div class="score">${esc(score)}</div>
      </div>
    `;
  }).join("");

  if (summary) summary.textContent = `${submitItems.length}条待批`;
}
```

**三点刻意为之，评审时不要「优化」回去：**

1. **没有 `active` 类**。改前有 `${sub.id === currentSubId ? 'active' : ''}`，改后去掉了。F4 出的 id 是 `23/24/…`，而 `currentSubId` 装的是 mock 的 `sub01`/`sub02`，两者永不相交——留着这行判断等于永远求值为 false 的死表达式。真列表里**不会有任何卡片高亮**，见 Task 2 的 Step 6。`.submit-item.active` 的样式本身保留不动。
2. **`onclick="selectSubmission(${it.submission_id})"` 不加引号**。`submission_id` 是整数，不加引号传的是数字，加了传的是字符串，而 `SUBMISSIONS.find(s => s.id === id)` 是严格比较——两种写法在这里结果一样（都找不到、都 return），但数字更贴近 F5 落地后的真实类型。
3. **`esc(score)` 对数字也调用**。`esc` 内部有 `String(s == null ? "" : s)`，数字进去出字符串，不会报错。

- [ ] **Step 5: 语法自检**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
python3 - <<'PY'
import re, subprocess, tempfile, os
src = open('homework.html', encoding='utf-8').read()
blocks = re.findall(r'<script>(.*?)</script>', src, re.S)
print(f"内联 <script> 块 {len(blocks)} 个")
for i, b in enumerate(blocks, 1):
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(b); path = f.name
    r = subprocess.run(['node', '--check', path], capture_output=True, text=True)
    print(f"  块 {i}: {'语法 OK' if r.returncode == 0 else r.stderr.strip()}")
    os.unlink(path)
PY
```

**预期**（`node` 已装在 `/Users/meiyazhao/.nvm/versions/node/v24.16.0/bin/node`）：

```
内联 <script> 块 2 个
  块 1: 语法 OK
  块 2: 语法 OK
```

`homework.html` 有 **2** 个内联 `<script>` 块：首段业务脚本（含本次改动）+ 第二段登录用户条脚本（本次不动，但一并检查，确认没被误伤）。

`node --check` 只做语法解析、不执行代码，所以 `document`/`fetch` 未定义不会报错——这正是我们要的。**DOM 行为仍然只能在浏览器验证**（Step 6 与 Task 2 Step 8）。

- [ ] **Step 6: 渲染层单点验证（不起后端也行）**

用 HTTP 打开页面（`file://` 打不开，页面受登录保护），登录 `teacher01`，在 Console 里粘：

```js
submitNotice = "";
submitItems = [
  { submission_id: 24, student_id: 50, student_name: "刘思琪", student_avatar: "🎵",
    student_level: "初学", ai_score: 75.2, submitted_at: "2026-08-01T00:00:00",
    tags: [ {label:"音准偏差随机",severity:"high"},
            {label:"听辨能力弱",severity:"high"},
            {label:"拖腔不足",severity:"medium"} ] },
  { submission_id: 23, student_id: 51, student_name: "李小燕", student_avatar: "",
    student_level: "初学", ai_score: null, submitted_at: null,
    tags: [ {label:"气息支撑不足",severity:"high"},
            {label:"拖腔时值偏短",severity:"low"},
            {label:"某未知档标签",severity:"whatever"} ] }
];
renderSubmitList();
```

**逐项对**：

| 检查 | 预期 |
|---|---|
| 条数 | 2 条 |
| 右上角 | 「2条待批」 |
| 第 1 条副标题 | `08-01 00:00`（**不是** `2026-08-01T00:00:00`，也不是本地时区换算后的值） |
| 第 2 条副标题 | `—` |
| 第 2 条头像 | `🎭`（空串被兜住，**不是空白格**） |
| 第 2 条分数 | `—`（**不是** `null`） |
| 第 1 条标签颜色 | 前两个朱砂（danger）、第三个赭黄（warn） |
| 第 2 条标签颜色 | 第 1 个朱砂、第 2 个景泰蓝（info）、第 3 个**灰**（neutral） |
| 控制台 | 无报错 |

再试空态与提示态：

```js
submitItems = []; submitNotice = ""; renderSubmitList();   // → 「暂无待批改提交」
submitItems = null; submitNotice = ""; renderSubmitList(); // → 「加载中…」
submitNotice = "待批改提交仅教师可见"; renderSubmitList();   // → 提示文案，右上角空
submitNotice = ""; submitItems = null; renderSubmitList(); // 复原成加载态
```

- [ ] **Step 7: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add homework.html
git commit -m "待批改提交列表渲染层改造：四态渲染 + 字段兜底 + severity 配色映射"
```

---

### Task 2: 数据层与接线——把列表接到 F4 真接口

Task 1 的渲染层已经就绪，本任务补上数据来源：`fetchSubmissions` 拉 F4，`selectHomework` 管作业切换，`renderHwList` 的卡片变成可点，`fetchHomeworks` 成功后默认选中第一份作业，并去掉页面初始化时对 mock 详情的那次调用。

**Files:**
- Modify: `homework.html`（常量注释 `:605-609`、`renderHwList` `:705`、`fetchHomeworks` `:757-777`、`selectSubmission` `:800-805`、初始化 `:929-933`）

**Interfaces:**
- Consumes: Task 1 的 `submitItems` / `submitNotice` / `renderSubmitList()`；已存在的 `esc()`、`API_BASE`、`currentUser`、`HW_STATUS` / `HW_STATUS_TEXT`、`renderHwSummary()`
- Produces:
  - `let currentHwId: number|null` — 当前选中的作业 id（F1 的 `homework_id`）
  - `let hwItems: object[]` — F1 列表的最近一次结果
  - `function selectHomework(hwId: number): void` — 切作业：刷高亮 → 进加载态 → 重拉
  - `async function fetchSubmissions(hwId: number): Promise<void>` — 拉 F4 并填状态变量

- [ ] **Step 1: 重写 mock 常量的说明注释**

找到 `homework.html:605-609`：

```js
// 作业列表已接真接口 GET /api/homeworks（见下方 fetchHomeworks / renderHwList）。
// 这个常量保留是因为**待批改提交**那一块仍是 mock（F4/F5 尚未实现），
// selectSubmission 还要读 HOMEWORKS[0].title 填批改详情页的标题。
// 等 F4 落地、SUBMISSIONS 一起换掉时，这个常量与 SUBMISSIONS 一并删除。
```

替换为：

```js
// 作业列表已接真接口 GET /api/homeworks，待批改提交已接
// GET /api/homeworks/<id>/submissions（见下方 fetchHomeworks / renderHwList /
// fetchSubmissions / renderSubmitList）。
// 这两个常量保留是因为**批改详情页**（右侧面板）仍是 mock——逐字偏差、加权融合、
// CDM、BKT、校准、评语都是 F5 的内容，尚未实现，selectSubmission 仍靠它们填右侧。
// 等 F5 落地时，这两个常量连同 selectSubmission 的函数体一并删除。
```

**这条注释必须改**：它现在说「F4/F5 尚未实现」，而 F4 的后端已经上线（commit `ee986ae`），留着就是错的。

- [ ] **Step 2: 加两个状态变量**

找到 Task 1 在 `homework.html:687` 附近留下的这一段：

```js
let currentSubId = null;
// 待批提交（F4）。这两个变量是 #submitList 的唯一数据源，改完都要调
```

在 `let currentSubId = null;` **之前**插入：

```js
// 当前选中的作业（F1 的 homework_id）。默认取 F1 列表第一份，由 fetchHomeworks
// 在拿到列表后调 selectHomework 设定。
let currentHwId = null;
// F1 列表的最近一次结果。点 hw-item 切换作业时要重渲一次作业列表来刷选中态，
// 数据从这儿取，不再请求一遍接口。
let hwItems = [];
```

- [ ] **Step 3: `renderHwList` 加选中态与点击**

找到 `homework.html:705-706`：

```js
function renderHwList(items) {
  const container = document.getElementById("hwList");
```

替换为：

```js
function renderHwList(items) {
  hwItems = items;                 // 存一份，selectHomework 刷选中态时复渲
  const container = document.getElementById("hwList");
```

再找到同一个函数里 `return` 之前、构造 `hw-item` 的那一行（在 `items.map(hw => {` 内部）：

```js
      return `
        <div class="hw-item">
```

替换为：

```js
      // 选中态与点击：.hw-item 的 cursor:pointer 与 .hw-item.active 样式本来
      // 就写好了（:229、:232），只是从来没接过线（spec 3.1）。
      const active = hw.homework_id === currentHwId ? " active" : "";
      return `
        <div class="hw-item${active}" onclick="selectHomework(${hw.homework_id})">
```

- [ ] **Step 4: 新增 `fetchSubmissions` 与 `selectHomework`**

找到 `homework.html:757` 的 `fetchHomeworks` 函数结尾（紧接着 `:780` 的 `}` 与 `:782` 的 `function renderSubmitList()`），在**两者之间**插入：

```js
// 待批提交列表：真接口 GET /api/homeworks/<id>/submissions（统一信封）。
// 与 fetchHomeworks 同：学生不发这个请求——接口挂 @teacher_required，学生调必
// 403，明知会被拒就不发，直接按 currentUser.role 分支。
async function fetchSubmissions(hwId) {
  if (!currentUser || currentUser.role !== "teacher") {
    submitItems = null;
    submitNotice = "待批改提交仅教师可见";
    renderSubmitList();
    return;
  }
  try {
    const res = await fetch(`${API_BASE}/api/homeworks/${hwId}/submissions`,
      { credentials: "same-origin" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    // 竞态兜底：慢请求回来时教师可能已经切到别的作业了，此时必须丢弃，
    // 否则会把 A 作业的提交画到 B 作业的列表下面。接口回显 homework_id 就是
    // 为了这个（接口 spec §3.7）。
    if (currentHwId !== hwId) return;
    submitNotice = "";
    submitItems = (body.data && body.data.submissions) ? body.data.submissions : [];
    renderSubmitList();
  } catch (e) {
    if (currentHwId !== hwId) return;
    submitItems = null;            // 别留半截数据
    submitNotice = "加载失败，请刷新重试";
    renderSubmitList();
  }
}

// 切换当前作业。点 hw-item 触发；页面初始化时由 fetchHomeworks 调一次。
function selectHomework(hwId) {
  currentHwId = hwId;
  renderHwList(hwItems);           // 刷 hw-item 的选中态
  submitItems = null;              // 先进加载态，否则会短暂显示上一份作业的提交
  submitNotice = "";
  renderSubmitList();
  fetchSubmissions(hwId);
}
```

**`submitNotice` 在进入加载态前必须清空**：否则从「加载失败」切到另一份作业时，旧提示会盖住新作业的加载态。

- [ ] **Step 5: `fetchHomeworks` 成功后默认选中第一份作业**

找到 `homework.html:772`：

```js
    renderHwList(body.data && body.data.homeworks ? body.data.homeworks : []);
```

替换为：

```js
    const items = body.data && body.data.homeworks ? body.data.homeworks : [];
    renderHwList(items);
    // 默认拉第一份作业的待批提交。F1 的排序是「待办优先」（grading → ongoing
    // → closed），第一份通常就是有待批的那份，但这里**不刻意去找**「第一份
    // pending_review_count > 0 的作业」——那等于把 F1 的排序口径在前端复制一份，
    // 两边漂移时默认作业会不一致（spec 3.1）。
    // items 为空（教师一份作业都没布置）时不调：那会发一个
    // homework_id=undefined 的请求。
    if (items.length) selectHomework(items[0].homework_id);
```

- [ ] **Step 6: `selectSubmission` 改成「找不到就立即 return」**

找到 `homework.html:800-805`：

```js
function selectSubmission(id) {
  currentSubId = id;
  renderSubmitList();

  const sub = SUBMISSIONS.find(s => s.id === id);
  if (!sub) return;
```

替换为：

```js
function selectSubmission(id) {
  // F4 出的 id（23/24/…）与 mock 的 sub01/sub02 永不相交，所以真列表里点任何
  // 一条都会在这里 return——批改详情是 F5 的内容，本次不做（spec 3.2）。
  // **必须在设 currentSubId 之前 return**：先设再退的话，卡片高亮会跟着移到
  // 真提交上，而右侧面板还停在上一次的 mock 内容——教师会以为右边那份就是
  // 自己刚点的那名学生。宁可完全不动。
  const sub = SUBMISSIONS.find(s => s.id === id);
  if (!sub) return;

  currentSubId = id;
  renderSubmitList();
```

**改完后 `sub` 在 `if` 之前就取好了**，下面填充右侧面板的那一大段（`:807` 起）一个字不用动。

- [ ] **Step 7: 去掉初始化时对 mock 详情的那次调用**

找到 `homework.html:929-933`：

```js
// 作业列表**不在这里渲染**：fetchHomeworks 要读 currentUser，而它要等第二段
// <script> 的 /api/auth/me 回来才有值，同步调会被误判成学生。调用点在那里。
renderSubmitList();
// 默认选中第一个提交
selectSubmission("sub01");
```

替换为：

```js
// 作业列表**不在这里渲染**：fetchHomeworks 要读 currentUser，而它要等第二段
// <script> 的 /api/auth/me 回来才有值，同步调会被误判成学生。调用点在那里。
// 这里只把待批列表画成加载态，真数据由 fetchHomeworks → selectHomework →
// fetchSubmissions 那条链接上。
renderSubmitList();
// 不调 selectSubmission("sub01")：右侧批改详情是 F5 的内容，F4 不出详情字段。
// 主动渲染 mock 会让面板常驻显示某一名的**假**数据，而真列表里有 5 名学生——
// 那不是演示，是误导。右侧停在它自己的空状态，直到 F5 落地（spec 3.3）。
```

- [ ] **Step 8: 起后端，端到端验证**

本仓库无测试框架，验证靠浏览器实操。先起服务（另开一个终端）：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && source .venv/bin/activate
python app-d.py            # 8877
```

先确认 F4 接口本身没被影响（回归）：

```bash
curl -s -c /tmp/f4page.jar -X POST http://127.0.0.1:8877/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"teacher01","password":"xiyun@2026"}' > /dev/null
curl -s -b /tmp/f4page.jar http://127.0.0.1:8877/api/homeworks | python3 -m json.tool | head -20
curl -s -b /tmp/f4page.jar http://127.0.0.1:8877/api/homeworks/12/submissions | python3 -m json.tool
```

**预期**：F1 出 3 份作业、**第一份是 hw12**（`status: "grading"`）；F4 出 5 条，顺序 `24 刘思琪 / 26 孙志远 / 27 赵雨桐 / 23 李小燕 / 25 周明轩`。

然后浏览器打开 `homework.html`（走 HTTP，经 nginx 或直连 8877 均可），按 `teacher01` 登录，逐项对：

| # | 操作 | 预期 |
|---|---|---|
| 1 | 打开页面 | 作业列表 3 份，**第一份（hw12）有蓝色边框高亮**；待批列表 5 条；右上角「5条待批」 |
| 2 | 看第 1 条卡片 | 刘思琪 · `08-01 00:00` · 3 个标签 · 分数 75.2 |
| 3 | 看标签颜色 | 朱砂 / 朱砂 / 赭黄（high、high、medium）——与 mock 时期**不同**，mock 里刘思琪是两条 `danger`，现在是三条且第二档变了。这是对齐真数据，不是回归（DOC_ISSUES §35.4 第 2 点已预告） |
| 4 | 点任一提交卡片 | **不高亮、右侧面板仍是空状态**、Console 无报错 |
| 5 | 点 hw13 | hw13 变高亮（hw12 取消）；待批列表变「暂无待批改提交」；右上角**清空** |
| 6 | 点回 hw12 | hw12 高亮；5 条回来；右上角「5条待批」 |
| 7 | 开 F12 Network，点 hw13 再快速点 hw12 | 只应看到两个 `/submissions` 请求；**列表最终显示的是 hw12 的 5 条**，不会出现 hw13 的 `[]` 盖掉 hw12 的内容（Step 4 的竞态兜底） |
| 8 | 登出，用 `stu001` 登录 | 作业列表「作业列表仅教师可见」；待批列表「待批改提交仅教师可见」；右上角空；**Network 里没有 `/api/homeworks` 也没有 `/submissions` 请求** |
| 9 | 停掉 Flask 后刷新（先切回 `teacher01`） | 两个列表都出「加载失败，请刷新重试」（F1 的是「加载失败，请刷新重试」，同文案） |

- [ ] **Step 9: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add homework.html
git commit -m "待批改提交列表接入 F4 真接口，新增作业选择交互"
```

---

### Task 3: 全量回归、文档登记

Task 2 结束时功能已经可用。本任务把 spec §5 列的全部验证项跑一遍，并把 DOC_ISSUES 里「前端未接入」的记载更新掉——那份文件当前说 `homework.html` 右侧仍是 mock 且待批列表未接入，已经与事实不符。

**Files:**
- Modify: `DOC_ISSUES.md`（第 35 条，`:1086` 附近的 §35.4）

**Interfaces:**
- Consumes: Task 1、Task 2 的全部改动
- Produces: 无代码产物

- [ ] **Step 1: 跑模型与真库的一致性闸门**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && source .venv/bin/activate
python scripts/check_db.py; echo "exit=$?"
```

**预期**：本次不动库，输出应与**改动前完全一致**。

**注意**：`check_db.py` 在干净 `main` 上**本来就会报差异**（`demo_versions` 表 + `teacher_demos` 三列是既有漂移，见项目记忆与 DOC_ISSUES 相关条目）。所以判定标准是「**与本次改动前一致**」，不是「无输出」。若不确定，先 `git stash` 跑一次基线再对比。

- [ ] **Step 2: 重跑 spec §5 的全部验证项**

照 Task 2 Step 8 的表格逐项再走一遍，外加：

```bash
# 作业不存在 → 404「作业不存在」
curl -s -b /tmp/f4page.jar http://127.0.0.1:8877/api/homeworks/999/submissions
# 学生 → 403；无 cookie → 401
curl -s -c /tmp/stu.jar -X POST http://127.0.0.1:8877/api/auth/login \
  -H 'Content-Type: application/json' -d '{"username":"stu001","password":"xiyun@2026"}' > /dev/null
curl -s -b /tmp/stu.jar http://127.0.0.1:8877/api/homeworks/12/submissions
curl -s http://127.0.0.1:8877/api/homeworks/12/submissions
```

**预期**：`404` + `{"code":404,"message":"作业不存在",...}`；`403`；`401`。

- [ ] **Step 3: 更新 DOC_ISSUES §35.4**

找到 `DOC_ISSUES.md:1086` 附近的这一节标题：

```markdown
### 35.4 前端未接入，`homework.html` 右侧仍是 mock
```

把整节替换为（保留原三点的编号与内容，改写首段与结论段）：

```markdown
### 35.4 前端已接入，`homework.html` 右侧仍是 mock

**2026-10-08 状态**：待批改提交列表（F4）**已接入**，见 `docs/superpowers/specs/2026-10-08-homework-submissions-page-design.md`。作业列表与待批列表现在都是真数据；**右侧批改详情面板仍是 mock**——它要的逐字偏差、加权融合、CDM、BKT、校准、评语是 F5 的内容，F5 未实现。

接入后新自拟的口径（文档未定义）：

| 项 | 自拟口径 | 理由 |
|---|---|---|
| 作业选择 | 默认 F1 列表第一份，点 `hw-item` 切换 | 文档未规定教师端如何选定作业。**不刻意找「第一份有待批的作业」**——那等于把 F1 的排序口径在前端复制一份 |
| 点击真提交 | **不做任何事**（不高亮、不重渲、不动右侧面板） | 详情是 F5 的内容。若先设 `currentSubId` 再退，卡片高亮会移到真提交上而右侧仍显示上一次的 mock 内容，教师会误以为那就是刚点的那名学生 |
| 右侧初始态 | 加载后停在空状态，不再主动渲染 mock 的 `sub01` | 真列表有 5 名学生，面板却常驻显示其中一名的假数据 |
| `severity` → CSS 类 | `high→danger`、`medium→warn`、`low→info`、其余（含 `"unknown"`）→`neutral`（新增一行 CSS） | 见 §35.3：三档语义文档未定义，配色映射是自拟的 |
| 时间显示 | ISO-8601 字符串切片成 `"08-01 00:00"`，**不走 `Date`** | 串无时区后缀、库里存的是北京时间；`Date` 会按浏览器本地时区来回转换，非 +08:00 的机器上会漂 |
| 无数据时右上角 | 留空，不写「暂无待批」 | 与「仅教师可见」并排会读成「确实一条都没有」，实际是「没权限看」（同 F1 的 `hwSummary`） |

`HOMEWORKS` / `SUBMISSIONS` 两个常量**保留未删**：右侧面板仍靠它们渲染，删了页面右半屏就是空的。它们与 `selectSubmission` 的函数体一并等 F5 落地时删除。因此**「同一页真数据与 mock 并存」的问题（§34.5）依旧存在**，只是范围缩小到右侧面板一块。

以下三点是接入时实际处理掉的，原样保留备查：
```

- [ ] **Step 4: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add DOC_ISSUES.md docs/superpowers/specs/2026-10-08-homework-submissions-page-design.md docs/superpowers/plans/2026-10-08-homework-submissions-page.md
git commit -m "待批改提交前端接入完成，更新 DOC_ISSUES 第 35.4 条"
```

**注意**：这一步会把 spec 与 plan 两份文档一起入库。工作区里另有 `docs/superpowers/specs/2026-09-30-homework-submissions-api-design.md` 与对应的 plan（F4 接口那两份）**至今仍是 untracked**——它们**不在本次提交范围**，要不要入库请单独决定，别顺手 `git add docs/`。

---

## 自检记录

**spec 覆盖**：§3.1 作业选择 → Task 2 Step 3/5/6；§3.2 点真提交无反应 → Task 2 Step 6；§3.3 右侧空状态 → Task 2 Step 7；§3.4 severity 映射 → Task 1 Step 1/4；§3.5 时间格式 → Task 1 Step 4（`fmtTime`）；§3.6 空值兜底 → Task 1 Step 4；§3.7 权限与各态文案 → Task 1 Step 4 + Task 2 Step 4；§3.8 常量保留 → Task 2 Step 1；§4 实现设计 → Task 1/2 全覆盖；§5 验证 → Task 3。

**类型一致性**：`submitItems`（`null`|数组）、`submitNotice`（`""`|字符串）、`currentHwId`（number|null）、`hwItems`（数组）四个变量在 Task 1 与 Task 2 中名字与语义一致；`renderSubmitList()` 全程无参数；`fmtTime` / `SEV_CLS` 只在 Task 1 定义、Task 1 内使用。

**超出 spec 的一处**：Task 2 Step 4 的**竞态兜底**（`if (currentHwId !== hwId) return;`）。spec §3 没写这一条，但不加会有真实的错显——快速点两份作业时，先发的慢请求回来后会把旧作业的提交画到新作业的列表下。接口 spec §3.7 回显 `homework_id` 的理由正是为此。评审若认为多余，删掉那两行 `if` 即可，其余不受影响。
