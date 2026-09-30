# 功能 9.6 标注规则列表页面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `annotation.html` 页尾新增「全库标注规则」卡片，走 C7 `GET /api/annotations/rules` 展示全库标注，支持按 `tag` 与 `word` 服务端筛选。

**Architecture:** 单文件自包含页面的常规做法——卡片 HTML 插在两栏网格之后、CSS 插在本页既有 `<style>` 内、JS 插在本页主 `<script>` 末尾。数据流是「改筛选条件 → 重新请求 C7 → 整表重画」，与左侧 C1–C6 的既有写法一致。

**Tech Stack:** 纯静态 HTML + 原生 JS（无构建、无依赖、无框架），对接已实现的 Flask 后端 C7。

## Global Constraints

- **只改 `annotation.html` 一个前端文件**（外加 `DOC_ISSUES.md`）。不动其它 10 个 `.html`、不动 `app/` 下任何后端代码、不动 `schema.sql`。
- **不动 `:root` 设计 token**（`annotation.html:11-41`）。新样式一律复用既有变量。
- **所有请求必须同源相对路径 + `credentials: 'same-origin'`**。写成 `location.host + ':8877'` 那样的跨源地址时 fetch 默认不带 Cookie，后端 `login_required` 只看到空 session 并回 401。
- **数据安全**：验证过程中如需插行，只能按抓到的 id 删。当前 `annotations` 表有 **3 行真数据（id 109 / 110 / 111）**，`DELETE FROM annotations;` 会不可恢复地删掉它们。
- **无测试框架**（无 `tests/`、`requirements.txt` 里无 pytest，别去装）。验证手段是：`node --check` 语法门禁 + `curl` 对真接口 + 浏览器人工核对 + `docker exec docker_postgres psql` 查库。
- **不做**：分页、列排序、导出、行内编辑/删除、点行跳转、与左侧歌词网格的联动。
- **中文输入法**：`input` 事件在拼音合成期间就会触发，必须按 Task 3 的写法处理，否则打一个字会发多次请求。
- 服务已在跑：Flask `127.0.0.1:8877`、nginx `:80`。页面可直连 `http://127.0.0.1:8877/annotation.html` 验证（未登录 302）。

---

## 前置事实（动手前必须知道）

### 页面结构与行号基线

`annotation.html` 共 **1183 行**。本计划引用的行号均以此为准；**每个任务的 Step 都给了「改前原文」，请按文本匹配定位，不要只认行号**。

```
 11-41   :root 设计 token
340-346  .ann-tag 的 5 条规则（全部挂在 .annotation-item 之下）
382-383  .empty-state / .empty-icon（无作用域前缀，可直接复用）
441      <div class="page-header">
446      <div class="piece-selector" id="pieceSelector">
448      <div class="piece-selector" id="segmentSelector">
451      <div style="display:grid;grid-template-columns:1.5fr 1fr;gap:16px">   两栏网格
525      </div>          网格闭合   ← 卡片插在这之后
526      </main>
535-1111 <script>  主脚本
745      showToast("success", "已添加标注", ...)
746      clearTagSelection();
750      if (segments[currentSegIdx] !== seg) return;      ← 第 1 个 return
752      if (!annLoaded) {                                  ← 第 2 个 return 的分支
843      renderLyrics();   （deleteAnnotation 末尾）
1066-1068 let annReqToken / annEmptyMsg / annEmptyIcon
1108-1110 renderLyrics(); renderAnnotations(); fetchDemos();
```

### 三个容易踩的坑

1. **`.ann-tag` 不能直接复用。** 它的基础规则与四个 `tag-*` 配色**全部挂在 `.annotation-item` 之下**（340–346 行），表格里写 `class="ann-tag"` 会一点样式都没有。Task 1 把选择器扩成并列选择器解决。
2. **`word_index` 是 0 基。** C5 的 `Field(ge=0)`、C3/C5/C7 的归一函数都按 0 基走。显示时要 `+1`，否则会出现「第 0 字」。
3. **`created_at` 已经是北京时间。** 库里是 `TIMESTAMP`（naive），DB 服务器时区实测 `Asia/Shanghai`。**不要**套 `AT TIME ZONE`，也**不要**走 `new Date()`。

### 语法门禁（每个任务收尾都跑）

前端没法单测，但可以先过一道语法关——它能在不打开浏览器的情况下抓住绝大多数手误：

```bash
python3 -c "
import re
s=open('annotation.html',encoding='utf-8').read()
b=re.findall(r'<script>(.*?)</script>', s, re.S)
open('/tmp/ann.js','w',encoding='utf-8').write('\n;\n'.join(b))
" && node --check /tmp/ann.js && echo "语法 OK"
```

（已在改动前的基线上实测通过：识别出 2 个 `<script>` 块，`node --check` 无输出、退出码 0。）

---

## Task 1: 卡片骨架、CSS 与空态

**Files:**
- Modify: `annotation.html`（三处：`.ann-tag` 选择器扩展、`<style>` 追加、`<main>` 末尾插卡片）

**Interfaces:**
- Consumes: 无
- Produces: DOM 元素 `#ruleTagFilter` `#ruleWordInput` `#ruleList` `#ruleCount`；后续任务往这些元素里渲染

- [ ] **Step 1: 扩展 `.ann-tag` 的 5 条选择器**

定位 `annotation.html:340-346`，把

