# 实时跟唱页（`sing_along.html`）曲目列表与示范播放 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `sing_along.html` 的曲目下拉、分段列表、逐字歌词从页面内硬编码的 `PIECES` 常量换成后端 C1/C2/C3 三个真接口，并把「播放示范」从 `requestAnimationFrame` 模拟动画换成真实音频播放。

**Architecture:** 单文件前端改造，全部改动落在 `sing_along.html` 一个文件里。新增一个统一的取数助手 `apiGet()`（同源 + Cookie + 统一信封拆包），三个 `loadXxx()` 按「切曲目 → 选段落」的层级逐级拉数据；`PIECES` 常量整体删除，全部消费者改读新的模块级状态。播放用一个游离的 `new Audio()` 实例，音频 url 由 `/api/demo/library/<id>` 懒加载取得。

**Tech Stack:** 原生 JS（无框架、无构建）、Flask 后端（已有接口，本轮不改）、PostgreSQL。验证靠 `curl` + 浏览器实测——**本仓库没有测试框架**，不要试图引入 pytest/vitest。

## Global Constraints

- **只改 `sing_along.html` 一个文件**，外加最后一步往 `DOC_ISSUES.md` 追加一条。不动 `app/`、`schema.sql`、`app-d.py`、`requirements.txt`，不引入任何新依赖、不新增前端文件。
- **接口一律用同源相对路径**（`/api/...`），只带 `credentials: 'same-origin'`。**绝对不要写成 `location.host + ':8877'`**——那是跨源请求，跨源 fetch 默认不带 Cookie，后端 `login_required` 只会看到空 session 并回 401。
- **统一响应信封**是 `{"code":0,"message":"ok","data":{...}}`，`code === 0` 才算成功。
- **渲染数据库文本必须转义**。本文件顶部登录条的既有纪律是「全部用 `textContent` 填充，不用 `innerHTML`——`display_name` 来自数据库，拼接进 HTML 会有注入风险」。曲目名、段落名、唱词、提示同样来自数据库，走 `innerHTML` 模板时必须过 `escapeHtml()`。
- **注释与提交信息用简体中文**；代码标识符保持英文。
- **`segments` 表的所有列（除 `id`）在 DDL 上均可空**，C2/C3 出参也如实可空。**任何 `.toFixed()` / 算术前都要先判 `Number.isFinite()`**——库里已有一条 `duration` 为 `null` 的曲目级数据，一个 `null` 上的 `.toFixed()` 会抛 TypeError 打断整张列表的 `map`，整页渲染不出来。
- **禁止静态直出音频**：`url` 必须用接口返回值，不要在页面里硬编码 `/api/audio/<id>`（路径漂移正是 `DOC_ISSUES` 第 1 条记的那类问题）。
- **本轮不修 B5**。示范音频当前放不出声（`spec` §2.5、`DOC_ISSUES` 第 40 条），前端只需正确降级，**不要**去改后端或改库来「让它能响」。

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `sing_along.html` | 修改 | 本轮全部前端改动 |
| `DOC_ISSUES.md` | 追加 | 第 40 条：B5 放不出示范音频 |

`sing_along.html` 是单文件自包含原型，不拆分。改动集中在底部那一个 `<script>` 里。

**用得到的既有锚点**（改前先按行号确认，行号会随增删漂移）：

| 位置 | 当前行 | 内容 |
|---|---|---|
| `#pieceSelect` | `:511-515` | 写死的 3 个 `<option>` |
| `drawLyricsAndGrid` | `:825-867` | 画歌词竖线与字（含拼音那行） |
| 全局状态块 | `:745-762` | `let currentPiece = "mu";` 所在 |
| `PIECES` 常量 | `:627-743` | 整个删除对象 |
| `renderTeacherTips` | `:998-1018` | 读 `seg.coachingTips` |
| `renderSegments` | `:1023-1039` | 读 `PIECES[currentPiece]` |
| `selectSegment` | `:1040-1054` | 同步函数 |
| `prepareTeacherCurve` | `:1055-1077` | 读 `seg.lyrics` |
| `recordLoop` | `:1136-1183` | 读 `seg.lyrics` / `coachingTips` |
| `updateMetrics` | `:1185-1246` | 读 `ly.teacherPitch` |
| `playDemo` | `:1306-1340` | 模拟动画，整体重写 |
| `stopAll` | `:1345-1380` | 需加音频停止 |
| `changePiece` | `:1382-1392` | 读 `PIECES` |
| `init` | `:1406-1413` | 同步函数 |

---

## Task 1: 曲目 / 分段 / 歌词链路切换（C1+C2+C3），删除 `PIECES`

这是本轮的主体：把页面唯一的数据源从页面内常量换成后端。**必须一次做完**——`PIECES` 的键是 `"mu"/"guifei"/"bawang"` 字符串，而 C1 给的是数字 `16/17/18`，任何中间状态都会让页面处于「下拉是新的、渲染还在读旧常量」的错配上。