```css
.annotation-item .ann-tag{
  padding:1px 6px;border-radius:3px;font-size:10px;font-weight:700;
}
.annotation-item .ann-tag.tag-articulation{background:rgba(0,102,179,0.10);color:var(--primary)}
.annotation-item .ann-tag.tag-breath{background:rgba(74,143,107,0.10);color:var(--success)}
.annotation-item .ann-tag.tag-pitch{background:rgba(201,168,76,0.10);color:var(--warning)}
.annotation-item .ann-tag.tag-rhythm{background:rgba(184,58,47,0.10);color:var(--danger)}
```

整体替换为

```css
/* 技法药丸。选择器是并列的：全库规则表格（功能 9.6）也用它，
   但两处的祖先元素不同，只写 .annotation-item 那条表格里会没有样式。
   扩并列而不是在表格的 CSS 里重抄一份颜色——两份十六进制色值迟早漂移。 */
.annotation-item .ann-tag,
.rule-table .ann-tag{
  padding:1px 6px;border-radius:3px;font-size:10px;font-weight:700;
}
.annotation-item .ann-tag.tag-articulation,
.rule-table .ann-tag.tag-articulation{background:rgba(0,102,179,0.10);color:var(--primary)}
.annotation-item .ann-tag.tag-breath,
.rule-table .ann-tag.tag-breath{background:rgba(74,143,107,0.10);color:var(--success)}
.annotation-item .ann-tag.tag-pitch,
.rule-table .ann-tag.tag-pitch{background:rgba(201,168,76,0.10);color:var(--warning)}
.annotation-item .ann-tag.tag-rhythm,
.rule-table .ann-tag.tag-rhythm{background:rgba(184,58,47,0.10);color:var(--danger)}
```

**这一步不改变左侧标注列表的任何渲染结果**——只是把同样一份声明多挂一个祖先选择器。

- [ ] **Step 2: 在 `<style>` 里追加新样式**

定位 `annotation.html:361` 的 `/* ===== Toast ===== */`，在它**之前**插入：

```css
/* ===== 全库标注规则（功能 9.6 / C7 GET /api/annotations/rules） ===== */
.rule-filter{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 10px}
/* 复用 .piece-btn，只是比曲目/唱段那排再低一层：字号与内边距都收小 */
.rule-filter .piece-btn{font-size:12px;padding:6px 12px}
.rule-word{
  padding:6px 12px;border:2px solid var(--border-light);border-radius:8px;
  background:var(--bg-secondary);color:var(--text-primary);
  font-size:12px;font-family:inherit;font-weight:600;width:150px;margin-bottom:10px;
}
.rule-word:focus{outline:none;border-color:var(--primary)}
.rule-table{width:100%;border-collapse:collapse;font-size:12px}
.rule-table th{
  text-align:left;padding:8px 10px;color:var(--text-muted);
  font-weight:600;border-bottom:1px solid var(--border-light);
}
.rule-table td{
  padding:8px 10px;border-bottom:1px solid var(--border-light);
  color:var(--text-secondary);
}
/* word_index 的「第 N 字」小字，比单元格正文轻一档 */
.rule-table .rule-idx{color:var(--text-muted);font-size:11px}
```

- [ ] **Step 3: 在 `<main>` 末尾插入卡片**

定位 `annotation.html:525-526`，即两栏网格的闭合 `</div>` 与 `</main>`：

```html
  </div>
</main>
```

在两者之间插入（缩进与同级元素对齐）：

```html
  <!-- 全库标注规则（功能 9.6 / C7 GET /api/annotations/rules）
       由页末 fetchRules() 渲染 -->
  <div class="card" style="margin-top:16px">
    <div class="card-header">
      <div class="card-title">
        <div class="icon" style="background:var(--primary-soft);color:var(--primary)">📋</div>
        全库标注规则
      </div>
      <span class="card-subtitle" id="ruleCount"></span>
    </div>
    <div class="rule-filter" id="ruleTagFilter"></div>
    <input class="rule-word" id="ruleWordInput" maxlength="1" placeholder="输入一个字筛选">
    <div id="ruleList"></div>
  </div>
```

- [ ] **Step 4: 跑语法门禁**

Run:
```bash
python3 -c "
import re
s=open('annotation.html',encoding='utf-8').read()
b=re.findall(r'<script>(.*?)</script>', s, re.S)
open('/tmp/ann.js','w',encoding='utf-8').write('\n;\n'.join(b))
" && node --check /tmp/ann.js && echo "语法 OK"
```
Expected: `语法 OK`（本步只改 HTML/CSS，JS 未动，必然通过——它是防手滑的基线）

- [ ] **Step 5: 浏览器核对骨架**

打开 `http://127.0.0.1:8877/annotation.html`（用 `teacher01` / `xiyun@2026` 登录）。

Expected:
- 页面最下方出现一张卡片，标题「📋 全库标注规则」
- 卡片内有三块空白区域（筛选按钮行、输入框、列表区），**都还没有内容**——这是本任务的预期状态
- 左上「歌词网格」与右上「老师标注」的渲染**与改动前完全一致**（Step 1 扩选择器没有副作用）
- 右上「已添加标注规则」的小药丸仍有颜色（验证 Step 1 没写坏那 5 条规则）

- [ ] **Step 6: 提交**

```bash
git add annotation.html
git commit -m "feat: 标注页新增全库规则卡片骨架（功能 9.6）"
```

---

## Task 2: 拉数据、渲染表格与四种空态

**Files:**
- Modify: `annotation.html`（主 `<script>` 末尾插入一整段 + 初始化多一行）

**Interfaces:**
- Consumes: Task 1 建的 `#ruleList` `#ruleCount`；本页既有的 `TAG_CATEGORY`（774 行）
- Produces: `fetchRules()`（无参、无返回值，async）、`renderRules(rows)`、`fmtRuleTime(v)`；状态变量 `ruleTag` / `ruleWord` / `ruleReqToken` / `ruleEmptyMsg` / `ruleEmptyIcon` / `ruleCountable`

- [ ] **Step 1: 插入 C7 数据层**

定位 `annotation.html:1105-1108`：

```js
  renderLyrics();
}

renderLyrics();
renderAnnotations();
fetchDemos();
```

在 `}` 与 `renderLyrics();` 之间插入：

```js
// ============================================
// 全库标注规则（功能 9.6 / C7 GET /api/annotations/rules）
// ============================================

// 筛选条件。ruleTag 的 null 表示「全部」（＝不发 tag 参数）——它不是词表的
// 第七项。六个技法名从 TAG_CATEGORY 取键，与左侧六个 .type-btn、与后端的
// ANNOTATION_TAGS 同源，不另抄一份字面量。
let ruleTag = null;
let ruleWord = "";

// 竞态守卫，见 fetchRules。**必须与 annReqToken 分开**：全库规则与左侧标注
// 列表是两条互不相干的请求流，共用一个计数器会让「切唱段」把「筛字」的响应
// 判成过期，反之亦然。
let ruleReqToken = 0;

// 空态文案与图标，由 fetchRules 按情形改写（同 annEmptyMsg / annEmptyIcon 的做法）
let ruleEmptyMsg = "加载中…";
let ruleEmptyIcon = "📋";

// 只有「拿到了服务端答案」才计数。403 与网络失败时清空——那种情况下
// 「共 0 条」是句假话
let ruleCountable = false;

async function fetchRules() {
  // 领号必须在 await 之前；await 之后再领就等于没领（同 fetchAnnotations）
  const token = ++ruleReqToken;

  // 只带非缺省的条件：都不设时查询串为空，等价于全库。
  // 不传空串——后端 ?word= 会收敛成「不筛」，结果虽同，但会让「没输入」与
  // 「输入了空」在网络层无法区分，排查时多一层困惑。
  const qs = new URLSearchParams();
  if (ruleTag !== null) qs.set("tag", ruleTag);
  if (ruleWord !== "") qs.set("word", ruleWord);

  let rows;
  try {
    // 同源相对路径 + same-origin：写成跨源地址时 fetch 默认不带 Cookie，
    // 后端 login_required 只看得到空 session 并回 401（同 C1–C6）
    const r = await fetch(`/api/annotations/rules?${qs}`, { credentials: "same-origin" });

    // 403 单独判：C7 挂的是 @teacher_required，学生打开本页就会撞上
    // （页面级鉴权只管登录，不管教师）。用 r.status 而不是 body.code——后者
    // 只是 HTTP 状态码的同值副本，且 r.json() 本身也可能失败。判在 r.json()
    // 之前，非 JSON 的响应体不会把这里也拖进下面的 catch。
    if (r.status === 403) {
      if (token !== ruleReqToken) return;
      ruleCountable = false;
      ruleEmptyMsg = "全库规则仅教师可见";
      ruleEmptyIcon = "🔒";
      renderRules([]);
      return;
    }

    const body = await r.json();
    if (!r.ok || body.code !== 0) throw new Error(body.message || String(r.status));
    rows = body.data || [];
  } catch (e) {
    // 期间又改过筛选条件的话，这个失败属于上一次查询，不该覆盖当前状态
    if (token !== ruleReqToken) return;
    ruleCountable = false;
    ruleEmptyMsg = "规则列表加载失败";
    ruleEmptyIcon = "⚠️";
    renderRules([]);
    return;
  }

  // 判定必须在 await 之后：快速连点两个筛选条件时，先发的慢响应可能后到
  if (token !== ruleReqToken) return;

  if (rows.length === 0) {
    // 「库里还没规则」与「筛出来没有」是两回事，文案必须分开——
    // 同 fetchDemos 里「拿不到」与「确实没有」的口径
    if (ruleTag !== null || ruleWord !== "") {
      ruleEmptyMsg = "没有匹配的规则";
      ruleEmptyIcon = "🔍";
    } else {
      ruleEmptyMsg = "库里还没有标注规则";
      ruleEmptyIcon = "📋";
    }
  }

  // 成功路径无条件把计数打开：否则「先失败、再筛到有数据」会一直不计数
  // （同 fetchAnnotations 复位 annEmptyMsg 的理由——上一次的失败状态不该留下）
  ruleCountable = true;
  renderRules(rows);
}

function fmtRuleTime(v) {
  // created_at 在库里是 TIMESTAMP（naive），DB 时区 Asia/Shanghai，拿到的
  // 已经是北京时间，不做换算。也不走 new Date()：一是没必要换算，二是它对
  // 无时区 ISO 串的解析行为在 ES5 / ES2016+ 之间变过（UTC vs 本地），
  // 切字符串没有这层歧义。
  if (!v) return "—";
  const s = String(v);
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(s)
    ? s.slice(5, 10) + " " + s.slice(11, 16)
    : s;
}

function esc(v) {
  // demo_title / segment_title 是教师上传时自己填的，char 来自 lyrics_json，
  // tag 来自库里——都是不可信字符串。这段是本页唯一渲染非本页产出文本的地方，
  // 拼进 innerHTML 前一律转义。
  // 左侧 renderAnnotations 用的是同一套拼法但没转义，那是既有代码，本轮不动。
  return String(v).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function renderRules(rows) {
  const list = document.getElementById("ruleList");
  const count = document.getElementById("ruleCount");

  // 「共」与「筛出」必须分开：把「筛出 3 条」读成「全库共 3 条」，就完全违背了
  // 功能 9.6 的用途——全库有多少条规则，这个数字要是对的
  const filtered = (ruleTag !== null || ruleWord !== "");
  count.textContent = ruleCountable
    ? `${filtered ? "筛出" : "共"} ${rows.length} 条`
    : "";

  if (rows.length === 0) {
    list.innerHTML =
      `<div class="empty-state"><div class="empty-icon">${ruleEmptyIcon}</div>${ruleEmptyMsg}</div>`;
    return;
  }

  list.innerHTML = `<table class="rule-table">
    <thead><tr>
      <th>曲目</th><th>唱段</th><th>字</th><th>技法</th><th>容忍度</th><th>标注时间</th>
    </tr></thead>
    <tbody>${rows.map((r) => {
      // char 为 null 时显示 "?" 而不是留空：同左侧 annChar() 的兜底口径——
      // 取不到是数据问题（segment_id 为空 / lyrics_json 为空 / 下标越界），
      // 要让人看见，不是藏起来
      const ch = (r.char === null || r.char === undefined) ? "?" : r.char;
      // word_index 是 0 基（C5 的 Field(ge=0) 也这么约束），显示「第 0 字」不通顺
      const idx = `<span class="rule-idx">第 ${r.word_index + 1} 字</span>`;
      // tag 认不出来时 TAG_CATEGORY 取不到值，拼出的 tag-undefined 没有对应
      // 样式规则，落回 .ann-tag 的基础外观。不兜底成某个已知类——那是给一个
      // 不认识的 tag 硬安一个语义配色（同左侧 renderAnnotations 的口径）
      const cat = TAG_CATEGORY[r.tag] || "";
      // tolerance / created_at / 归属在 DDL 上均可空，为 null 显示「—」。
      // 这与左侧 .ann-tol 不同——那里是 flex，少一格不影响别人；表格里
      // 少一格会让整列错位
      const tol = (r.tolerance === null || r.tolerance === undefined)
        ? "—" : `±${r.tolerance}c`;
      return `<tr>
        <td>${esc(r.demo_title || "—")}</td>
        <td>${esc(r.segment_title || "—")}</td>
        <td>${esc(ch)} ${idx}</td>
        <td><span class="ann-tag tag-${cat}">${esc(r.tag)}</span></td>
        <td>${tol}</td>
        <td>${fmtRuleTime(r.created_at)}</td>
      </tr>`;
    }).join("")}</tbody>
  </table>`;
}
```