**Files:**
- Modify: `sing_along.html`（唯一）

**Interfaces:**
- Consumes: `GET /api/demos` → `[{id,title,role,banshi,duration,elo_difficulty,segment_count}]`；`GET /api/demos/<demoId>/segments` → `[{id,seq,title,duration}]`；`GET /api/segments/<segmentId>` → `{id,seq,title,duration,lyrics:[{char,pitch,start,duration,note,tip}]}`。三者都只需登录，**学生账号可调**。
- Produces: 模块级状态 `demos: Array`、`segments: Array`、`currentLyrics: Array`、`currentDemoId: number|null`；助手 `apiGet(path): Promise<any>`、`escapeHtml(s): string`、`demoTitle(): string`；`loadDemos(): Promise<void>`、`loadSegments(demoId): Promise<void>`；`prepareTeacherCurve()` 与 `renderTeacherTips()` **改为无参**（Task 2 依赖 `currentDemoId` 与 `demoAudio`）。

- [ ] **Step 1: 先建立基线，确认改动前后的差异可观测**

起后端（若未在跑），用学生账号拿一个 Cookie，把四个接口的**改前**输出存下来当基线：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
rm -f /tmp/sa_cookie.txt
curl -s -c /tmp/sa_cookie.txt -X POST http://127.0.0.1:8877/api/auth/login \
  -H 'Content-Type: application/json' -d '{"username":"stu001","password":"xiyun@2026"}'
curl -s -b /tmp/sa_cookie.txt http://127.0.0.1:8877/api/demos | python3 -m json.tool | head -20
```

预期：登录返回 `"code": 0` 且 `role` 是 `student`；`/api/demos` 返回 **6** 条（id 1/15/16/17/18/19）。

同时记录页面对 `PIECES` 的依赖强度（**这就是本任务要清零的「失败测试」**）：

```bash
grep -c "PIECES" sing_along.html
```

预期：`14`。本任务结束时这个数字必须是 `0`。

- [ ] **Step 2: 加两个工具函数（`escapeHtml` + `apiGet`）**

在 `sing_along.html` 的「工具函数」分区（`function midiToNote(midi)` 之前，约 `:779`）插入：

```js
// ============================================================
// 取数与转义
// ============================================================
// 渲染数据库文本必须转义：曲目名/唱词/提示都来自库里，直接拼进 innerHTML
// 就是注入面。同文件顶部登录条对 display_name 用的是 textContent，这里因为
// 要用模板字符串拼结构，改用等价的转义。
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

// 统一取数：同源相对路径（经 nginx 代理到 Flask），必须带 Cookie——跨源 fetch
// 默认不带 Cookie，后端 login_required 只会看到空 session 并回 401。
// 统一信封 {code, message, data}：HTTP 非 2xx 或 code !== 0 都当失败抛出，
// 调用方只需 try/catch 一处，不必各自拆信封。
async function apiGet(path) {
  const r = await fetch(path, { credentials: "same-origin" });
  let body = null;
  try { body = await r.json(); } catch (e) { /* 非 JSON（如 nginx 的 502 页） */ }
  if (!r.ok) throw new Error((body && body.message) || ("HTTP " + r.status));
  if (!body || body.code !== 0) throw new Error((body && body.message) || "响应格式错误");
  return body.data;
}
```

- [ ] **Step 3: 换掉全局状态，新增 `demoTitle()`**

把全局状态块（`:745-762` 里的）这一行：

```js
let currentPiece = "mu";
```

替换为：

```js
let demos = [];              // C1 GET /api/demos
let segments = [];           // C2 当前曲目的分段
let currentLyrics = [];      // C3 当前段落的逐字歌词
let currentDemoId = null;    // 当前曲目 id（数字，null = 还没选）
```

`currentSegmentIdx` 保留（全页十余处依赖它），它是 `segments` 的**下标**。

在同区块末尾（`const tipsGrid = ...` 之后）加：

```js
function demoTitle() {
  const d = demos.find(x => x.id === currentDemoId);
  return d ? d.title : "";
}
```

- [ ] **Step 4: 删除整个 `PIECES` 常量**

删除 `:627-743` 整段（`const PIECES = { ... };`，含前面三行 `// ====` 注释头）。

此时页面已无法运行——这正是本任务接下来要修的。

- [ ] **Step 5: 加 `loadDemos()` 与 `loadSegments()`**

紧接 `demoTitle()` 之后插入：