- [ ] **Step 2: 初始化时拉一次**

把 `annotation.html:1108-1110` 的

```js
renderLyrics();
renderAnnotations();
fetchDemos();
```

改成

```js
renderLyrics();
renderAnnotations();
fetchDemos();
fetchRules();   // 全库标注规则（功能 9.6），不带参数 = 全库
```

- [ ] **Step 3: 跑语法门禁**

Run:
```bash
python3 -c "
import re
s=open('annotation.html',encoding='utf-8').read()
b=re.findall(r'<script>(.*?)</script>', s, re.S)
open('/tmp/ann.js','w',encoding='utf-8').write('\n;\n'.join(b))
" && node --check /tmp/ann.js && echo "语法 OK"
```
Expected: `语法 OK`。若报 SyntaxError，按提示的行号回到 `/tmp/ann.js` 里定位（它是两个 script 块拼起来的，行号与 `annotation.html` 不直接对应，用报错附近的代码片段认）。

- [ ] **Step 4: 用 curl 取一份真数据当对照基准**

Run:
```bash
curl -s -c /tmp/ck.txt -X POST http://127.0.0.1:8877/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"teacher01","password":"xiyun@2026"}' -o /dev/null
curl -s -b /tmp/ck.txt 'http://127.0.0.1:8877/api/annotations/rules' | python3 -m json.tool
```
Expected: `code: 0`，`data` 是 3 行。**2026-09-30 实测的返回值**（若库未变动应与下表逐字一致）：

| id | char | word_index | tag | tolerance | created_at | segment_title | demo_title |
|---|---|---|---|---|---|---|---|
| 109 | 三 | 3 | 归韵 | 30 | 2026-09-30T09:00:15.033074 | 辕门外三声炮如同雷震 | 《穆桂英挂帅》· 辕门外三声炮 |
| 110 | 同 | 7 | 拖腔 | 30 | 2026-09-30T09:00:32.246823 | 辕门外三声炮如同雷震 | 《穆桂英挂帅》· 辕门外三声炮 |
| 111 | 震 | 9 | 强音 | 37 | 2026-09-30T09:01:09.529824 | 辕门外三声炮如同雷震 | 《穆桂英挂帅》· 辕门外三声炮 |

> 若登录接口的字段名与上面不符，改用页面登录后用浏览器 devtools 抄一份响应；**不要**因为 curl 这一步失败就跳过对照。

- [ ] **Step 5: 浏览器核对表格**

刷新 `http://127.0.0.1:8877/annotation.html`。

Expected（逐项对照 Step 4 的 curl 输出）。按 2026-09-30 的实测数据，表格应当是：