```js
// ============================================================
// 数据加载
// ============================================================
async function loadDemos() {
  demos = await apiGet("/api/demos");
  const sel = document.getElementById("pieceSelect");
  if (demos.length === 0) {
    const o = document.createElement("option");
    o.value = "";
    o.textContent = "（库里还没有曲目）";
    sel.replaceChildren(o);
    return;
  }
  // 用 createElement + textContent 而不是 innerHTML：title 来自数据库
  sel.replaceChildren(...demos.map(d => {
    const o = document.createElement("option");
    o.value = String(d.id);
    o.textContent = d.title;
    return o;
  }));
  sel.value = String(demos[0].id);
}

async function loadSegments(demoId) {
  segments = await apiGet(`/api/demos/${demoId}/segments`);
  currentSegmentIdx = -1;
  currentLyrics = [];
  renderSegments();
  segmentInfo.textContent = demoTitle() + " · 请选择段落";
  renderTeacherTips();
  drawEmptyState();
}
```

- [ ] **Step 6: 改 `drawLyricsAndGrid()`——去拼音、跳过脏条目**

把 `:825-867` 整个函数替换为：

```js
function drawLyricsAndGrid() {
  if (currentLyrics.length === 0) return;
  currentLyrics.forEach((ly, idx) => {
    // start 可空（C2/C3 spec）：没有时间点的字画不出来，跳过即可——
    // 不能让一个脏条目打断整条渲染。
    if (!Number.isFinite(ly.start)) return;
    const x = timeToX(ly.start);
    if (x >= 0 && x <= canvasWidth) {
      const isActive = (idx === currentWordIndex);
      ctx.save();
      ctx.strokeStyle = isActive ? "rgba(0,102,179,0.5)" : "rgba(180,160,145,0.4)";
      ctx.lineWidth = isActive ? 3 : 1.5;
      ctx.setLineDash(isActive ? [] : [3, 5]);
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, canvasHeight);
      ctx.stroke();
      ctx.restore();
      ctx.save();
      const isPassed = (idx < currentWordIndex);
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      ctx.font = isActive ? "bold 18px sans-serif" : "15px sans-serif";
      ctx.fillStyle = isActive ? "#0066B3" : (isPassed ? "#4A8F6B" : "#8A7A6A");
      ctx.fillText(ly.char || "", x, TOP_OFFSET - 4);
      ctx.restore();
    }
  });
  ctx.save();
  ctx.strokeStyle = "rgba(200,190,180,0.3)";
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 5]);
  ctx.beginPath();
  ctx.moveTo(0, TOP_OFFSET + 2);
  ctx.lineTo(canvasWidth, TOP_OFFSET + 2);
  ctx.stroke();
  ctx.restore();
}
```

**相对原版删掉的是** `:849-855` 那段画 `ly.pinyin` 的代码块——C3 不返回 `pinyin`，后端无此数据源，不是漏接。

- [ ] **Step 7: 改 `renderTeacherTips()`——改无参、读 `currentLyrics`**

把 `:998-1018` 整个函数替换为：

```js
function renderTeacherTips() {
  if (currentSegmentIdx < 0) {
    tipsGrid.innerHTML = `<span style="color:var(--text-muted);font-size:14px;">请选择一个分段，查看对应的技巧提示。</span>`;
    return;
  }
  if (currentLyrics.length === 0) {
    tipsGrid.innerHTML = `<span style="color:var(--text-muted);font-size:14px;">该唱段还没有歌词数据。</span>`;
    return;
  }
  // tip 是逐字的（C3 的 lyrics[].tip），不再按字查 coachingTips 表——
  // 原来的按字建 map 在同段出现重复字时会互相覆盖。
  tipsGrid.innerHTML = currentLyrics.map(ly => `
      <div class="tip-item">
        <span class="char">${escapeHtml(ly.char || "")}</span>
        <span class="hint">${escapeHtml(ly.tip || "")}</span>
      </div>
    `).join("");
}
```

- [ ] **Step 8: 改 `renderSegments()`——读 `segments`、判空、三种空态**

把 `:1023-1039` 整个函数替换为：

```js
function renderSegments() {
  const container = document.getElementById("segmentList");
  if (currentDemoId === null) {
    container.innerHTML = `<span style="color:var(--text-muted);font-size:14px;">请先选择曲目。</span>`;
    return;
  }
  if (segments.length === 0) {
    container.innerHTML = `<span style="color:var(--text-muted);font-size:14px;">该曲目还没解析出唱段。</span>`;
    return;
  }
  container.innerHTML = segments.map((seg, idx) => {
    const isActive = idx === currentSegmentIdx;
    const seq = (seg.seq != null) ? seg.seq : (idx + 1);
    // duration 在 DDL 上可空：null 上直接 .toFixed 会抛 TypeError 打断整个 map，
    // 整张列表渲染不出来。库里有真实数据命中这条。
    const dur = Number.isFinite(seg.duration) ? (seg.duration.toFixed(1) + "s") : "时长未知";
    return `
      <div class="segment-item ${isActive ? 'active' : ''}" onclick="selectSegment(${idx})">
        <div class="segment-title">第 ${seq} 段 · ${escapeHtml(seg.title || "")}</div>
        <div class="segment-meta">${dur}</div>
        <span class="segment-status ${isActive ? 'ready' : 'pending'}">${isActive ? "▶ 当前" : "待练习"}</span>
      </div>
    `;
  }).join("");
}
```

**注意**：原版的 `seg.subtitle` 与 `completed` 去掉了。`subtitle` 后端没有对应字段（库里 `segments.title` 本身就是唱词）；`completed` 全页从未被赋值，段落恒为「待练习」。

- [ ] **Step 9: 改 `selectSegment()`——改 async，选段时拉 C3**

把 `:1040-1054` 整个函数替换为：

```js
async function selectSegment(idx) {
  if (isRecording || isPlaying) stopAll();
  currentSegmentIdx = idx;
  renderSegments();
  const seg = segments[idx];
  try {
    const detail = await apiGet(`/api/segments/${seg.id}`);
    currentLyrics = Array.isArray(detail.lyrics) ? detail.lyrics : [];
  } catch (e) {
    currentLyrics = [];
    addLog(`加载唱段详情失败：${e.message}`, "error");
  }
  const seq = (seg.seq != null) ? seg.seq : (idx + 1);
  segmentInfo.textContent = `${demoTitle()} · 第 ${seq} 段 · ${seg.title || ""}`;
  prepareTeacherCurve();
  renderTeacherTips();
  currentWordIndex = -1;
  studentPoints = [];
  syncCurrentTime = 0;
  drawTimeline();
  addLog(`选择段落: 第 ${seq} 段 ${seg.title || ""}`, "info");
}
```

- [ ] **Step 10: 改 `prepareTeacherCurve()`——改无参、字段改名、跳过标点**

把 `:1055-1077` 整个函数替换为：

```js
function prepareTeacherCurve() {
  teacherPoints = [];
  const seg = segments[currentSegmentIdx];
  segmentDuration = (seg && Number.isFinite(seg.duration)) ? seg.duration : 0;
  const sampleRate = 0.02;
  for (let t = 0; t <= segmentDuration; t += sampleRate) {
    let pitch = null;
    for (let i = 0; i < currentLyrics.length; i++) {
      const ly = currentLyrics[i];
      // pitch === null 表示这是标点（C3 spec）；start/duration 可空。
      // 三者任一不成立就跳过这一格，不参与曲线。
      if (ly.pitch === null || !Number.isFinite(ly.pitch)
          || !Number.isFinite(ly.start) || !Number.isFinite(ly.duration)) continue;
      if (t >= ly.start && t < ly.start + ly.duration) {
        pitch = ly.pitch;
        const edge = 0.03;
        if (i > 0 && t < ly.start + edge) {
          const prev = currentLyrics[i - 1];
          // 前一个字可能是标点（pitch 为 null），那样就算不出过渡，直接用本字音高
          if (Number.isFinite(prev.pitch)) {
            const ratio = (t - ly.start) / edge;
            pitch = prev.pitch + (ly.pitch - prev.pitch) * ratio;
          }
        }
        break;
      }
    }
    if (pitch !== null) teacherPoints.push({ t, pitch });
  }
  timeTotal.textContent = segmentDuration.toFixed(2) + "s";
}
```

- [ ] **Step 11: 改 `recordLoop()`——字段改名 + tip 直读**

在 `:1136-1183` 里改这四处：

① 函数开头取 `seg` 并加空值保护（原为 `const seg = PIECES[currentPiece].segments[currentSegmentIdx];`）：

```js
  const seg = segments[currentSegmentIdx];
  if (!seg) { stopRecordingAndAnalyze(); return; }
  if (elapsed > ((Number.isFinite(seg.duration) ? seg.duration : 0) + 0.5)) {
    stopRecordingAndAnalyze();
    return;
  }
```

② 找当前字的循环（原用 `seg.lyrics[i].start` / `.dur`）：

```js
  let widx = -1;
  let teacherPitchNow = null;
  for (let i = 0; i < currentLyrics.length; i++) {
    const ly = currentLyrics[i];
    if (Number.isFinite(ly.start) && Number.isFinite(ly.duration)
        && elapsed >= ly.start && elapsed < ly.start + ly.duration) {
      widx = i;
      teacherPitchNow = ly.pitch;
      break;
    }
  }
```

③ 提示气泡（原为 `seg.coachingTips?.find(t => t.char === currentLyric.char)`）：

```js
  if (widx !== currentWordIndex) {
    currentWordIndex = widx;
    if (widx >= 0) {
      const currentLyric = currentLyrics[widx];
      if (currentLyric.tip) showCoaching(currentLyric.tip, currentLyric.char);
    }
    updateMetrics(elapsed, seg, widx);
  }
```

④ 后面的 `syncCurrentTime = elapsed; drawTimeline(); updateProgress(elapsed);` 不动。

- [ ] **Step 12: 改 `updateMetrics()`——字段改名 + 标点保护**

把 `:1187-1188` 这两行：