| 曲目 | 唱段 | 字 | 技法 | 容忍度 | 标注时间 |
|---|---|---|---|---|---|
| 《穆桂英挂帅》· 辕门外三声炮 | 辕门外三声炮如同雷震 | 三 第 4 字 | 归韵 | ±30c | 09-30 09:00 |
| 《穆桂英挂帅》· 辕门外三声炮 | 辕门外三声炮如同雷震 | 同 第 8 字 | 拖腔 | ±30c | 09-30 09:00 |
| 《穆桂英挂帅》· 辕门外三声炮 | 辕门外三声炮如同雷震 | 震 第 10 字 | 强音 | ±37c | 09-30 09:01 |

逐项核对：
- 卡片标题右侧显示 **「共 3 条」**
- 六列表头依次是：曲目 / 唱段 / 字 / 技法 / 容忍度 / 标注时间
- 曲目列是 `teacher_demos.title` 的完整值——**带书名号与间隔点**（`《穆桂英挂帅》· 辕门外三声炮`），不是「穆桂英挂帅」
- 「字」列的 N 比库里的 `word_index` **大 1**（`word_index` 3 / 7 / 9 → 第 4 / 8 / 10 字）
- 技法列是彩色药丸，颜色与右上角标注列表里同一个 tag 的颜色一致
- 时间列是 `MM-DD HH:mm` 短串，与 `created_at` 的月日时分一致（**不是**原始 ISO 串整串）

- [ ] **Step 6: 提交**

```bash
git add annotation.html
git commit -m "feat: 标注页全库规则接上 C7 并渲染表格"
```

---

## Task 3: 筛选交互（tag 按钮 + 单字输入框）

**Files:**
- Modify: `annotation.html`（主 `<script>` 的 C7 段内插入两个控件初始化函数；初始化列表多加一行）

**Interfaces:**
- Consumes: Task 2 的 `fetchRules()`、`ruleTag` / `ruleWord`；Task 1 建的 `#ruleTagFilter` `#ruleWordInput`；本页既有的 `.type-btn` 按钮组（492–497 行）与其 `data-tag`
- Produces: `renderRuleTagFilter()`、`applyRuleWord(v)`；两处写路径（C5/C6 成功回调）将调用 Task 2 的 `fetchRules()`

- [ ] **Step 1: 插入筛选控件逻辑**

定位 Task 2 插入内容里 `function renderRules(rows) {` 这一行，在它**之前**插入：

```js
function renderRuleTagFilter() {
  const box = document.getElementById("ruleTagFilter");
  // 「全部」是本地概念（＝不发 tag 参数），不是词表的第七项。
  // 六个技法名与顺序都取自左侧那六个 .type-btn——它们是本页技法词表的
  // 显示真源（后端的 ANNOTATION_TAGS 是写入校验的真源，TAG_CATEGORY 是
  // 配色的真源）。从 DOM 取而不是写 `Object.keys(TAG_CATEGORY)`：后者的
  // 键序是 滑音/归韵/擞音/换气/强音/拖腔，与左侧按钮的显示顺序不一致。
  const tags = [...document.querySelectorAll(".type-btn")].map((b) => b.dataset.tag);
  const items = [null, ...tags];

  box.innerHTML = items.map((t) => {
    // data-tag 用空串表示「全部」：null 塞进 HTML 属性会变成字符串 "null"
    const v = t === null ? "" : t;
    const active = t === ruleTag ? " active" : "";
    return `<button class="piece-btn${active}" data-tag="${v}">${t === null ? "全部" : t}</button>`;
  }).join("");

  box.querySelectorAll(".piece-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const next = btn.dataset.tag === "" ? null : btn.dataset.tag;
      // 点已经选中的那个按钮不重发请求
      if (next === ruleTag) return;
      ruleTag = next;
      renderRuleTagFilter();   // 重画以更新 .active
      fetchRules();
    });
  });
}

function applyRuleWord(v) {
  // 值没变就不重发：compositionend 之后浏览器往往还会补一个
  // isComposing === false 的 input 事件，不去重就会为同一个词发两次请求
  if (v === ruleWord) return;
  ruleWord = v;
  fetchRules();
}

function initRuleWordInput() {
  const input = document.getElementById("ruleWordInput");
  // 中文输入法：拼音合成阶段浏览器就会发 input 事件。不挡的话，打「san」
  // 会依次按 s → a → n 各请求一次，而且 maxlength 在合成期间不生效，
  // 最后一个字母可能被留下来当筛选条件。
  // 不做 debounce：一个字就是一次完整查询，没有中间态可言。
  input.addEventListener("input", (e) => {
    if (e.isComposing) return;   // 合成中，不是最终输入
    applyRuleWord(input.value);
  });
  input.addEventListener("compositionend", () => {
    applyRuleWord(input.value);
  });
}
```

- [ ] **Step 2: 初始化时把控件画出来**

把 Task 2 改过的初始化块

```js
renderLyrics();
renderAnnotations();
fetchDemos();
fetchRules();   // 全库标注规则（功能 9.6），不带参数 = 全库
```

改成

```js
renderLyrics();
renderAnnotations();
fetchDemos();
// 全库标注规则（功能 9.6）。控件先画、再拉数据：顺序反过来的话，
// 拉回来时按钮还不存在，筛不动
renderRuleTagFilter();
initRuleWordInput();
fetchRules();
```

- [ ] **Step 3: 跑语法门禁**

Run:
```bash
python3 -c "
import re
s=open('annotation.html',encoding='utf-8').read()
b=re.findall(r'<script>(.*?)</script>', s, re.S)
open('/tmp/ann.js','w',encoding='utf-8').write('\n;\n'.join(b))
" && node --check /tmp/ann.js && echo "语法 OK"
```
Expected: `语法 OK`