```js
  const ly = seg.lyrics[widx];
  const teacherP = ly.teacherPitch;
```

替换为：

```js
  const ly = currentLyrics[widx];
  // 标点没有音高（pitch 为 null），算不出偏差，直接不更新读数
  if (!ly || !Number.isFinite(ly.pitch)) return;
  const teacherP = ly.pitch;
```

函数其余部分（节奏/气息那些 `widx === 2` 的模拟分支）**保持原样**。

- [ ] **Step 13: 改 `changePiece()`——改 async，取数字 demoId**

把 `:1382-1392` 整个函数替换为：

```js
async function changePiece() {
  const sel = document.getElementById("pieceSelect");
  currentDemoId = sel.value ? Number(sel.value) : null;
  currentLyrics = [];
  segments = [];
  stopAll();
  if (currentDemoId === null) {
    renderSegments();
    segmentInfo.textContent = "请选择曲目";
    renderTeacherTips();
    drawEmptyState();
    return;
  }
  try {
    await loadSegments(currentDemoId);
    addLog(`切换曲目: ${demoTitle()}`, "info");
  } catch (e) {
    segments = [];
    renderSegments();
    addLog(`加载分段失败：${e.message}`, "error");
  }
}
```

- [ ] **Step 14: 改 `init()`——改 async，先拉曲目列表**

把 `:1406-1413` 替换为：

```js
async function init() {
  initCanvas();
  drawEmptyState();
  renderSegments();
  renderTeacherTips();
  try {
    await loadDemos();
    addLog("🚀 智能陪练已加载，选择曲目和段落开始练习", "info");
  } catch (e) {
    addLog(`加载曲目列表失败：${e.message}`, "error");
  }
}
init();
```

- [ ] **Step 15: 静态自检**

```bash
grep -c "PIECES\|currentPiece" sing_along.html
grep -n "teacherPitch\|\.pinyin\|coachingTips\|seg\.subtitle" sing_along.html
node --check <(sed -n '/^<script>$/,/^<\/script>$/p' sing_along.html | sed '1d;$d') 2>&1 | head -5
```

预期：
- 第一条输出 `0`
- 第二条**无输出**（这些旧字段名必须一个都不剩）
- 第三条若 `node` 不可用则跳过；可用时不应报语法错误

- [ ] **Step 16: 浏览器实测**

后端起在 8877（nginx 侧 80 端口转发），用 `stu001` / `xiyun@2026` 登录后打开 `http://<host>/sing_along.html`。逐条确认：

1. 下拉框出现 **6** 条曲目，第一条是「贵妃醉酒·选段」（id 升序）
2. 选第 16 条《穆桂英挂帅》→ 分段区出现 **10** 段，标题形如「第 1 段 · 辕门外三声炮如同雷震」，时长 `19.5s`
3. 点第 1 段 → 画布画出 10 个字的竖线与蓝色教师曲线、顶部**没有拼音行**；「教师提示」区每字右侧有提示文字（如「辕 → 平稳行腔，咬字清楚」）
4. 选第 19 条《红娘》→ 分段区显示「该曲目还没解析出唱段。」
5. 选第 1 条「贵妃醉酒·选段」→ 分段区出现 1 段「第 1 段 · 第一段」，时长 `30.5s`
6. 点「🎙️ 开始跟唱」录一小段再停 → 读数与曲线仍在跳（录制流程本轮不动，不应被改坏）

- [ ] **Step 17: 提交**

```bash
git add sing_along.html
git commit -m "feat: sing_along 曲目/分段/歌词接真接口，删除 PIECES 常量

曲目下拉走 C1 /api/demos，分段列表走 C2，逐字歌词与提示走 C3。
拼音行删除（C3 不返回 pinyin）；duration 判空，避免 null 上 .toFixed 打断列表渲染。
数据库文本一律经 escapeHtml 再进 innerHTML。"
```

---

## Task 2: 播放示范接真实音频（B5）

**Files:**
- Modify: `sing_along.html`

**Interfaces:**
- Consumes: `GET /api/demo/library/<demoId>` → `{..., url: string|null}`（Task 1 的 `apiGet`、`currentDemoId`）
- Produces: `resolveAudioUrl(demoId): Promise<string|null>`；`demoAudio`（模块级 `Audio` 实例）；`playDemo()` 改为 async

- [ ] **Step 1: 确认音频 url 的真实形态与当前失败方式**

```bash
curl -s -b /tmp/sa_cookie.txt http://127.0.0.1:8877/api/demo/library/16 | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['url'])"
curl -s -b /tmp/sa_cookie.txt -o /dev/null -w "code=%{http_code}\n" http://127.0.0.1:8877/api/audio/75
```

预期：`url` 是 `/api/audio/75`；直接请求该 url 得到 **400**（`spec` §2.5 / `DOC_ISSUES` 第 40 条）。

**这说明本任务完成后点播放仍然听不到声音**——这是已知的、本轮不修的后端缺陷。本任务验收的是**代码路径**：url 取到 → `<audio>` 发起请求 → 4xx → `error` 被捕获 → 日志提示 + 回到停止态。

- [ ] **Step 2: 加音频实例与 url 缓存**

紧接 Task 1 的 `demoTitle()` 之后插入：

```js
// 示范音频：游离的 Audio 实例，不往 DOM 塞 <audio> 元素——页面没有播放器控件的
// 设计位，一切播控都走既有的 btnPlayDemo / btnStop。
const demoAudio = new Audio();
demoAudio.preload = "none";
const audioUrlCache = new Map();   // demoId -> url|null，懒加载后缓存
let audioError = false;            // 本次播放是否已由 error 事件报过错，防重复日志
```

- [ ] **Step 3: 加 `resolveAudioUrl()`**

紧接上一步之后插入：

```js
// 音频 url 懒加载：C1 的曲目列表不含音频地址，带 url 的是示范库详情。
// 该接口只需登录（学生可调）。取一次就缓存，同一曲目不再重复请求。
async function resolveAudioUrl(demoId) {
  if (audioUrlCache.has(demoId)) return audioUrlCache.get(demoId);
  const detail = await apiGet(`/api/demo/library/${demoId}`);
  const url = detail.url || null;
  audioUrlCache.set(demoId, url);
  return url;
}
```

- [ ] **Step 4: 注册音频事件（一次，模块级）**

紧接上一步之后插入：

```js
// 时长要等 loadedmetadata——play() 返回时 duration 常常还是 NaN
demoAudio.addEventListener("loadedmetadata", () => {
  if (Number.isFinite(demoAudio.duration)) {
    timeTotal.textContent = demoAudio.duration.toFixed(2) + "s";
  }
});
// 进度条与时间由音频真实的 currentTime 驱动（播放示范时画布不动，
// 但进度条反映整首的播放进度）
demoAudio.addEventListener("timeupdate", () => {
  if (!isPlaying) return;
  const d = demoAudio.duration;
  if (Number.isFinite(d) && d > 0) {
    progressFill.style.width = Math.min(100, (demoAudio.currentTime / d) * 100) + "%";
  }
  timeCurrent.textContent = demoAudio.currentTime.toFixed(2) + "s";
});
demoAudio.addEventListener("ended", () => {
  stopAll();
  addLog("示范播放完成", "success");
});
// 当前后端还不能提供示范音频（DOC_ISSUES 第 40 条），这条是常态路径而非边角
demoAudio.addEventListener("error", () => {
  audioError = true;
  addLog("示范音频加载失败：后端未能提供该音频", "error");
  stopAll();
});
```

- [ ] **Step 5: 重写 `playDemo()`**

把 `:1306-1340` 整个函数替换为：

```js
async function playDemo() {
  // 播的是整首，与段落无关——不再要求「先选一个练习段落」
  if (currentDemoId === null) { alert("请先选择曲目"); return; }
  if (isRecording) stopAll();

  let url;
  try {
    url = await resolveAudioUrl(currentDemoId);
  } catch (e) {
    addLog(`获取示范音频失败：${e.message}`, "error");
    return;
  }
  if (!url) {
    addLog("该曲目没有示范音频", "warn");
    document.getElementById("btnPlayDemo").disabled = true;
    return;
  }

  audioError = false;
  demoAudio.src = url;
  demoAudio.currentTime = 0;

  // 先进入播放态再 play()：play() 既可能被浏览器的自动播放策略拒绝，
  // 也可能因取不到音频而 reject，两条路都要能从「播放中」退回。
  isPlaying = true;
  document.getElementById("btnPlayDemo").disabled = true;
  document.getElementById("btnRecord").disabled = true;
  document.getElementById("btnStop").style.display = "inline-flex";
  addLog("▶️ 播放示范音频…", "info");

  try {
    await demoAudio.play();
  } catch (e) {
    // 取不到音频时 error 事件已接管并打过日志；这里只兜「自动播放被拒」
    if (!audioError) addLog(`播放失败：${e.message}`, "error");
    if (isPlaying) stopAll();
  }
}
```

- [ ] **Step 6: `stopAll()` 加音频停止**

在 `:1345` 的 `stopAll()` 开头，`isPlaying = false;` / `isRecording = false;` 之后加：

```js
  // src 为空时设 currentTime 无意义，跳过
  if (demoAudio.src) {
    demoAudio.pause();
    demoAudio.currentTime = 0;
  }
```

**按钮复位不用另写**：`stopAll()` 尾部已有 `document.getElementById("btnPlayDemo").disabled = false;`，而 `changePiece()` 会先调 `stopAll()`——所以「在 demo 1（无音频）上按钮被置灰，切回 demo 16 后恢复可用」这条自动成立。Step 8 要实测确认它真的成立。