- [ ] **Step 4: curl 出每个 tag 的期望行数**

Run:
```bash
for t in 滑音 归韵 换气 强音 拖腔 擞音; do
  printf '%s: ' "$t"
  curl -s -b /tmp/ck.txt --get --data-urlencode "tag=$t" \
    http://127.0.0.1:8877/api/annotations/rules | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["data"]))'
done
```
Expected（2026-09-30 实测；若库未变动应逐行一致）：

```
滑音: 0
归韵: 1
换气: 0
强音: 1
拖腔: 1
擞音: 0
```

**注意 `滑音` / `换气` / `擞音` 是 0**——这正好提供了一个真实的「筛选无匹配」用例，下一步要用上。

- [ ] **Step 5: 浏览器核对筛选**

刷新页面。

Expected：
- 筛选行显示 7 个按钮：`全部 滑音 归韵 换气 强音 拖腔 擞音`，**顺序与左侧六个类型按钮一致**，`全部` 默认高亮
- 逐个点六个技法按钮，逐项对照 Step 4 的数字：

  | 点这个按钮 | 表格行数 | 计数 |
  |---|---|---|
  | 滑音 | 0（显示「🔍 没有匹配的规则」） | 筛出 0 条 |
  | 归韵 | 1（只有「三」那行） | 筛出 1 条 |
  | 换气 | 0（同上） | 筛出 0 条 |
  | 强音 | 1（只有「震」那行） | 筛出 1 条 |
  | 拖腔 | 1（只有「同」那行） | 筛出 1 条 |
  | 擞音 | 0（同上） | 筛出 0 条 |

- 点回`全部`：回到 3 行、计数「共 3 条」
- 输入框输入「三」：只剩「三」那一行，计数「筛出 1 条」
- 输入框删空：回到 3 行、计数「共 3 条」
- 输入一个字库里没有的字（如「喵」）：列表显示「🔍 没有匹配的规则」、计数「**筛出 0 条**」
- **输入法验证**：切到拼音输入法打一个字，devtools 的 Network 面板应只出现**一次** `annotations/rules` 请求（不是每个字母一次）

- [ ] **Step 6: 提交**

```bash
git add annotation.html
git commit -m "feat: 标注页全库规则支持按技法与字筛选"
```

---

## Task 4: 写操作后刷新全库列表

**Files:**
- Modify: `annotation.html`（`saveAnnotation()` 与 `deleteAnnotation()` 各加一行调用）

**Interfaces:**
- Consumes: Task 2 的 `fetchRules()`
- Produces: 无（本任务只加调用点）

- [ ] **Step 1: `saveAnnotation` 写成功后刷新**

定位 `annotation.html:745-752`：

```js
  showToast("success", "已添加标注", annNote({ index: row.word_index, tag: row.tag }));
  clearTagSelection();

  // 期间切走了唱段的话，这一行属于旧唱段，不能插进新唱段的列表；也不该再为
  // 旧唱段发一次 GET——fetchAnnotations 会领新号，把当前唱段的结果顶掉
  if (segments[currentSegIdx] !== seg) return;

  if (!annLoaded) {
```

改成

```js
  showToast("success", "已添加标注", annNote({ index: row.word_index, tag: row.tag }));
  clearTagSelection();

  // 写已经落库，全库规则列表的行与计数此刻就过期了，带当前筛选条件重拉一次。
  // **必须放在下面两个 return 之前**：它们是「用户快速操作」的常见路径
  // （切走了唱段 / 本地列表本来就不完整），也恰恰是全库列表最容易陈旧的时刻。
  // 不 await：toast 与左侧列表的更新不该等这一次请求（同 switchPiece 调
  // fetchSegments 的口径）
  fetchRules();

  // 期间切走了唱段的话，这一行属于旧唱段，不能插进新唱段的列表；也不该再为
  // 旧唱段发一次 GET——fetchAnnotations 会领新号，把当前唱段的结果顶掉
  if (segments[currentSegIdx] !== seg) return;

  if (!annLoaded) {
```

- [ ] **Step 2: `deleteAnnotation` 写成功后刷新**

定位 `annotation.html:838-844`：

```js
  showToast("success", "已删除标注", annNote(ann));
  const i = annotations.findIndex((a) => a.id === id);
  if (i >= 0) annotations.splice(i, 1);
  renderAnnotations();
  renderLyrics();   // 格子上的 ✓ 由 renderLyrics 画，删了要重画一次
}
```

改成

```js
  showToast("success", "已删除标注", annNote(ann));
  const i = annotations.findIndex((a) => a.id === id);
  if (i >= 0) annotations.splice(i, 1);
  renderAnnotations();
  renderLyrics();   // 格子上的 ✓ 由 renderLyrics 画，删了要重画一次
  // 同 saveAnnotation：全库规则列表的行与计数此刻已经过期
  fetchRules();
}
```

- [ ] **Step 3: 跑语法门禁**

Run:
```bash
python3 -c "
import re
s=open('annotation.html',encoding='utf-8').read()
b=re.findall(r'<script>(.*?)</script>', s, re.S)
open('/tmp/ann.js','w',encoding='utf-8').write('\n;\n'.join(b))
" && node --check /tmp/ann.js && echo "语法 OK"
```
Expected: `语法 OK`

- [ ] **Step 4: 记下改动前的行数基线**

Run:
```bash
docker exec docker_postgres psql -U xiyun -d xiyun -tAc "SELECT count(*) FROM annotations;"
docker exec docker_postgres psql -U xiyun -d xiyun -tAc "SELECT id FROM annotations ORDER BY id;"
```
Expected: `3`，以及 `109` / `110` / `111`。**把这两个输出抄下来**，后面每一步都要用它比对、收尾时要按 id 删回去。

> 若数据库连接参数与此不符，README/`.env` 里的 `DATABASE_URL` 是准的，按它来。

- [ ] **Step 5: 浏览器核对一致性**

刷新页面，全库卡片应显示「共 3 条」。然后：

1. 在左侧歌词网格点一个字 → 选一个当前没选中的技法（比如该字还没标「擞音」就选擞音）→ 点「添加标注」
   - Expected：左侧列表多一条；**全库卡片变成「共 4 条」且表格多一行**
2. 记下刚新增那行的内容，回到左侧在「已添加标注规则」里点它右边的 ✕ → 确认删除
   - Expected：左侧少一条；**全库卡片回到「共 3 条」**
3. **带筛选时的一致性**：先点筛选按钮「拖腔」（库里拖腔只有 1 条）→ 此时计数「筛出 1 条」→ 去左侧加一条「擞音」的标注
   - Expected：全库卡片**仍是拖腔的那 1 行、计数仍是「筛出 1 条」**（新加的那条不属于当前筛选，就不该出现）；点回「全部」才看得到它变成 3+1=4 条
4. 重复 Step 4 的两条 psql，确认行数与 id 集合与基线**完全一致**

- [ ] **Step 6: 提交**

```bash
git add annotation.html
git commit -m "feat: 标注增删后同步刷新全库规则列表"
```

---

## Task 5: 登记 DOC_ISSUES 与整体回归

**Files:**
- Modify: `DOC_ISSUES.md`（新增第 33 条；更新第 32.4 条的第 5 项）

**Interfaces:**
- Consumes: 前四个任务的全部产出
- Produces: 无

- [ ] **Step 1: 更新第 32.4 条「待确认」第 5 项**

定位 `DOC_ISSUES.md` 第 32.4 节里的：

```markdown
5. **C7 目前没有任何前端调用方**。功能 9.6 在 `annotation.html` 里没有对应 UI，本项目也没有别的页面会调它。接口先落地，页面是否属于本期范围待文档方确认。
```

改成：

```markdown
5. ~~**C7 目前没有任何前端调用方**。功能 9.6 在 `annotation.html` 里没有对应 UI，本项目也没有别的页面会调它。~~ **2026-09-30 补**：功能 9.6 的 UI 已落地在 `annotation.html` 页尾（见第 33 条），C7 现在有调用方了。本条不再成立，保留原文以便追溯接口与页面分两批交付这件事。
```

- [ ] **Step 2: 新增第 33 条**

定位 `DOC_ISSUES.md` 里的 `## 待核实` 一行（第 967 行附近），在它**之前**插入：

```markdown
## 33. 功能 9.6 的 UI 归属页、`word` 的输入形态、教师页面的学生可见性，文档均未规定

功能 9.6「标注规则列表管理 ｜ 集中展示+筛选」的页面侧于 2026-09-30 落地，实现见 `docs/superpowers/specs/2026-09-30-annotation-rules-page-design.md`、计划见 `docs/superpowers/plans/2026-09-30-annotation-rules-page.md`、提交见 `annotation.html`。以下是本轮自拟的口径。

### 33.1 本轮自拟口径

| 项 | 文档给的 | 本轮自拟 | 依据 |
|---|---|---|---|
| UI 落在哪一页 | **什么都没有** | 并进 `annotation.html` 页尾 | 《3-功能清单》模块 9「歌词级标注」下 9.1–9.7 七个功能点，其中 9.1–9.5、9.7 都已实现在 `annotation.html`；9.6 是同一模块唯一缺的一块，不是新模块 |
| 页面形态 | 「集中展示+筛选」 | 页面最下方一张通栏卡片 | 作用域自上而下从窄到宽：选曲目/唱段 → 改这一个唱段 → 看全库。右上「已添加标注规则」只含当前唱段，两者中间隔着整块歌词区 |
| 行上能做什么 | 未规定 | **只读**，无跳转、无就地删除 | 文档 9.6 的说明只有「集中展示+筛选」，没提编辑；改动一律回左侧单唱段标注区（9.1–9.5、9.7 已齐） |
| 筛选在哪一侧做 | 未规定 | **服务端**，每次改条件带 `tag`/`word` 重新请求 C7 | C7 已给出这两个参数；且 `word` 匹配的是归一后的字，该语义只有后端有，前端自己过滤要复刻一遍，容易与后端漂移 |
| `word` 输入框形态 | 未规定 | `<input maxlength="1">` 单字 | 与第 32.4 条第 1 问自拟的「精确等于一个字」对齐；UI 直接表达真实语义，用户不会对它抱「搜子串」的期待 |
| tag 控件 | 未规定 | 「全部」+ 六个技法，互斥按钮组 | 「全部」是本地概念（＝不发 `tag` 参数），**不是词表的第七项**；六个技法名与顺序取自左侧既有 `.type-btn` |
| 计数文案 | 未规定 | 无筛选时「共 N 条」，有筛选时「筛出 N 条」 | 只写「共 N 条」的话，筛出 3 条会被读成「全库共 3 条」，与 9.6 的用途直接冲突 |

### 33.2 学生能看到教师工作台页面

页面级鉴权（`page_login_required`）只要求**登录**，不要求教师。`annotation.html` 页末脚本虽然算了 `isTeacher`（`annotation.html:1143`），但只用于显示姓名与头像，没有用它拦任何内容。因此：

- 学生能打开 `annotation.html`
- 左侧 C4（教师专属）回 403，既有代码统一显示「标注加载失败」——**对学生是误导性文案**
- 本轮新增的全库块对 403 显示「🔒 全库规则仅教师可见」（同 `demo_library.html` 对学生的处理）

**同一页上因此会同时出现两种口径**（左侧「加载失败」、右侧「仅教师可见」）。这是可接受的代价——统一 C4 的文案属于另一件事，不在本轮范围。

**待文档方确认**：教师工作台页面（示范库管理 / 歌词级标注 / 作业批改）是否应禁止学生访问？若应禁止，页面级鉴权需要新增一个 `teacher_page_required`，并重新审视现有 10 个页面。

### 33.3 全库列表仍无「按曲目筛」

第 32.4 条「待确认」第 4 问已经问过「是否需要按曲目/唱段筛的参数」。本轮落地后这个问题更具体了：

- C7 只有 `tag` 与 `word` 两个参数，按曲目筛**做不到**
- 表格目前在视觉上按「曲目 → 唱段 → 字序」分组（后端排序所致），但**没有折叠、没有按曲目过滤**
- 当前 `annotations` 只有 3 行，不构成问题；标注量上来后，「找出某出戏的所有规则」会是这个界面最常见的诉求

**待文档方确认**：C7 是否补 `demo_id` / `segment_id` 查询参数？补的话前端加两个下拉即可，不补则「按曲目看」只能靠肉眼在长表里找。
```