- [ ] **Step 7: 静态自检**

```bash
grep -n "demoLoop\|requestAnimationFrame(demoLoop)" sing_along.html
grep -n "demoAudio\|resolveAudioUrl" sing_along.html
```

预期：第一条**无输出**（原来的模拟循环必须整段消失）；第二条列出 Step 2–6 加的那些行。

- [ ] **Step 8: 浏览器实测**

1. 选 demo 16 → 点「▶️ 播放示范」→ **浏览器 Network 里应看到一次 `/api/demo/library/16`（返回 url）和一次对 `/api/audio/75` 的请求**，该请求返回 400 → 日志面板出现「示范音频加载失败：后端未能提供该音频」→ 按钮回到可点、「⏹️ 停止」消失
2. 选 demo 1（无音频）→ 点播放 → 日志「该曲目没有示范音频」，按钮置灰
3. **再切回 demo 16 → 播放按钮必须恢复可点**（这条是本任务的回归点）
4. 连点两次播放 → 不应叠加两条日志/两个播放态
5. 播放中切曲目 / 点停止 → 不报错

- [ ] **Step 9: 提交**

```bash
git add sing_along.html
git commit -m "feat: sing_along 播放示范接真实音频

url 经 /api/demo/library/<id> 懒加载并缓存，<audio> 的 currentTime 驱动进度条与时间。
播放不再要求先选段落（播的是整首）。音频取不到时由 error 事件降级为日志提示并复位按钮。
B5 当前放不出声见 DOC_ISSUES 第 40 条。"
```

---

## Task 3: 端到端验证与缺陷登记

**Files:**
- Modify: `DOC_ISSUES.md`（追加第 40 条）

**Interfaces:**
- Consumes: Task 1、Task 2 的全部产物
- Produces: `DOC_ISSUES.md` 第 40 条

- [ ] **Step 1: 跑一遍完整边角清单**

清一个干净会话，用 `stu001` 登录，按 `spec` §7 逐条走：

| # | 操作 | 预期 |
|---|---|---|
| 1 | 打开页面 | 下拉 6 条，分段区「请先选择曲目。」，日志无报错 |
| 2 | 选 demo 16 → 选第 1 段 | 10 段列表、画布 10 字无拼音、教师提示齐全 |
| 3 | 点播放示范 | 日志失败提示（后端缺陷），按钮复位 |
| 4 | 选 demo 19（零分段） | 「该曲目还没解析出唱段。」，不报错 |
| 5 | 选 demo 1（无音频）→ 点播放 | 「该曲目没有示范音频」+ 按钮置灰 |
| 6 | 切回 demo 16 | 播放按钮**恢复可点** |
| 7 | 停掉后端（或断网）后刷新页面 | 日志「加载曲目列表失败：…」，下拉为空态，**页面不白屏** |
| 8 | 恢复后端，选 demo 17 / 18 | 分段数分别为 3 / 2，歌词与提示正常 |

第 7 条若不方便停后端，可用浏览器 DevTools 的 Network 面板设成 Offline 再刷新，效果等同。

- [ ] **Step 2: 复查没有越界改动**

```bash
git status --short
git diff --stat HEAD~2 -- . ':!sing_along.html' ':!docs'
```

预期：只有 `sing_along.html` 被改（外加 docs 与即将改的 `DOC_ISSUES.md`）。**不要出现 `app/`、`schema.sql`、`app-d.py`、`requirements.txt` 的改动。**

- [ ] **Step 3: 在 `DOC_ISSUES.md` 末尾追加第 40 条**

在文件末尾（`## 待核实` 一节**之前**）追加：

```markdown
## 40. 示范音频（B5）当前一条都放不出：`file_path` 形状与代码约定不符，且文件缺失

2026-10-09 做 `sing_along.html` 的「播放示范」时实测发现：`GET /api/audio/<file_id>`
（B5）对本项目全部示范曲目的音频**无一成功**。

### 40.1 实测

| audio id | 对应曲目 | 库里的 `file_path` | 磁盘上有文件 | B5 实测 |
|---|---|---|---|---|
| 75 | demo 16《穆桂英挂帅》 | `uploads/demos/muguaying_yuanmenwai.wav` | 有（19.7MB） | **400** |
| 76 | demo 17《贵妃醉酒》 | `uploads/demos/guifeizuijiu_haidaobinglun.wav` | 无 | **400** |
| 77 | demo 18《霸王别姬》 | `uploads/demos/bawangbieji_kandawang.wav` | 无 | **400** |
| 78 | demo 19《红娘》 | `uploads/demos/hongniang_jiaozhangsheng.wav` | 无 | **400** |
| 74 | demo 15 `01_xipi_1931` | `090e52c9fb8642ab95d3c7e431e0e2b5.wav` | 无 | **404** |

`400` 的响应体是统一信封的 `{"code":400,"message":"非法的音频文件名"}`。

### 40.2 两个互相独立的缺陷

**① `file_path` 形状与代码约定不符（数据错，不是代码错）。**

上传链路（`app/common/storage.py` 的 `save`）生成的是**裸文件名**（`uuid4().hex + 后缀`），
`storage.resolve()` 就按「相对 `upload_dir` 的名字」拼路径：

```python
root = settings.upload_dir.resolve()
path = (root / stored_name).resolve()
if path.parent != root:
    raise BusinessError(400, "非法的音频文件名")
```

而这 6 条数据的 `file_path` 带了 `uploads/` 前缀，被拼成 `uploads/uploads/demos/…`，
父目录不等于 `uploads/`，于是 400。**`resolve()` 的行为与它的文档字符串一致，它没错**——
错的是种进库里的那些值：它们记的是「相对项目根」的路径，而列的约定是「相对 `upload_dir`」。

**② 文件本身也不在。**

`uploads/demos/` 下**只有** `muguaying_yuanmenwai.wav` 一个文件（demo 16 那条）；
76/77/78 指向的文件在磁盘上根本不存在。audio 74 那个裸名文件同样不在 `uploads/` 下，故 404。
**所以即使把 ① 的路径形状改对，也只有 demo 16 一首能真正出声。**

### 40.3 影响与当前口径

- 影响面不止跟唱页：`demo_library.html` 的详情区、`pitch_comparison.html` 的分析链路
  （基准音频）只要走到「按 `file_id` 取示范音频」这一步，同样拿不到音频。
- **本轮（`docs/superpowers/specs/2026-10-09-sing-along-list-and-demo-playback-design.md`）
  不改后端、不改库、不动磁盘文件**：前端按 `<audio>` 的 `error` 事件降级为日志提示，
  播放链路的代码路径完整可验，但听不到声音。
- 修复需要两件事一起做：把 `file_path` 改成裸文件名（或让 `resolve()` 兼容带前缀的旧值，
  但那是给脏数据开口子，倾向于改数据），以及把缺失的音频文件补回 `uploads/`。
  **后者需要音频源文件，目前不在仓库里**（`../艺校_docs/` 只有另几个素材）。
```

- [ ] **Step 4: 提交**

```bash
git add DOC_ISSUES.md
git commit -m "docs: 登记 DOC_ISSUES 第 40 条——B5 放不出示范音频

file_path 带 uploads/ 前缀被 storage.resolve 拼成 uploads/uploads/… 判 400；
且 uploads/demos/ 下只有 1 个文件存在。即使修好路径，也只有 demo 16 能出声。"
```

---

## Self-Review

**Spec 覆盖**（逐节对回 `spec`）：

| spec 节 | 落在哪个任务 |
|---|---|
| §2.3 字段缺口（pinyin/subtitle/bpm/key 删除，pitch/duration 改名） | Task 1 Step 4/6/7/10/11/12 |
| §2.4 音频 url 懒加载 + 缓存 | Task 2 Step 3 |
| §2.5 B5 缺陷、本轮不修 | Task 2 Step 1、Task 3 Step 3 |
| §2.6 不显示 `elo_difficulty` | Task 1 Step 5（下拉只放 title） |
| §3 调用链四个时机 | Task 1 Step 5/9/14、Task 2 Step 3 |
| §4.1 状态改造 | Task 1 Step 3 |
| §4.2 逐函数改动表 | Task 1 Step 6–14、Task 2 Step 5/6 |
| §4.3 播放重写（放开选段、loadedmetadata、timeupdate、ended、画布不动） | Task 2 Step 2–6 |
| §5 六条容错 | Task 1 Step 8/9/10、Task 2 Step 5、Task 3 Step 1 |
| §6 非目标 | Global Constraints；Task 1 Step 11/12 明确「录制流程的模拟逻辑不动」 |
| §7 验证方式 | Task 1 Step 16、Task 2 Step 8、Task 3 Step 1 |
| §8 风险（接口复用、整首音频、残留「第一段」） | 无需实现，已随 spec 记录 |

**类型/命名一致性**：`apiGet` / `escapeHtml` / `demoTitle` / `loadDemos` / `loadSegments` / `resolveAudioUrl` / `demoAudio` / `audioUrlCache` / `audioError` / `currentDemoId` / `currentLyrics` / `segments` / `demos` 在三个任务里用法一致；`prepareTeacherCurve()` 与 `renderTeacherTips()` 在 Task 1 改为**无参**后，Task 2 未再以带参形式调用。

**两处已同步修正 spec，spec 与 plan 不再有分叉**：

1. spec §4.2 里「`updateProgress()` 分母改为音频总时长」已改成「**不改**，播放走自己的 `timeupdate` 处理器」——两个模式共用一个函数会让录制时的进度条也被整首时长污染。
2. spec §7 的验证口径已按 §2.5 的缺陷改成「播放只验链路不验声音」。