- [ ] **Step 3: 整体回归 —— 五个场景逐条过**

刷新页面，逐条确认：

1. **教师正常**：全库卡片「共 3 条」，三行数据与 `curl 'http://127.0.0.1:8877/api/annotations/rules'` 一致
2. **筛选**：六个技法按钮逐个点，行数等于 `curl --get --data-urlencode "tag=X"` 的行数；输入框输一个字只剩匹配行
3. **空态区分**：输入一个库里没有的字 → 「🔍 没有匹配的规则」+「筛出 0 条」
4. **学生降级**：登出，用 `stu001` / `xiyun@2026` 登录，打开 `annotation.html` → 全库卡片显示「🔒 全库规则仅教师可见」，**不是**「规则列表加载失败」，计数为空
5. **未登录**：登出后直接访问 `http://127.0.0.1:8877/annotation.html` → 302 跳 `/login.html`

- [ ] **Step 4: 确认只动了一个前端文件**

Run:
```bash
git status --short
git log --oneline -6
```
Expected：`git status` 只有 `DOC_ISSUES.md` 待提交（前四个任务的 `annotation.html` 已各自提交）。`git log` 显示本轮的 5 个提交。

**若 `git status` 里出现任何其它 `.html`**，说明误改了别的页面，回退它。

- [ ] **Step 5: 确认 annotations 表没被改动**

Run:
```bash
docker exec docker_postgres psql -U xiyun -d xiyun -tAc "SELECT count(*) FROM annotations;"
docker exec docker_postgres psql -U xiyun -d xiyun -tAc "SELECT id FROM annotations ORDER BY id;"
```
Expected：与 Task 4 Step 4 记下的基线**完全一致**——`3` 与 `109/110/111`。

**若多出行，按 id 逐条删回去**（`DELETE FROM annotations WHERE id = <抓到的 id>;`），**绝不要用 `DELETE FROM annotations WHERE segment_id = ...` 或整表清空**——表里有真数据。

- [ ] **Step 6: 确认后端未被波及**

Run:
```bash
python scripts/check_db.py
```
Expected：只有**既有**漂移（`demo_versions` 表 + `teacher_demos` 的三列——这是本仓库在干净 `main` 上就存在的，不是本轮改坏的）。若出现别的新差异，说明误改了 `schema.sql` 或模型。

- [ ] **Step 7: 提交**

```bash
git add DOC_ISSUES.md
git commit -m "docs: 登记功能 9.6 前端落地的自拟口径（DOC_ISSUES 第 33 条）"
```

---

## 自审记录

- **Spec 覆盖**：spec 1（目标）→ Task 1–4；3（页内结构）→ Task 1 Step 3；4（数据流）→ Task 2 Step 1 + Task 3 + Task 4；5（筛选控件）→ Task 3；6（表格渲染）→ Task 2 Step 1；7（空态与失败态）→ Task 2 Step 1 的 `fetchRules` 各分支；8（复用与新增）→ Task 1 Step 1–2；9（验证）→ 各任务 Step 的核对项；10（收尾）→ Task 5。
- **超出 spec 的两处**（已在对应步骤里写明理由）：① `esc()` 转义助手（Task 2），spec 8 说「只复用不新造」，但全库表格是本页唯一渲染教师自填标题的地方，不转义会新开一个注入面；② `.ann-tag` 选择器扩展（Task 1），spec 8 原写「可直接复用」，实测发现那 5 条规则全挂在 `.annotation-item` 之下，spec 已同步更正。
- **类型一致性**：`fetchRules()` / `renderRules(rows)` / `fmtRuleTime(v)` / `esc(v)` / `applyRuleWord(v)` / `renderRuleTagFilter()` / `initRuleWordInput()` 在 Task 2、3、4 中的名字与签名一致；状态变量 `ruleTag` / `ruleWord` / `ruleReqToken` / `ruleEmptyMsg` / `ruleEmptyIcon` / `ruleCountable` 全程同名。
