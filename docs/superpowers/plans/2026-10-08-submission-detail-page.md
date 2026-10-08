# 批改详情（F5）前端接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `homework.html` 右侧批改面板从 mock 常量换成 `GET /api/submissions/<id>/detail`，并删掉页面上最后两个 mock 常量。

**Architecture:** 单文件改动（`homework.html`），全部落在首段 `<script>` 内。右侧面板收口到一个状态机（`detailState`: `idle`/`loading`/`error`/`content`）与一个绘制入口 `renderDetail()`；五个内容区块各有一个只写自己那一块的渲染函数；产出 HTML 字符串的纯函数（`emptyBlock` / `cdmItemHtml` / `bktItemHtml`）与 DOM 写入分离，这样 node 能在假 DOM 里直接测页面里的**真函数**（不复制代码、不装依赖）。

**Tech Stack:** 纯静态 HTML + 原生 JS（无构建、无框架、无运行时依赖）；测试用 node v24 + 自写假 DOM（`node:vm`），**不安装任何包**。

**设计依据：** `docs/superpowers/specs/2026-10-08-submission-detail-page-design.md`（下称「spec」）。任务里 `§x.y` 均指该文件的章节。

## Global Constraints

- 页面是纯静态 HTML：**不新增依赖、不引入构建步骤、不新增 CSS 规则、不新增 HTML 元素**。空态样式一律内联，照 `fetchHomeworks`（`homework.html:804`）与 `renderSubmitList`（`:873`）既有的写法。
- `API_BASE` 保持 `""`（同源，经 nginx `/api` 代理）。**不要改成 `location.host + ':8877'`**——那是跨源请求，跨源 fetch 默认不带 Cookie，后端 `login_required` 只会看到空 session 并回 401。
- **不改任何后端文件**：`app/`、`app-d.py` 一行不碰。本次是纯前端接入，接口已上线（commit `a58e9eb`）。
- 所有进 `innerHTML` 的数据库字段一律过 `esc()`（`:716` 已有）。
- 注释用中文、标识符用英文；注释要说明「为什么」而不是复述代码。
- 测试脚本放 `/tmp/f5fe/`，**不进仓库**（本项目无测试框架，约定是临时脚本 + curl + psql）。
- 后端必须跑着：`127.0.0.1:8877`（`.venv/bin/python app-d.py`）。当前已在跑，勿重复启动；未跑则先起。
- 提交粒度 = 任务粒度，**直接提到 `main`**（本项目不开分支、不开 PR）。提交信息用中文，并用 `git commit -F -` 传多行信息。

## 为什么有测试脚本（评审请先看这段）

本仓库没有测试框架，F1–F4 各轮都是「curl + 浏览器实操」。本次加一个 node 假 DOM 夹具，原因是 spec 里几条关键分支**用真数据一次都触发不到**，手工点页面覆盖不了：

| 分支 | 真库现状 | 手工测得到吗 |
|---|---|---|
| `cdm_tags[].confidence` 为 `null` | 13 条标签全都有 confidence | 否 |
| `cdm_tags[].severity` 为未知值 | 只有 `high`/`medium`/`low` | 否 |
| `bkt[].before` / `after` 为 `null` | 两侧皆 NULL 的行被并成 `[]`，不存在「一条里某侧为 null」 | 否 |
| 竞态丢弃（乱序响应） | 要人工制造极慢请求 | 否 |

夹具 60 行、零依赖，读的就是 `homework.html` 里的那一段 `<script>`，不复制任何页面代码。**若评审认为不值得，可以把 Task 1 的夹具步骤删掉、只留浏览器验证**——那样上面四类分支就只能靠代码审查保证。

---

## 文件结构

| 文件 | 责任 |
|---|---|
| `homework.html` | **本次唯一改动的仓库文件**。右侧面板的 `<script>` 逻辑；不动标记、不动 CSS |
| `DOC_ISSUES.md` | 仅 Task 7 更新三处已过时的「右侧仍是 mock」表述 |
| `/tmp/f5fe/harness.mjs` | 假 DOM 夹具：把页面首段 `<script>` 放进 `node:vm` 里跑（不进仓库） |
| `/tmp/f5fe/api.mjs` | node 直连真接口（自己管 Cookie）（不进仓库） |
| `/tmp/f5fe/t1..t5.test.mjs` | 各任务的测试（不进仓库） |

**改动锚点（`homework.html` 当前快照，任务执行中行号会漂，一律按内容定位）：**

| 锚点 | 内容 |
|---|---|
| `:522-597` | 右侧 `.review-panel` 标记（`#emptyState` `:526`、`#reviewContent` `:533`、七个区块） |
| `:561` | 加权融合的权重公式行（Task 4 删） |
| `:566` | CDM 的「只展示置信度 > 0.7」说明（Task 2 改） |
| `:603-680` | 段头注释 + `HOMEWORKS`（`:613-617`）+ `SUBMISSIONS`（`:619-680`）（Task 6 删） |
| `:685` | `const API_BASE = ""` |
| `:696` | `let currentSubId = null;`（Task 1 起接上） |
| `:842-849` | `selectHomework()`（Task 5 加复位） |
| `:864-915` | `renderSubmitList()`（Task 5 加 `active`） |
| `:917-1009` | `selectSubmission(id)`（Task 1 整体重写） |
| `:1048-1058` | 首段脚本末尾的初始化（Task 1 补 `renderDetail()`） |

---

## 真库快照（2026-10-08 写本计划时实测，用于核对测试期望）

各任务的「真数据」用例都拿这些数当期望值。若某条测试失败，先跑一遍下面这段确认是**代码错**还是**库变了**：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
.venv/bin/python - <<'PY'
import json,urllib.request,http.cookiejar
cj=http.cookiejar.CookieJar(); op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.open(urllib.request.Request("http://127.0.0.1:8877/api/auth/login",
  data=json.dumps({"username":"teacher01","password":"xiyun@2026"}).encode(),
  headers={"Content-Type":"application/json"}))
g=lambda p: json.load(op.open("http://127.0.0.1:8877"+p))
for x in g("/api/homeworks")["data"]["homeworks"]:
    s=g(f"/api/homeworks/{x['homework_id']}/submissions")["data"]["submissions"]
    print(x["homework_id"], x["title"][:16], "->", [(i["submission_id"],i["student_name"],len(i["tags"])) for i in s])
for i in (24,26,27,23,25):
    d=g(f"/api/submissions/{i}/detail")["data"]
    print(i, d["student_name"], repr(d["student_avatar"]), "ai",d["ai_score"], "tea",d["teacher_score"],
          "cdm",[(t["label"][:6],t["severity"],t["confidence"]) for t in d["cdm_tags"]],
          "bkt",[(b["skill"],b["before"],b["after"],b["delta"]) for b in d["bkt"]])
PY
```

| 事实 | 值 |
|---|---|
| 作业 | `homework_id` **12 / 13 / 14**（键名是 `homework_id`，不是 `id`）；只有 12 有待批 |
| hw12 待批 | 5 条，顺序 24 刘思琪(卡片 3 标签) / 26 孙志远(2) / 27 赵雨桐(1) / 23 李小燕(2) / 25 周明轩(2) |
| hw13 / hw14 | 各 0 条（Task 5 的「切作业」用它验空列表） |
| 24 刘思琪 | 头像 `🎵` · ai 75.2 · tea 75.2 · 评语「音准偏差较大，建议先进行单音模唱训练。」 · CDM **4** 条 0.85/0.76/0.71/**0.52** · BKT 2 条（气息支撑 .42→.40、音准控制 .48→.46，皆 −0.02） |
| 26 孙志远 | `🥁` · ai 71.3 · tea **null** · 评语 **null** · CDM 3 条 0.88/0.82/**0.65** · BKT 0 |
| 27 赵雨桐 | `🎼` · ai 85.7 · CDM 1 条 · BKT 0 |
| 23 李小燕 | `🎭` · ai 82.5 · tea 82.5 · CDM 3 条，末条 `low` **0.45** · BKT 3 条（拖腔 .28→.28 **delta 0.0**；气息 .51→.53；音准 .72→.74） |
| 25 周明轩 | `🎹` · ai 78.9 · CDM 2 条 · BKT 0 |
| 五份共同 | `lyrics` 皆 `[]` · `dimensions` 皆 `null` |
| 错误信封 | 教师取 999 → **404** `{"code":404,"data":null,"message":"提交不存在"}`；`stu001` 取 24 → **403** `"需要教师权限"` |
| 接口顶层键 | detail 出 22 个键；list 的 `data` 是 `{homeworks:[...]}` / `{homework_id,homework_title,submissions:[...]}`（**都包了一层，不是裸数组**） |

注：`bkt` 的 `delta` 是 **`0.0` 不是 `null`**（23 的拖腔），所以 Task 3 里 flat 档在真数据上确实会被走到——但 `before`/`after` 为 `null` 的**单侧缺失**在真库里没有（两侧皆 NULL 的行被后端并成 `[]`），那部分靠纯函数用例兜。

---

## Task 1: 测试夹具 + 状态机骨架

**Files:**
- Create: `/tmp/f5fe/harness.mjs`（夹具，不进仓库）
- Create: `/tmp/f5fe/api.mjs`（真接口客户端，不进仓库）
- Create: `/tmp/f5fe/t1.test.mjs`（测试，不进仓库）
- Modify: `homework.html`（`:696` 的状态变量区、`:917-1009` 的 `selectSubmission`、`:1048-1058` 的初始化）

**Interfaces:**
- Consumes: 已有的 `esc()`（`:716`）、`fmtTime()`（`:860`）、`renderSubmitList()`（`:864`）、`API_BASE`（`:685`）、`currentUser`（`:688`）、`currentSubId`（`:696`）
- Produces（后面任务要用，名字与签名必须逐字一致）：
  - `const DETAIL_IDLE_HTML: string` —— `#emptyState` 的首帧原文
  - `let detailState: "idle" | "loading" | "error" | "content"`
  - `let detailData: object | null`、`let detailError: string`、`let detailSeq: number`
  - `function renderDetail(): void` —— 右侧面板唯一绘制入口
  - `function fillDetail(d: object): void` —— 头部 + 终审区；区块渲染在 Tasks 2–4 往里加
  - `function selectSubmission(id: number): void`
  - `async function fetchDetail(id: number): Promise<void>`
  - `function retryDetail(): void`

- [ ] **Step 1: 写夹具 `harness.mjs`**

```js
// /tmp/f5fe/harness.mjs
// 把 homework.html 首段 <script> 放进假 DOM 里跑，从而直接测页面里的真函数。
// 不复制任何页面代码——测的就是 homework.html 里那一份。
// 运行前提：node v24+（用到 node:vm / 顶层 await）。
import fs from 'node:fs';
import vm from 'node:vm';

const HTML = process.argv[2] || 'homework.html';

export function loadPage(path = HTML, opts = {}) {
  const html = fs.readFileSync(path, 'utf8');
  const m = html.match(/<script>([\s\S]*?)<\/script>/);
  if (!m) throw new Error('没找到首段 <script>');
  const src = m[1];

  const els = new Map();
  const mkEl = () => ({ innerHTML: '', textContent: '', value: '', style: {} });
  // #emptyState 的首帧内容写在**页面标记**里，而假 DOM 不解析标记。不预置的话
  // DETAIL_IDLE_HTML 抓到的是空串，idle 态就测不出「写回的是首帧原文」。
  // 只预置这一个元素——它是唯一一个「初值来自标记」且被断言的。
  const seedIdle = (() => {
    const after = html.split('<div class="empty-state" id="emptyState">')[1] || '';
    return after.split('<!-- 详情内容 -->')[0].replace(/\s*<\/div>\s*$/, '');
  })();
  els.set('emptyState', { innerHTML: seedIdle, textContent: '', value: '', style: {} });
  const document = {
    getElementById(id) { if (!els.has(id)) els.set(id, mkEl()); return els.get(id); },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    createElement() { return mkEl(); },
    body: { appendChild() {} },
    addEventListener() {},
  };
  const sandbox = { document, console, JSON, Math, String, Object, Array, Number, Date, setTimeout };
  sandbox.window = sandbox;
  sandbox.fetch = opts.fetch || (() => { throw new Error('测试里不该发请求（给 loadPage 传 opts.fetch）'); });
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox, { filename: path });
  return {
    run: (code) => vm.runInContext(code, sandbox),
    el: (id) => document.getElementById(id),
    has: (name) => vm.runInContext(`typeof ${name}`, sandbox),
  };
}

export const results = [];
export function check(name, fn) {
  try { fn(); results.push([true, name, '']); }
  catch (e) { results.push([false, name, e.message]); }
}
export async function acheck(name, fn) {
  try { await fn(); results.push([true, name, '']); }
  catch (e) { results.push([false, name, e.message]); }
}
export function eq(actual, expected, what = '') {
  if (actual !== expected) {
    throw new Error(`${what}\n  期望: ${JSON.stringify(expected)}\n  实际: ${JSON.stringify(actual)}`);
  }
}
export function ok(cond, what = '') { if (!cond) throw new Error(`应为真: ${what}`); }
export function report() {
  const bad = results.filter(r => !r[0]);
  for (const [pass, name, msg] of results) {
    console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}`);
    if (!pass) console.log('      ' + msg.replace(/\n/g, '\n      '));
  }
  console.log(`\n${results.length - bad.length} PASS / ${bad.length} FAIL`);
  process.exit(bad.length ? 1 : 0);
}
```

- [ ] **Step 2: 写真接口客户端 `api.mjs`**

```js
// /tmp/f5fe/api.mjs
// node 直连真接口。node 的 fetch 没有 cookie jar，登录后的 Set-Cookie 要自己带。
const BASE = 'http://127.0.0.1:8877';

export async function login(username = 'teacher01', password = 'xiyun@2026') {
  const r = await fetch(`${BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!r.ok) throw new Error(`登录失败 HTTP ${r.status}`);
  const raw = r.headers.getSetCookie ? r.headers.getSetCookie() : [r.headers.get('set-cookie')];
  const cookie = raw.filter(Boolean).map(c => c.split(';')[0]).join('; ');
  if (!cookie) throw new Error('登录没有拿到 Set-Cookie');
  return {
    cookie,
    async get(path) {
      const res = await fetch(`${BASE}${path}`, { headers: { Cookie: cookie } });
      return { status: res.status, body: await res.json().catch(() => null) };
    },
  };
}
```

- [ ] **Step 3: 写测试 `t1.test.mjs`**

```js
// /tmp/f5fe/t1.test.mjs
import { loadPage, check, acheck, eq, ok, report } from './harness.mjs';

const mkRes = (payload, okFlag = true, status = 200) =>
  ({ ok: okFlag, status, json: async () => payload });

// ============ 一、四态渲染（不需要网络）============
const p = loadPage();

check('idle：显示首帧原文，内容区隐藏', () => {
  p.run('detailState = "idle"; renderDetail()');
  ok(p.el('emptyState').innerHTML.includes('选择左侧提交进行批改'), '应回首帧原文');
  eq(p.el('reviewContent').style.display, 'none', '内容区应隐藏');
});

check('loading：出加载中，且旧内容先被藏起来', () => {
  p.run('detailState = "loading"; renderDetail()');
  ok(p.el('emptyState').innerHTML.includes('加载中'), '应出加载态');
  eq(p.el('reviewContent').style.display, 'none', '旧内容必须先藏起来');
});

check('error：出失败标题 + 后端原因 + 重试按钮', () => {
  p.run('detailState = "error"; detailError = "提交不存在"; renderDetail()');
  const h = p.el('emptyState').innerHTML;
  ok(h.includes('加载失败'), '应出失败标题');
  ok(h.includes('提交不存在'), '应显示原因');
  ok(h.includes('retryDetail()'), '应有重试按钮');
  eq(p.el('reviewContent').style.display, 'none');
});

check('content：隐藏空态、显示内容区、填头部与终审区', () => {
  p.run(`detailData = {
    student_name: "刘思琪", student_avatar: "🎵",
    homework_title: "《穆桂英挂帅》· 辕门外三声炮",
    submitted_at: "2026-08-01T00:00:00",
    ai_score: 75.2, teacher_score: 75.2,
    teacher_comment: "音准偏差较大，建议先进行单音模唱训练。"
  }; detailState = "content"; renderDetail()`);
  eq(p.el('emptyState').style.display, 'none', '空态应隐藏');
  eq(p.el('reviewContent').style.display, 'block', '内容区应显示');
  eq(p.el('detailName').textContent, '刘思琪');
  eq(p.el('detailAvatar').textContent, '🎵');
  ok(p.el('detailMeta').textContent.includes('08-01 00:00'), '时间应切片显示');
  eq(p.el('detailScore').textContent, 75.2);
  eq(p.el('teacherComment').value, '音准偏差较大，建议先进行单音模唱训练。');
  eq(p.el('finalScore').value, 75.2, 'teacher_score 优先');
  eq(p.el('aiSuggestedScore').textContent, 75.2, 'AI 建议分始终取 ai_score');
});

check('content：content 态但数据为 null 时回落 idle（两态必须同进同出）', () => {
  p.run('detailData = null; detailState = "content"; renderDetail()');
  eq(p.el('reviewContent').style.display, 'none', '没有数据就不该显示内容区');
});

check('空值兜底：空串头像 / null 姓名 / null 时间 / 0 分', () => {
  p.run(`detailData = {
    student_name: null, student_avatar: "",
    homework_title: null, submitted_at: null,
    ai_score: 0, teacher_score: null, teacher_comment: null
  }; detailState = "content"; renderDetail()`);
  eq(p.el('detailAvatar').textContent, '🎭', '空串头像要用 || 兜');
  eq(p.el('detailName').textContent, '未知学生');
  ok(p.el('detailMeta').textContent.includes('未知作业'), '标题 null 用 || 兜');
  ok(p.el('detailMeta').textContent.includes('—'), '时间 null 出 —');
  eq(p.el('detailScore').textContent, 0, '合法的 0 分不能被当成没值');
  eq(p.el('finalScore').value, 0, 'teacher_score 为 null 时落到 ai_score 的 0');
  eq(p.el('aiSuggestedScore').textContent, 0);
  eq(p.el('teacherComment').value, '');
});

check('retryDetail：没有选中提交时不动任何状态', () => {
  p.run('currentSubId = null; detailState = "error"');
  const seqBefore = p.run('detailSeq');
  p.run('retryDetail()');
  eq(p.run('detailSeq'), seqBefore, '不该发请求（序号不该涨）');
  eq(p.run('detailState'), 'error');
});

// ============ 二、竞态与角色（要控制 fetch 的返回时机）============

await acheck('竞态：后发的先回来，先发的迟到不许覆盖', async () => {
  const pending = [];
  const q = loadPage('homework.html', {
    fetch: (url) => new Promise((resolve) => pending.push({ url, resolve })),
  });
  q.run('currentUser = { role: "teacher" }');
  const a = q.run('fetchDetail(24)');
  const b = q.run('fetchDetail(26)');
  eq(pending.length, 2, '两次调用应各发一个请求');
  eq(pending[0].url.endsWith('/api/submissions/24/detail'), true, '第一个请求是 24');
  pending[1].resolve(mkRes({ code: 0, data: { student_name: '孙志远', ai_score: 71.3 } }));
  await b;
  eq(q.run('detailData.student_name'), '孙志远');
  eq(q.run('detailState'), 'content');
  pending[0].resolve(mkRes({ code: 0, data: { student_name: '刘思琪', ai_score: 75.2 } }));
  await a;
  eq(q.run('detailData.student_name'), '孙志远', '迟到的 24 不该盖掉 26');
});

await acheck('错误信封：显示后端 message，不是 HTTP 码', async () => {
  const q = loadPage('homework.html', {
    fetch: async () => mkRes({ code: 404, message: '提交不存在' }, false, 404),
  });
  q.run('currentUser = { role: "teacher" }');
  await q.run('fetchDetail(999)');
  eq(q.run('detailState'), 'error');
  eq(q.run('detailError'), '提交不存在');
});

await acheck('学生账号：一个请求都不发，直接出权限文案', async () => {
  let called = 0;
  const q = loadPage('homework.html', { fetch: async () => { called++; return mkRes({}); } });
  q.run('currentUser = { role: "student" }');
  await q.run('fetchDetail(24)');
  eq(called, 0, '学生端不该发请求');
  eq(q.run('detailState'), 'error');
  ok(q.run('detailError').includes('仅教师可见'), '文案应说权限');
});

await acheck('切作业：作废后迟到的响应不改任何状态', async () => {
  const pending = [];
  const q = loadPage('homework.html', {
    fetch: (url) => new Promise((resolve) => pending.push({ url, resolve })),
  });
  q.run('currentUser = { role: "teacher" }; detailState = "content"; detailData = { student_name: "旧的" }');
  const a = q.run('fetchDetail(24)');
  q.run('detailSeq++');                       // selectHomework 里就是这么作废的
  pending[0].resolve(mkRes({ code: 0, data: { student_name: '刘思琪' } }));
  await a;
  eq(q.run('detailData.student_name'), '旧的', '被作废的响应不该动 detailData');
});

await acheck('重试：错误态点重试会重新发请求', async () => {
  const pending = [];
  const q = loadPage('homework.html', {
    fetch: (url) => new Promise((resolve) => pending.push({ url, resolve })),
  });
  q.run('currentUser = { role: "teacher" }; currentSubId = 27; detailState = "error"; detailError = "网络异常"');
  q.run('retryDetail()');
  eq(pending.length, 1, '应重新发一个请求');
  ok(pending[0].url.endsWith('/api/submissions/27/detail'), '重试的是原来那条');
  pending[0].resolve(mkRes({ code: 0, data: { student_name: '赵雨桐' } }));
  await new Promise(r => setImmediate(r));
  eq(q.run('detailState'), 'content');
  eq(q.run('detailData.student_name'), '赵雨桐');
});

report();
```

- [ ] **Step 4: 跑测试，确认失败**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
node /tmp/f5fe/t1.test.mjs
```

Expected: 全部 `FAIL`（`renderDetail is not defined` 之类），末尾类似 `0 PASS / 12 FAIL`。**若出现 PASS，说明夹具没读到页面脚本，先查夹具。**
夹具自检（应当通过）：`node -e "import('/tmp/f5fe/harness.mjs').then(m=>{const p=m.loadPage();console.log(p.run('fmtTime(\"2026-08-01T00:00:00\")'))})"` → 打印 `08-01 00:00`。

- [ ] **Step 5: 改状态变量区（`homework.html:696`）**

把这一行：

```js
let currentSubId = null;
```

替换为：

```js
// ===== 批改详情（F5）=====
// 首帧原文（idle 态），必须在任何代码改写 #emptyState 之前抓。回 idle 时原样
// 写回，这样「选择左侧提交进行批改」那段文案只有一个来源（HTML），不在 JS 里
// 再抄一份（spec 3.3）。
const DETAIL_IDLE_HTML = document.getElementById("emptyState").innerHTML;

// 选中的提交 id。F4 就引入了它，但 renderSubmitList 从没读过（卡片高亮一直没接），
// F5 让点击真的换出右侧内容，这一步才接上（spec 3.8）。
let currentSubId = null;
// 右侧面板的状态机。四个状态各自完整渲染两块，见 renderDetail()（spec 3.2）。
let detailState = "idle";        // idle | loading | error | content
let detailData = null;           // content 态的数据；与 detailState==="content" 同进同出
let detailError = "";            // error 态的原因文案（后端 message 或网络异常）
// 自增序号，用来作废在飞的请求（spec 3.4）。**不用 currentSubId 比 id**：教师双击
// 同一张卡片会发两个同 id 的请求，比 id 两个都通过，后回来的会覆盖先回来的。
// selectHomework 里一句 detailSeq++ 也就顺带作废了切作业时在飞的请求。
let detailSeq = 0;
```

- [ ] **Step 6: 重写 `selectSubmission` 并新增四个函数**

`selectSubmission` 现在这条「`SUBMISSIONS.find` → 找不到 return → 从 mock 填面板」的整段（`homework.html:917-1009`）要删掉。用 Read 确认边界：`:917` 是 `function selectSubmission(id) {`，`:1009` 是它的收尾 `}`（紧接着是空行与 `// ============` / `// 交互操作` 段头）。整段替换为：

```js
// 点左侧待批卡片。角色判断不在这里（学生看不到卡片），在 fetchDetail 里——
// 与 F4「明知会 403 就不发请求」同一处口径。
function selectSubmission(id) {
  currentSubId = id;
  renderSubmitList();            // 高亮跟过来（spec 3.8）

  detailState = "loading";
  detailError = "";
  detailData = null;             // 与 loading 同进同出（spec 4.1）
  renderDetail();                // 先把上一名的内容藏起来，再显示加载态

  fetchDetail(id);
}

// F5 批改详情：GET /api/submissions/<id>/detail（统一信封）。
// 竞态用自增序号，理由见 detailSeq 的声明处（spec 3.4）。
async function fetchDetail(id) {
  const seq = ++detailSeq;

  // 接口挂 @teacher_required，学生调必 403，明知会被拒就不发（与 F4 同源）。
  // 这条分支当前走不到（学生看不到待批卡片、没有入口），是照 F4 的原则加的防御：
  // 万一列表将来对学生开放，右侧第一句该说的是权限，而不是让它去撞 403。
  if (!currentUser || currentUser.role !== "teacher") {
    detailState = "error";
    detailError = "批改详情仅教师可见";
    renderDetail();
    return;
  }

  // 取数与渲染分开：catch 只包住取数，renderDetail 放在 try 外面，
  // 免得渲染里的异常被当成「加载失败」盖掉真正的原因。
  let data = null;
  let error = "";
  try {
    const res = await fetch(`${API_BASE}/api/submissions/${id}/detail`,
      { credentials: "same-origin" });
    if (seq !== detailSeq) return;
    if (!res.ok) {
      // 错误信封里后端自己写了 message（404「提交不存在」/ 403「需要教师权限」），
      // 原样显示比自己拼一句 HTTP xxx 有用。
      const b = await res.json().catch(() => null);
      throw new Error((b && b.message) || `HTTP ${res.status}`);
    }
    const body = await res.json();
    if (seq !== detailSeq) return;          // res.json() 也是异步的，再判一次
    data = body.data || null;
    if (!data) error = "响应里没有 data";
  } catch (e) {
    error = e.message || "网络异常";
  }

  if (seq !== detailSeq) return;            // 迟到的失败不该盖掉后一次的成功
  detailData = data;
  detailError = error;
  detailState = data ? "content" : "error";
  renderDetail();
}

// 错误态的「重试」。currentSubId 为 null 说明没有可重试的目标（错误态必然有它，
// 这一句防的是从控制台直接调）。
function retryDetail() {
  if (currentSubId == null) return;
  selectSubmission(currentSubId);
}

// 右侧面板的**唯一绘制入口**。四个状态各自完整渲染两块（spec 3.2）——
// 从 content 切到 loading 时必须先把 #reviewContent 藏起来，否则点第二名学生的
// 瞬间右侧还挂着上一名的分数与评语，教师会读成「正在刷新这名学生的数据」。
function renderDetail() {
  const empty = document.getElementById("emptyState");
  const content = document.getElementById("reviewContent");

  // content 态但数据为空时**不当 content 渲染**，回落 idle：两者必须同进同出，
  // 否则会显示一个所有格子都是「—」的空壳，看起来像「这名学生什么数据都没有」。
  if (detailState === "content" && detailData) {
    empty.style.display = "none";
    content.style.display = "block";
    fillDetail(detailData);
    return;
  }

  empty.style.display = "";
  content.style.display = "none";

  if (detailState === "loading") {
    empty.innerHTML = `
      <div class="icon">⏳</div>
      <div class="title">加载中…</div>
      <div class="desc">正在读取批改详情</div>`;
  } else if (detailState === "error") {
    // 重试按钮复用终审区同款的 .btn-secondary（:590），不新增 CSS（spec 3.2）。
    empty.innerHTML = `
      <div class="icon">⚠️</div>
      <div class="title">加载失败</div>
      <div class="desc">${esc(detailError)}</div>
      <div style="margin-top:12px"><button class="btn-secondary" onclick="retryDetail()">重试</button></div>`;
  } else {
    empty.innerHTML = DETAIL_IDLE_HTML;     // idle：回首帧原文
  }
}

// 头部 + 终审区。五个内容区块由各自的 renderDetail* 负责（Tasks 2–4 往里加调用）。
function fillDetail(d) {
  // 头像可能是**空串**不是 null（students.avatar），必须用 || 兜，?? 兜不到空串。
  document.getElementById("detailAvatar").textContent = d.student_avatar || "🎭";
  document.getElementById("detailName").textContent = d.student_name || "未知学生";
  document.getElementById("detailMeta").textContent =
    `${d.homework_title || "未知作业"} · 提交于 ${fmtTime(d.submitted_at)}`;
  // ai_score 可能是合法的 0，所以用 == null 判而不是 ||（spec 3.7）。
  document.getElementById("detailScore").textContent = (d.ai_score == null) ? "—" : d.ai_score;

  // 终审区只回显，**不按 status/reviewed_at 推断「还能不能改」**（spec 3.7）：
  // 真库 23/24 已有 teacher_score 与评语，status 却还是 ai_scored——页面若自己
  // 按 status 认定「还没批过」并盖掉已存在的评语，就等于替 F6 定了终审状态机。
  document.getElementById("teacherComment").value = d.teacher_comment || "";
  document.getElementById("finalScore").value = (d.teacher_score ?? d.ai_score ?? "");
  document.getElementById("aiSuggestedScore").textContent = (d.ai_score == null) ? "—" : d.ai_score;
}
```

- [ ] **Step 7: 补初始化调用（`homework.html:1048-1058`）**

把这一段：

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

替换为：

```js
// 两个面板各画一次自己的初始态：左下进「加载中…」，右侧进 idle（F5 之后右侧
// 不再有任何 mock，空状态就是它的真实初始态）。
// 作业列表**不在这里渲染**：fetchHomeworks 要读 currentUser，而它要等第二段
// <script> 的 /api/auth/me 回来才有值，同步调会被误判成学生。调用点在那里。
// 真数据由 fetchHomeworks → selectHomework → fetchSubmissions 那条链接上。
renderSubmitList();
renderDetail();
```

- [ ] **Step 8: 跑测试，确认全部通过**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
node /tmp/f5fe/t1.test.mjs
```

Expected: 12 行 `PASS`，末尾 `12 PASS / 0 FAIL`（退出码 0）。

- [ ] **Step 9: 浏览器确认骨架能跑**

用 `/browse` 技能（项目约定：网页浏览一律用它，不用 chrome MCP）打开 `http://127.0.0.1:8877/login.html`，用 `teacher01` / `xiyun@2026` 登录，进入 `http://127.0.0.1:8877/homework.html`。

Expected：页面不报错；左侧 5 条待批；右侧显示「📝 选择左侧提交进行批改」；点任一条 → 右侧先出「⏳ 加载中…」，随后变成**内容区空壳**（头像 🎭、姓名 `—`、AI初评分 `—`、各区块空着）——Tasks 2–4 才会把内容填上，这一步只验证状态机能跑通。

- [ ] **Step 10: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add homework.html
git commit -F - <<'EOF'
feat: F5 右侧批改面板骨架（状态机 + 详情取数）

- 四态状态机 idle/loading/error/content，一个绘制入口 renderDetail()
- selectSubmission 整段重写：不再读 mock，改为取真接口
- 自增序号 detailSeq 作竞态守卫（比 id 更好的理由见注释）
- 终审区只回显，不按 status 推断能否修改
- 五个内容区块与空态渲染留待后续任务
EOF
```

---

## Task 2: CDM 归因诊断区块（4.6）

**Files:**
- Modify: `homework.html`（新增 `emptyBlock` / `cdmItemHtml` / `renderDetailCdm`，`fillDetail` 里加一行，改 `:566` 的说明文案）
- Create: `/tmp/f5fe/t2.test.mjs`

**Interfaces:**
- Consumes: `renderDetail` / `fillDetail` / `detailData` / `detailState`（Task 1）；`esc()`（`:716`）
- Produces:
  - `function emptyBlock(text: string): string` —— 区块级空态的一段 HTML（Tasks 3/4 复用）
  - `function cdmItemHtml(t: object): string` —— 一条 CDM 标签的 HTML
  - `function renderDetailCdm(d: object): void`

- [ ] **Step 1: 写测试 `t2.test.mjs`**

```js
// /tmp/f5fe/t2.test.mjs
import { loadPage, check, eq, ok, report } from './harness.mjs';
import { login } from './api.mjs';

const p = loadPage();

// ============ 一、纯函数（真数据触发不到的分支在这里兜）============
check('severity 三档各自映射到 item 与 conf 两个类', () => {
  const html = (t) => p.run(`cdmItemHtml(${JSON.stringify(t)})`);
  ok(html({ label: 'A', severity: 'high', confidence: 0.82 }).includes('class="cdm-item high"'),
    'high 应有 item 修饰类');
  ok(html({ label: 'A', severity: 'high', confidence: 0.82 }).includes('class="conf high"'),
    'high 应有 conf 修饰类');
  ok(html({ label: 'A', severity: 'medium', confidence: 0.72 }).includes('class="cdm-item medium"'));
  // .cdm-item 没有 .low 档（:350-351 只有 high/medium），描边必须回落基类
  ok(html({ label: 'A', severity: 'low', confidence: 0.45 }).includes('class="cdm-item"'),
    'low 在 item 上不该有修饰类');
  ok(html({ label: 'A', severity: 'low', confidence: 0.45 }).includes('class="conf low"'),
    'low 在 conf 上有现成的 .conf.low');
});

check('未知 severity 与 Object 原型上的键都要走中性档', () => {
  const html = (t) => p.run(`cdmItemHtml(${JSON.stringify(t)})`);
  for (const sev of ['unknown', 'constructor', 'toString', 'HIGH', '']) {
    const h = html({ label: 'A', severity: sev, confidence: 0.5 });
    ok(h.includes('class="cdm-item"'), `severity=${JSON.stringify(sev)} 应回落基类，实际: ${h.slice(0, 90)}`);
    ok(h.includes('class="conf"'), `severity=${JSON.stringify(sev)} 的胶囊也该回落基类`);
    ok(!h.includes('undefined'), `不该拼出 undefined: ${h.slice(0, 90)}`);
  }
});

check('confidence 为 null 显示 —，不抛异常', () => {
  const h = p.run('cdmItemHtml({ label: "A", severity: "high", confidence: null })');
  ok(h.includes('—'), '应为 —');
  ok(!h.includes('NaN'), '不该出现 NaN');
  ok(!h.includes('%'), 'null 不该带百分号');
});

check('confidence 四舍五入到整数百分数', () => {
  const pct = (c) => p.run(`cdmItemHtml({ label:"A", severity:"high", confidence:${c} })`)
    .match(/class="conf[^"]*">([^<]*)</)[1];
  eq(pct(0.45), '45%');
  eq(pct(0.52), '52%');
  eq(pct(0.8), '80%');
  eq(pct(1), '100%');
});

check('label / evidence 都转义，且 evidence 为 null 不出现 null', () => {
  const h = p.run(`cdmItemHtml({ label: "<b>&x</b>", severity: "high", confidence: 0.9, evidence: null })`);
  ok(h.includes('&lt;b&gt;&amp;x&lt;/b&gt;'), 'label 应转义');
  ok(!h.includes('<b>'), '不该有裸标签');
  ok(!h.includes('null'), 'evidence 为 null 时不该渲染出 null');
});

check('空数组出「暂无归因标签」', () => {
  p.run('renderDetailCdm({ cdm_tags: [] })');
  ok(p.el('cdmList').innerHTML.includes('暂无归因标签'), '应出空态');
});

check('cdm_tags 缺失时不抛异常，出空态', () => {
  p.run('renderDetailCdm({})');
  ok(p.el('cdmList').innerHTML.includes('暂无归因标签'));
});

// ============ 二、真数据（走真接口）============
const teacher = await login();
const details = {};
for (const id of [24, 26, 27, 23, 25]) {
  details[id] = (await teacher.get(`/api/submissions/${id}/detail`)).body.data;
}

check('真数据：五份的 CDM 条数是 4/3/1/3/2（不套 0.7 阈值）', () => {
  const counts = [24, 26, 27, 23, 25].map(id => details[id].cdm_tags.length);
  eq(counts.join('/'), '4/3/1/3/2', '比 F4 卡片多出 0.52 / 0.65 / 0.45 三条');
});

check('真数据：≤ 0.7 的三条必须出现（F5 与 F4 的口径差）', () => {
  const low = [24, 26, 23].flatMap(id => details[id].cdm_tags)
    .filter(t => t.confidence !== null && t.confidence <= 0.7)
    .map(t => `${t.confidence}:${t.label}`);
  ok(low.some(s => s.startsWith('0.52')), '24 的 0.52 应在');
  ok(low.some(s => s.startsWith('0.65')), '26 的 0.65 应在');
  ok(low.some(s => s.startsWith('0.45')), '23 的 0.45 应在');
  eq(low.length, 3, '正好三条');
});

check('真数据：23 的 low 档渲染成「中性描边 + 蓝胶囊」', () => {
  p.run(`renderDetailCdm(${JSON.stringify(details[23])})`);
  const h = p.el('cdmList').innerHTML;
  ok(h.includes('class="cdm-item"'), 'low 那条的 item 应无修饰类');
  ok(h.includes('class="conf low"'), 'low 那条的胶囊应带 .low');
  ok(h.includes('>45%<'), '应显示 45%');
  eq((h.match(/class="cdm-item/g) || []).length, 3, '23 应有 3 条');
});

check('真数据：24 的 evidence 文本进得去、且按接口给的顺序（置信度降序）', () => {
  p.run(`renderDetailCdm(${JSON.stringify(details[24])})`);
  const h = p.el('cdmList').innerHTML;
  const confs = [...h.matchAll(/class="conf[^"]*">([^<]*)</g)].map(m => m[1]);
  eq(confs.join(','), '85%,76%,71%,52%', '顺序照接口，页面不再排');
});

report();
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
node /tmp/f5fe/t2.test.mjs
```

Expected: 纯函数那几条 `FAIL`（`cdmItemHtml is not defined`）；真数据那条也可能 `FAIL`。末尾 FAIL 数 > 0。
（后端必须跑着，否则 `login()` 会抛。若报 `登录失败` / `fetch failed`，先起 `.venv/bin/python app-d.py`。）

- [ ] **Step 3: 加 `emptyBlock` 与 CDM 三个函数**

在 `homework.html` 的 `renderSubmitList` 之后、`function selectSubmission` 之前插入：

```js
// 区块级空态。样式内联、**不新增 CSS**——与 fetchHomeworks（:804）和
// renderSubmitList（:873）的空态同一套写法。
function emptyBlock(text) {
  return `<div style="padding:12px;text-align:center;color:var(--text-muted);font-size:11px">${esc(text)}</div>`;
}

// severity → 两个 CSS 类。**两套映射不是笔误**：.cdm-item 只定义了 high/medium
// 两档描边（:350-351），而 .conf 三档都有（:356-358）。所以 low 与未知档在 item 上
// 不加修饰类（回落基类的中性描边）、在胶囊上 low 用现成的 .conf.low。
// **不给 .cdm-item 补 .low/.unknown 规则**——低档真正需要区分的是胶囊颜色（spec 3.5）。
const CDM_ITEM_CLS = { high: " high", medium: " medium" };
const CDM_CONF_CLS = { high: " high", medium: " medium", low: " low" };
// spec 3.5 的「其它（含后端的 unknown）」要兜住**任意**字符串：severity 是后端透传的，
// 直接拿它查表会被 Object 原型上的成员命中（"constructor" 能查到一个函数），
// 拼出 class="cdm-itemundefined"。所以先用三个已知档白名单收口。
const CDM_SEV_KNOWN = ["high", "medium", "low"];

// 一条 CDM 标签的 HTML。**纯函数**（只吃数据、只吐字符串，不碰 DOM），
// 这样能在 node 里直接测——confidence 与 severity 为空的那些分支真库里一次都
// 不出现，手工点页面覆盖不到。
function cdmItemHtml(t) {
  const sev = CDM_SEV_KNOWN.includes(t.severity) ? t.severity : "unknown";
  // confidence 可能是 null（F5 刻意不丢这类元素，接口 spec §36.6）：**不能 .toFixed**
  // ——null.toFixed 会抛 TypeError 打断整个 map，一条坏数据让整块渲染不出来。
  const conf = (t.confidence == null) ? "—" : `${Math.round(t.confidence * 100)}%`;
  return `
    <div class="cdm-item${CDM_ITEM_CLS[sev] ?? ""}">
      <div class="label">${esc(t.label)}</div>
      <span class="conf${CDM_CONF_CLS[sev] ?? ""}">${conf}</span>
      <span class="evidence">${esc(t.evidence || "")}</span>
      <div class="actions">
        <button class="confirm" onclick="confirmCDM(this)">✓</button>
        <button onclick="rejectCDM(this)">✗</button>
      </div>
    </div>`;
}

// 功能 4.6。接口出**全量**、不套 F4 卡片那条 0.7 阈值（spec 3.1、DOC_ISSUES §36.6），
// 顺序也照接口给的（后端已按置信度降序排好，页面不再排一次）。
function renderDetailCdm(d) {
  const tags = d.cdm_tags || [];
  document.getElementById("cdmList").innerHTML =
    tags.length ? tags.map(cdmItemHtml).join("") : emptyBlock("暂无归因标签");
}
```

- [ ] **Step 4: `fillDetail` 里接上 CDM**

把 `fillDetail` 末尾这一行：

```js
  document.getElementById("aiSuggestedScore").textContent = (d.ai_score == null) ? "—" : d.ai_score;
}
```

替换为：

```js
  document.getElementById("aiSuggestedScore").textContent = (d.ai_score == null) ? "—" : d.ai_score;

  // 各内容区块只写自己那一块（spec 4.2）：一块里的坏数据或异常不会让其它块渲染不出来。
  renderDetailCdm(d);
}
```

- [ ] **Step 5: 改 `:566` 的说明文案**

把这一行（`homework.html:566`）：

```html
            <div style="font-size:10px;color:var(--text-muted);margin-top:4px">只展示置信度 &gt; 0.7 的标签 · 老师可修正，数据回流优化模型</div>
```

替换为：

```html
            <div style="font-size:10px;color:var(--text-muted);margin-top:4px">按置信度降序展示全部标签（不筛阈值） · 老师可修正，数据回流优化模型</div>
```

理由：后半句仍然成立；前半句在 F5 上是**反的**——批改页刻意不筛阈值（spec 3.10），真库有 3 条 ≤ 0.7 的标签会出现在这里。

- [ ] **Step 6: 跑测试，确认全部通过**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
node /tmp/f5fe/t2.test.mjs
```

Expected: 12 行 `PASS`，末尾 `12 PASS / 0 FAIL`。

- [ ] **Step 7: 浏览器确认**

`/browse` 打开 `http://127.0.0.1:8877/homework.html`（已登录则直接进）。点左侧第 1 条（刘思琪）→ 右侧 CDM 区应出 **4** 条，末尾一条胶囊是 `52%`；再点第 5 条（周明轩）→ 2 条；点赵雨桐 → 1 条。

Expected：卡片上的标签数比右侧少（24 卡片 3 个 vs 右侧 4 条）——差的正是 ≤ 0.7 的那条。

- [ ] **Step 8: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add homework.html
git commit -F - <<'EOF'
feat: F5 CDM 归因诊断区块真渲染

- cdmItemHtml 纯函数：severity 两套映射（.cdm-item 只有 high/medium 描边，
  .conf 三档都有）、三个已知档白名单收口、confidence 为 null 出 —
- renderDetailCdm 出全量不套 0.7 阈值（与 F4 卡片的刻意差异）
- emptyBlock 助手，样式内联不新增 CSS
- 改正卡片下那句「只展示置信度 > 0.7」——F5 是反的
EOF
```

---

## Task 3: BKT 状态更新区块（4.7）

**Files:**
- Modify: `homework.html`（新增 `bktItemHtml` / `renderDetailBkt`，`fillDetail` 里加一行）
- Create: `/tmp/f5fe/t3.test.mjs`

**Interfaces:**
- Consumes: `emptyBlock`（Task 2）、`esc()`、`fillDetail`（Task 1）
- Produces:
  - `function bktItemHtml(b: object): string`
  - `function renderDetailBkt(d: object): void`

- [ ] **Step 1: 写测试 `t3.test.mjs`**

```js
// /tmp/f5fe/t3.test.mjs
import { loadPage, check, eq, ok, report } from './harness.mjs';
import { login } from './api.mjs';

const p = loadPage();

// ============ 一、纯函数（真数据触发不到的分支）============
check('delta 为 null → flat 档、无箭头（显式判，不靠 null>0 为假）', () => {
  const h = p.run('bktItemHtml({ skill: "气息", before: 0.5, after: 0.5, delta: null })');
  ok(h.includes('class="after flat"'), '应走 flat');
  ok(!h.includes('↗') && !h.includes('↘'), 'flat 不该有箭头');
  ok(h.includes('50%'), '百分比仍应正常');
});

check('delta 三档方向：正 ↗ up、负 ↘ down、零 → flat', () => {
  const h = (d) => p.run(`bktItemHtml({ skill: "x", before: 0.4, after: 0.4, delta: ${d} })`);
  ok(h(0.02).includes('↗') && h(0.02).includes('after up'));
  ok(h(-0.02).includes('↘') && h(-0.02).includes('after down'));
  ok(h(0).includes('→') && h(0).includes('after flat'));
});

check('before / after 为 null → 数值位出 —、宽度 0、不抛异常', () => {
  const h = p.run('bktItemHtml({ skill: "x", before: null, after: null, delta: null })');
  ok(!h.includes('NaN'), '不该出现 NaN');
  ok(!h.includes('undefined'), '不该出现 undefined');
  ok(h.includes('width:0%'), '两侧宽度都该是 0');
  eq((h.match(/—/g) || []).length, 2, '两个数值位都是 —');
  ok(h.includes('var(--text-muted)'), 'after 取不到时用中性色兜');
});

check('after 有值 → 按阈值分档取色；before 为 null 不影响 after', () => {
  const color = (a) => p.run(`bktItemHtml({ skill:"x", before: null, after: ${a}, delta: 0.01 })`)
    .match(/background:([^"]+)"/)[1];
  eq(color(0.9), '#4A8F6B');
  eq(color(0.7), '#0066B3');
  eq(color(0.5), '#C9A84C');
  eq(color(0.3), '#B83A2F');
});

check('skill 名转义；空数组出「本次无 BKT 状态变化」', () => {
  ok(p.run('bktItemHtml({ skill: "<i>x</i>", before: 1, after: 1, delta: 0 })')
    .includes('&lt;i&gt;x&lt;/i&gt;'), 'skill 应转义');
  p.run('renderDetailBkt({ bkt: [] })');
  ok(p.el('bktList').innerHTML.includes('本次无 BKT 状态变化'), '应出「本次没有」而不是加载失败');
  p.run('renderDetailBkt({})');
  ok(p.el('bktList').innerHTML.includes('本次无 BKT 状态变化'), 'bkt 缺失同样兜住');
});

// ============ 二、真数据 ============
const teacher = await login();
const details = {};
for (const id of [24, 26, 27, 23, 25]) {
  details[id] = (await teacher.get(`/api/submissions/${id}/detail`)).body.data;
}

check('真数据：五份的 BKT 条数是 2/0/0/3/0', () => {
  eq([24, 26, 27, 23, 25].map(id => details[id].bkt.length).join('/'), '2/0/0/3/0');
});

check('真数据：23 的「拖腔」0.28→0.28 走 flat 且不显示 0% 之外的东西', () => {
  p.run(`renderDetailBkt(${JSON.stringify(details[23])})`);
  const h = p.el('bktList').innerHTML;
  eq((h.match(/class="bkt-item"/g) || []).length, 3, '23 应有 3 条');
  ok(h.includes('拖腔'), '应含拖腔');
  ok(h.includes('class="after flat"'), 'delta 为 0 的那条应 flat');
  ok(h.includes('28%'), '应显示 28%');
  ok(!h.includes('NaN') && !h.includes('undefined'), '不该出现 NaN/undefined');
});

check('真数据：24 两条都是负向，且顺序照接口', () => {
  p.run(`renderDetailBkt(${JSON.stringify(details[24])})`);
  const h = p.el('bktList').innerHTML;
  eq((h.match(/after down/g) || []).length, 2, '两条都应 down');
  const skills = [...h.matchAll(/class="skill">([^<]*)</g)].map(m => m[1]);
  eq(skills.join(','), details[24].bkt.map(b => b.skill).join(','), '顺序照接口，页面不再排');
});

check('真数据：25/26/27 三份都出「本次无 BKT 状态变化」', () => {
  for (const id of [25, 26, 27]) {
    p.run(`renderDetailBkt(${JSON.stringify(details[id])})`);
    ok(p.el('bktList').innerHTML.includes('本次无 BKT 状态变化'), `${id} 应出空态`);
  }
});

report();
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
node /tmp/f5fe/t3.test.mjs
```

Expected: 全部 `FAIL`（`bktItemHtml is not defined`），末尾 FAIL 数 > 0。

- [ ] **Step 3: 加 BKT 两个函数**

在 Task 2 的 `renderDetailCdm` 之后插入：

```js
// 一条 BKT 前后对比的 HTML。**纯函数**，理由同 cdmItemHtml。
// before / after / delta 都可能为 null——接口对两侧 key 取并集，一侧没有就是 null
// （接口 spec §3.6）；(null).toFixed(0) 会抛，所以每一步都先判数值再算。
function bktItemHtml(b) {
  const num = (v) => (typeof v === "number" && isFinite(v)) ? v : null;
  const before = num(b.before);
  const after = num(b.after);
  const delta = num(b.delta);

  // delta 为 null 时走 flat。**显式判**，不靠「null > 0 为假」落到 flat——那只是
  // 巧合（null < 0 同样为假），三目一改就成未定义行为（spec 3.6）。
  const dir = delta === null ? "flat" : (delta > 0 ? "up" : (delta < 0 ? "down" : "flat"));
  const arrow = delta === null ? "" : (delta > 0 ? "↗" : (delta < 0 ? "↘" : "→"));
  const pct = (v) => v === null ? "—" : `${Math.round(v * 100)}%`;
  // 宽度直接乘：值是概率，超界的值由 .bar-wrap 的 overflow:hidden（:375）裁掉。
  const width = (v) => v === null ? 0 : v * 100;
  // after 取不到时那串阈值算不出意义，用中性色兜（spec 3.6）。
  const color = after === null ? "var(--text-muted)"
    : (after >= 0.85 ? "#4A8F6B" : (after >= 0.60 ? "#0066B3" : (after >= 0.40 ? "#C9A84C" : "#B83A2F")));

  return `
    <div class="bkt-item">
      <span class="skill">${esc(b.skill)}</span>
      <div class="bar-wrap">
        <div class="before" style="width:${width(before)}%"></div>
        <div class="after" style="width:${width(after)}%;background:${color}"></div>
      </div>
      <div class="vals">
        <span class="before">${pct(before)}</span>
        <span class="arrow">→</span>
        <span class="after ${dir}">${pct(after)} ${arrow}</span>
      </div>
    </div>`;
}

// 功能 4.7。空数组是**真库常态**（5 份里 3 份），文案要说清「本次没有」，
// 不能与「加载失败」共用一句话（spec 3.6）。
function renderDetailBkt(d) {
  const rows = d.bkt || [];
  document.getElementById("bktList").innerHTML =
    rows.length ? rows.map(bktItemHtml).join("") : emptyBlock("本次无 BKT 状态变化");
}
```

- [ ] **Step 4: `fillDetail` 里接上 BKT**

把：

```js
  renderDetailCdm(d);
}
```

替换为：

```js
  renderDetailCdm(d);
  renderDetailBkt(d);
}
```

- [ ] **Step 5: 跑测试，确认全部通过**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
node /tmp/f5fe/t3.test.mjs
```

Expected: 11 行 `PASS`，末尾 `11 PASS / 0 FAIL`。

- [ ] **Step 6: 浏览器确认**

`/browse` 打开 `http://127.0.0.1:8877/homework.html`。点刘思琪（24）→ BKT 区 2 条、都是 ↘、条形在缩；点李小燕（23）→ 3 条，其中「拖腔」是灰色 → 且无箭头；点孙志远/赵雨桐/周明轩 → 都出「本次无 BKT 状态变化」。

- [ ] **Step 7: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add homework.html
git commit -F - <<'EOF'
feat: F5 BKT 状态更新区块真渲染

- bktItemHtml 纯函数：before/after/delta 为 null 各自兜底，delta 显式判而非
  靠 null>0 为假落到 flat
- 空数组出「本次无 BKT 状态变化」（真库 5 份里 3 份是这种）
- 顺序照接口，页面不重排
EOF
```

---

## Task 4: 三个空位区块（4.4 / 4.5 / 4.10）+ 删掉权重公式行

**Files:**
- Modify: `homework.html`（新增 `renderDetailLyrics` / `renderDetailFusion` / `renderDetailCalib`，`fillDetail` 补齐五个调用，删 `:561`）
- Create: `/tmp/f5fe/t4.test.mjs`

**Interfaces:**
- Consumes: `emptyBlock`（Task 2）、`fillDetail`（Task 1）
- Produces: `renderDetailLyrics(d)` / `renderDetailFusion(d)` / `renderDetailCalib(d)`，均返回 `void`

- [ ] **Step 1: 写测试 `t4.test.mjs`**

```js
// /tmp/f5fe/t4.test.mjs
import fs from 'node:fs';
import { loadPage, check, acheck, eq, ok, report } from './harness.mjs';
import { login } from './api.mjs';

const p = loadPage();

check('歌词块：出「暂无逐字偏差数据（数据源待接入）」', () => {
  p.run('renderDetailLyrics({ lyrics: [] })');
  const h = p.el('lyricsCompare').innerHTML;
  ok(h.includes('暂无逐字偏差数据'), '应出空态');
  ok(h.includes('数据源待接入'), '要说清是没数据源，不是「本次没有」');
});

check('融合块：格子出空态，两格置 —', () => {
  p.run('renderDetailFusion({ dimensions: null })');
  ok(p.el('fusionGrid').innerHTML.includes('暂无维度分与加权结果'), '应出空态');
  eq(p.el('fusionTotal').textContent, '—');
  eq(p.el('fusionPass').textContent, '—');
});

check('校准块：出「暂无校准项（数据源待接入）」', () => {
  p.run('renderDetailCalib({})');
  const h = p.el('calibGrid').innerHTML;
  ok(h.includes('暂无校准项'), '应出空态');
  ok(h.includes('数据源待接入'), '校准是 F7 的事');
});

check('三个空态都用了内联样式，不带新类名', () => {
  p.run('renderDetailLyrics({}); renderDetailFusion({}); renderDetailCalib({})');
  for (const id of ['lyricsCompare', 'fusionGrid', 'calibGrid']) {
    ok(p.el(id).innerHTML.includes('style="padding:'), `${id} 的空态应带内联样式`);
  }
});

check('fillDetail 五个区块都接上了（真数据不抛异常）', () => {
  p.run(`detailData = {
    student_name: "刘思琪", student_avatar: "🎵", homework_title: "T",
    submitted_at: "2026-08-01T00:00:00", ai_score: 75.2, teacher_score: 75.2,
    teacher_comment: null, lyrics: [], dimensions: null,
    cdm_tags: [{ label: "气息支撑不足", severity: "medium", confidence: 0.52 }],
    bkt: []
  }; detailState = "content"; renderDetail()`);
  ok(p.el('cdmList').innerHTML.includes('气息支撑不足'), 'CDM 应渲染');
  ok(p.el('bktList').innerHTML.includes('本次无 BKT 状态变化'), 'BKT 应渲染');
  ok(p.el('lyricsCompare').innerHTML.includes('暂无逐字偏差数据'), '歌词应出空态');
  ok(p.el('fusionGrid').innerHTML.includes('暂无维度分'), '融合应出空态');
  ok(p.el('calibGrid').innerHTML.includes('暂无校准项'), '校准应出空态');
});

// ============ 文件级：两句静态文案 ============
const html = fs.readFileSync('homework.html', 'utf8');

check('权重公式行已删（它描述的 dimensions/fusion 接口都不出）', () => {
  ok(!html.includes('当前权重: 音准40%'), '公式行应已删除');
  ok(!html.includes('dimᵢ_score'), '公式本体应已删除');
});

check('CDM 说明已是「不筛阈值」', () => {
  ok(html.includes('按置信度降序展示全部标签（不筛阈值）'), '文案应已改');
  ok(!html.includes('只展示置信度 &gt; 0.7'), '旧文案应已不存');
});

// ============ 真数据：三块在 5 份上都是空态 ============
const teacher = await login();
await acheck('真数据：5 份的 lyrics 都是 []、dimensions 都是 null', async () => {
  for (const id of [24, 26, 27, 23, 25]) {
    const d = (await teacher.get(`/api/submissions/${id}/detail`)).body.data;
    eq(d.lyrics.length, 0, `${id} 的 lyrics`);
    eq(d.dimensions, null, `${id} 的 dimensions`);
  }
});

report();
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
node /tmp/f5fe/t4.test.mjs
```

Expected: 前六条 `FAIL`（函数未定义 / 文案未改），末尾 FAIL 数 > 0。

- [ ] **Step 3: 加三个空位区块的渲染函数**

在 Task 3 的 `renderDetailBkt` 之后插入：

```js
// 功能 4.4 逐字偏差：本接口当前**恒出 []**（后端显式空位，接口 spec §2.5）。
// **非空分支故意不写**——从当前接口拿到非空数组是不可能的（service 里写死 []），
// 为看不见的形状写渲染代码只会写错。F3 把 B 组结果落进 ai_detail 之后，在这里补
// 真渲染，并把下面这句降级成 if (!d.lyrics.length) 的分支（spec 6.4）。
function renderDetailLyrics(d) {
  document.getElementById("lyricsCompare").innerHTML =
    emptyBlock("暂无逐字偏差数据（数据源待接入）");
}

// 功能 4.5：dimensions 恒为 null（接口显式空位，spec 3.1）。
// feature_matrix 与 overall_confidence 有值但**不上屏**：9 个驼峰键没有中文标签，
// 而最接近的槽位 #fusionTotal 写的是「加权总分」，overall_confidence 是置信度不是
// 分数，放进去就是错标（spec 3.11）。总分由 ai_score 承担，它在头部与终审区已有。
function renderDetailFusion(d) {
  document.getElementById("fusionGrid").innerHTML =
    emptyBlock("暂无维度分与加权结果（数据源待接入）");
  document.getElementById("fusionTotal").textContent = "—";
  document.getElementById("fusionPass").textContent = "—";
}

// 功能 4.10（F7 的地盘）：F5 **不出校准**——那是 F7 的读职责（接口 spec §3.11）。
// 区块保留（4.10 是正式需求），出空态；要显示得先等 F7 定下校准项的取值集合
// （DOC_ISSUES 第 37 条：校准项文档从未定义，且 score_calibrations 装不下页面的
// 「按维度勾三项」）。
function renderDetailCalib(d) {
  document.getElementById("calibGrid").innerHTML =
    emptyBlock("暂无校准项（数据源待接入）");
}
```

- [ ] **Step 4: `fillDetail` 补齐五个调用**

把：

```js
  renderDetailCdm(d);
  renderDetailBkt(d);
}
```

替换为：

```js
  renderDetailCdm(d);
  renderDetailBkt(d);
  renderDetailLyrics(d);
  renderDetailFusion(d);
  renderDetailCalib(d);
}
```

（`fillDetail` 至此定型：头部 + 终审区 + 五个区块，与 spec §4.2 的表一一对应。）

- [ ] **Step 5: 删掉权重公式行（`homework.html:561`）**

删除这一整行：

```html
            <div class="fusion-formula">公式: Σ(wᵢ × dimᵢ_score) ≥ 0.6 ? "通过" : "未通过" · 当前权重: 音准40% 节奏30% 气息20% 咬字10%</div>
```

理由：它描述的 `dimensions` 与 `fusion` 接口都不出（接口 spec §36.2），照渲会在一排「—」底下摆一个具体公式；40/30/20/10 与 0.6 这两个数文档从未定义、接口也刻意不带，留在页面上等于页面自己发明了一套算法（spec 3.10）。

（`.fusion-formula` 这条 CSS 规则本身**留着不动**——删 CSS 不在本次范围，且它没有别的使用者也不影响渲染。）

- [ ] **Step 6: 跑测试，确认全部通过**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
node /tmp/f5fe/t4.test.mjs
```

Expected: 8 行 `PASS`，末尾 `8 PASS / 0 FAIL`。

- [ ] **Step 7: 浏览器确认**

`/browse` 打开 `http://127.0.0.1:8877/homework.html`，逐份点开 24/26/27/23/25。

Expected：五份的「🎵 歌词级偏差对比」都是「暂无逐字偏差数据（数据源待接入）」；「⚖️ 多维加权融合」格子是「暂无维度分与加权结果（数据源待接入）」、下面两格都是 `—`；**权重公式那一行整行不在了**；「🎯 AI 评分校准」是「暂无校准项（数据源待接入）」。

- [ ] **Step 8: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add homework.html
git commit -F - <<'EOF'
feat: F5 三个无数据源区块出显式空态（4.4/4.5/4.10）

- 歌词/融合/校准三块保留区块、渲染「（数据源待接入）」，
  与 BKT/CDM 的「本次没有」区分开
- 删掉加权融合的权重公式行：dimensions 与 fusion 接口都不出，
  40/30/20/10 与 0.6 文档从未定义
- fillDetail 至此定型：头部 + 终审区 + 五个区块
EOF
```

---

## Task 5: 卡片高亮接线 + 切作业复位右侧（两个 F4 遗留件）

**Files:**
- Modify: `homework.html`（`:842-849` 的 `selectHomework`、`:890-902` 的 `renderSubmitList` 映射体）
- Create: `/tmp/f5fe/t5.test.mjs`

**Interfaces:**
- Consumes: `currentSubId` / `detailSeq` / `detailState` / `detailData` / `renderDetail()`（Task 1）
- Produces: 无新函数（两处修改）

- [ ] **Step 1: 写测试 `t5.test.mjs`**

```js
// /tmp/f5fe/t5.test.mjs
import { loadPage, check, eq, ok, report } from './harness.mjs';
import { login } from './api.mjs';

const teacher = await login();
const hwList = (await teacher.get('/api/homeworks')).body.data.homeworks;
const list = (await teacher.get('/api/homeworks/12/submissions')).body.data.submissions;

// 所有请求都成功但返回空列表：selectHomework 会顺手 fetchSubmissions，喂它空数组
// 就不会有真数据干扰右侧断言。
const p = loadPage('homework.html', {
  fetch: async () => ({ ok: true, status: 200, json: async () => ({ code: 0, data: { submissions: [] } }) }),
});
// hwItems 必须先喂真作业列表：renderHwList 的第一句就是 items.length，
// 传 null 会当场 TypeError，selectHomework 后面那几步根本走不到。
p.run('currentUser = { role: "teacher" }');
p.run(`hwItems = ${JSON.stringify(hwList)};`);
p.run(`submitItems = ${JSON.stringify(list)}; submitNotice = ""; renderSubmitList()`);

check('列表渲染出 5 条，且初始没有任一条带 active', () => {
  const h = p.el('submitList').innerHTML;
  eq((h.match(/class="submit-item/g) || []).length, 5);
  eq((h.match(/class="submit-item active"/g) || []).length, 0, '没选中时不该有高亮');
});

check('选中一条后只有那一条带 active', () => {
  p.run('currentSubId = 26; renderSubmitList()');
  const h = p.el('submitList').innerHTML;
  eq((h.match(/class="submit-item active"/g) || []).length, 1, '只能有一条高亮');
  // 高亮必须落在 26 那一张上：取 active 卡片里 onclick 的 id
  const m = h.match(/class="submit-item active" onclick="selectSubmission\((\d+)\)/);
  ok(m, '高亮的应该是本轮被点开的那条');
  eq(m[1], '26');
});

check('切到另一条，高亮跟过去且不残留', () => {
  p.run('currentSubId = 23; renderSubmitList()');
  const h = p.el('submitList').innerHTML;
  eq((h.match(/class="submit-item active"/g) || []).length, 1);
  eq(h.match(/class="submit-item active" onclick="selectSubmission\((\d+)\)/)[1], '23');
});

check('未选中（null）时不高亮任何一条', () => {
  p.run('currentSubId = null; renderSubmitList()');
  eq((p.el('submitList').innerHTML.match(/active/g) || []).length, 0);
});

// ============ 切作业复位右侧 ============
check('selectHomework：右侧回 idle、清选中、作废在飞请求', () => {
  p.run(`currentSubId = 24; detailState = "content"; detailData = { student_name: "刘思琪" };
         detailSeq = 7; detailError = "旧错误"`);
  p.run('selectHomework(13)');
  eq(p.run('currentHwId'), 13, '作业应切换');
  eq(p.run('currentSubId'), null, '应清掉左下的选中');
  eq(p.run('detailState'), 'idle', '右侧应回 idle，不是 loading');
  eq(p.run('detailData'), null);
  eq(p.run('detailError'), '');
  ok(p.run('detailSeq') > 7, '应作废在飞的详情请求');
  eq(p.el('reviewContent').style.display, 'none', '内容区应藏起来');
  ok(p.el('emptyState').innerHTML.includes('选择左侧提交进行批改'), '应回首帧原文');
});

check('切作业后右侧不残留上一份的学生姓名', () => {
  const h = p.el('reviewContent').innerHTML + p.el('emptyState').innerHTML;
  ok(!h.includes('刘思琪'), '不该还挂着上一份作业的学生');
});

check('切回原作业也不会自动重开上一份详情', () => {
  p.run('selectHomework(12)');
  eq(p.run('detailState'), 'idle');
  eq(p.run('currentSubId'), null);
});

report();
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
node /tmp/f5fe/t5.test.mjs
```

Expected：`未选中时不该有高亮` 等几条 `FAIL`——因为 `renderSubmitList` 现在压根不产生 `active`；`selectHomework` 那几条 `FAIL`——右侧状态不会被复位。末尾 FAIL 数 ≥ 4。

- [ ] **Step 3: `renderSubmitList` 接上高亮（`:890-902`）**

把映射体开头这一段：

```js
  container.innerHTML = submitItems.map(it => {
    // tags 不截断：接口按置信度降序给全量（刘思琪 3 条）。.tags 本就是
    // flex-wrap，让它换行，不要 slice——截掉哪条纯看运气（spec 3.6）。
    const tagsHtml = (it.tags || []).map(t =>
      `<span class="tag ${SEV_CLS[t.severity] || "neutral"}">${esc(t.label)}</span>`
    ).join("");
```

替换为：

```js
  container.innerHTML = submitItems.map(it => {
    // tags 不截断：接口按置信度降序给全量（刘思琪 3 条）。.tags 本就是
    // flex-wrap，让它换行，不要 slice——截掉哪条纯看运气（spec 3.6）。
    const tagsHtml = (it.tags || []).map(t =>
      `<span class="tag ${SEV_CLS[t.severity] || "neutral"}">${esc(t.label)}</span>`
    ).join("");
    // 选中态。F4 就引入了 currentSubId 却从没读过、`.submit-item.active`（:255）
    // 的样式一直没被用过；F5 让点击真的换出右侧内容，这里才接上（spec 3.8）。
    // 不接的话点开一条右侧换了内容、左侧却看不出点的是哪一名。
    const active = it.submission_id === currentSubId ? " active" : "";
```

再把：

```js
      <div class="submit-item" onclick="selectSubmission(${it.submission_id})">
```

替换为：

```js
      <div class="submit-item${active}" onclick="selectSubmission(${it.submission_id})">
```

- [ ] **Step 4: `selectHomework` 补右侧复位（`:842-849`）**

把整个函数：

```js
function selectHomework(hwId) {
  currentHwId = hwId;
  renderHwList(hwItems);           // 刷 hw-item 的选中态
  submitItems = null;              // 先进加载态，否则会短暂显示上一份作业的提交
  submitNotice = "";
  renderSubmitList();
  fetchSubmissions(hwId);
}
```

替换为：

```js
function selectHomework(hwId) {
  currentHwId = hwId;
  renderHwList(hwItems);           // 刷 hw-item 的选中态
  submitItems = null;              // 先进加载态，否则会短暂显示上一份作业的提交
  submitNotice = "";
  renderSubmitList();

  // 右侧也必须复位。F4 时这不可能出问题（右侧永远是空状态），F5 落地后就是实缺陷：
  // 开过 hw12 的刘思琪再点 hw13，右侧还挂着刘思琪的分数与评语，而左下已经换成
  // hw13 的空列表——教师会以为 hw13 里有一份刘思琪的提交（spec 3.9）。
  currentSubId = null;             // 取消左下的高亮
  detailSeq++;                     // 作废在飞的详情请求
  detailData = null;
  detailError = "";
  detailState = "idle";            // 回空状态，**不是** loading——没有新提交要加载
  renderDetail();

  fetchSubmissions(hwId);
}
```

- [ ] **Step 5: 跑测试，确认全部通过**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
node /tmp/f5fe/t5.test.mjs
```

Expected: 7 行 `PASS`，末尾 `7 PASS / 0 FAIL`。

- [ ] **Step 6: 浏览器确认**

`/browse` 打开 `http://127.0.0.1:8877/homework.html`：点开刘思琪 → 左卡片有蓝色描边；点李小燕 → 描边跟过去且只剩一个；点左侧 hw13 → 右侧回「📝 选择左侧提交进行批改」、左下「暂无待批改提交」、左侧无任一卡片高亮；点回 hw12 → 左下 5 条回来、**右侧仍是空状态**（不会自动重开刘思琪）。

- [ ] **Step 7: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add homework.html
git commit -F - <<'EOF'
fix: F5 接上卡片高亮，并修 F4 切作业不复位右侧的缺陷

- renderSubmitList 产出 active：currentSubId 是 F4 留下的死状态，
  .submit-item.active 的样式一直没被用过
- selectHomework 复位右侧（清选中、作废在飞请求、回 idle）：
  F4 时右侧恒为空状态所以看不出，F5 落地后会残留上一份作业的学生详情
EOF
```

---

## Task 6: 删掉两个 mock 常量

**Files:**
- Modify: `homework.html`（`:603-680`：段头注释改写 + `HOMEWORKS` / `SUBMISSIONS` 删除）
- Create: `/tmp/f5fe/t6.test.mjs`

**Interfaces:**
- Consumes: 无（Task 1 已让两个常量失去全部使用点）
- Produces: 无

- [ ] **Step 1: 写测试 `t6.test.mjs`**

```js
// /tmp/f5fe/t6.test.mjs
import fs from 'node:fs';
import { loadPage, check, eq, ok, report } from './harness.mjs';

const html = fs.readFileSync('homework.html', 'utf8');
const p = loadPage();          // 能加载 = <script> 没有语法错误

check('两个 mock 常量已从文件里消失', () => {
  ok(!html.includes('const SUBMISSIONS'), 'SUBMISSIONS 应已删除');
  ok(!html.includes('const HOMEWORKS'), 'HOMEWORKS 应已删除');
  ok(!html.includes('sub01'), 'mock 的 id 不该残留');
  ok(!html.includes('h01'), 'mock 的作业 id 不该残留');
});

check('运行时确实取不到它们（删的不是同名别处）', () => {
  eq(p.has('SUBMISSIONS'), 'undefined');
  eq(p.has('HOMEWORKS'), 'undefined');
});

check('六个桩函数都还在（它们是 F6/F2 的落点，不是 mock 数据）', () => {
  for (const fn of ['confirmCDM', 'rejectCDM', 'submitReview', 'saveDraft',
                    'playVoiceComment', 'showAssignModal']) {
    eq(p.has(fn), 'function', `${fn} 不该被一起删掉`);
  }
});

check('页面仍能正常初始化（三个渲染入口都在）', () => {
  for (const fn of ['renderSubmitList', 'renderDetail', 'renderHwList']) {
    eq(p.has(fn), 'function', `${fn} 应在`);
  }
});

check('段头注释不再说这一页有 mock', () => {
  ok(!html.includes('模拟数据'), '「模拟数据」段头应已改写');
  ok(html.includes('没有 mock'), '应说明本页无 mock');
});

report();
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
node /tmp/f5fe/t6.test.mjs
```

Expected：`两个 mock 常量已从文件里消失`、`运行时确实取不到它们`、`段头注释` 三条 `FAIL`；桩函数与初始化两条应已 `PASS`。末尾 FAIL 数 = 3。

- [ ] **Step 3: 删常量、改写段头注释（`:603-680`）**

把从 `<script>` 之后到 `SUBMISSIONS` 结束的整段（`homework.html:604-680`，即「模拟数据」段头 + `HOMEWORKS` + `SUBMISSIONS`）：

```js
// ============================================
// 模拟数据
// ============================================
// 作业列表已接真接口 GET /api/homeworks，待批改提交已接
// GET /api/homeworks/<id>/submissions（见下方 fetchHomeworks / renderHwList /
// fetchSubmissions / renderSubmitList）。
// 这两个常量保留是因为**批改详情页**（右侧面板）仍是 mock——逐字偏差、加权融合、
// CDM、BKT、校准、评语都是 F5 的内容，尚未实现，selectSubmission 仍靠它们填右侧。
// 等 F5 落地时，这两个常量连同 selectSubmission 的函数体一并删除。
const HOMEWORKS = [ ... ];

const SUBMISSIONS = [ ... ];
```

替换为：

```js
// ============================================
// 本页数据全部来自真接口，没有 mock
// ============================================
//   GET /api/homeworks                         作业列表（F1）→ fetchHomeworks
//   GET /api/homeworks/<id>/submissions        待批改提交（F4）→ fetchSubmissions
//   GET /api/submissions/<id>/detail           批改详情（F5）→ fetchDetail
// 逐字偏差（4.4）与四维分（4.5）在库里没有数据源、校准（4.10）属 F7，右侧那三块
// 因此出显式空态，见 renderDetailLyrics / renderDetailFusion / renderDetailCalib。
// 原来这里的 HOMEWORKS / SUBMISSIONS 两个 mock 常量已随 F5 落地删除。
```

（用 Read 取 `:604-680` 的原文确认边界：`const HOMEWORKS = [` 起、`SUBMISSIONS` 的收尾 `];` 止。）

- [ ] **Step 4: 跑测试，确认全部通过**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
node /tmp/f5fe/t6.test.mjs
```

Expected: 5 行 `PASS`，末尾 `5 PASS / 0 FAIL`。

- [ ] **Step 5: 跑前四轮的测试，确认没有回归**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
for n in 1 2 3 4 5; do echo "--- t$n ---"; node /tmp/f5fe/t$n.test.mjs | tail -2; done
```

Expected：五个都是 `N PASS / 0 FAIL`（N 依次 12 / 12 / 11 / 8 / 7）。

- [ ] **Step 6: 浏览器确认**

`/browse` 打开 `http://127.0.0.1:8877/homework.html`，开控制台执行 `typeof SUBMISSIONS` 与 `typeof HOMEWORKS`。

Expected：两个都是 `"undefined"`；页面功能与 Task 5 结束时完全一致（这一轮只删数据，不改行为）。

- [ ] **Step 7: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add homework.html
git commit -F - <<'EOF'
chore: F5 删掉页面最后两个 mock 常量

HOMEWORKS 与 SUBMISSIONS 各只有 1 个使用点，都在 selectSubmission 里，
Task 1 重写该函数后已无引用。段头注释改写为本页真实的三个接口。
EOF
```

---

## Task 7: 端到端验收 + 同步 DOC_ISSUES

**Files:**
- Modify: `DOC_ISSUES.md`（三处已过时的「右侧仍是 mock」）
- 无代码改动

**Interfaces:**
- Consumes: Tasks 1–6 的全部成果
- Produces: 无

- [ ] **Step 1: 跑全套测试**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
for n in 1 2 3 4 5 6; do echo "--- t$n ---"; node /tmp/f5fe/t$n.test.mjs | tail -2; done
```

Expected：六个都 `0 FAIL`（12 / 12 / 11 / 8 / 7 / 5）。

- [ ] **Step 2: 接口侧回归（确认前端这一轮没碰后端）**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git status --short          # 应只有 homework.html 与 DOC_ISSUES.md 被改
git diff --stat HEAD -- app app-d.py    # 应为空，本次一行后端都没碰
```

再用 `/tmp/f5fe/api.mjs` 复核接口侧四个数：

```bash
cd /tmp/f5fe && cat > regress.mjs <<'EOF'
import { login } from './api.mjs';
const t = await login();
console.log('hw12 待批:', (await t.get('/api/homeworks/12/submissions')).body.data.submissions.length, '（应 5）');
console.log('detail 24 CDM:', (await t.get('/api/submissions/24/detail')).body.data.cdm_tags.length, '（应 4）');
console.log('detail 999:', (await t.get('/api/submissions/999/detail')).status, '（应 404）');
const stu = await login('stu001');
console.log('学生取 detail:', (await stu.get('/api/submissions/24/detail')).status, '（应 403）');
EOF
node regress.mjs
```

Expected: `5 / 4 / 404 / 403`。

- [ ] **Step 3: 浏览器逐份核对（spec §5 的第 2–8 条）**

用 `/browse` 打开 `http://127.0.0.1:8877/login.html`，登录后进 `homework.html`，逐条确认：

1. **24 刘思琪**：CDM **4** 条（含 `52%` 那条）、BKT 2 条（都 ↘）、终审框预填 `75.2` + 评语「音准偏差较大，建议先进行单音模唱训练。」；头像 🎵；提交时间显示 `08-01 00:00`。
2. **26 孙志远**：CDM 3 条、BKT「本次无 BKT 状态变化」、评语框空（显示 placeholder）、评分预填 `71.3`。
3. **27 赵雨桐**：CDM 1 条、BKT 空态、评分 `85.7`。
4. **23 李小燕**：CDM 3 条，第三条「归韵口型保持不足」的**卡片描边是中性、胶囊是蓝的**（`conf low`，45%）；BKT 3 条，其中「拖腔」是 `28% →`（delta 恰为 0，`flat` 档：灰色值 + 一个 `→`）；评分预填 `82.5` + 评语。
5. **25 周明轩**：CDM 2 条、BKT 空态、评分 `78.9`。
6. **五份共同**：歌词 / 融合 / 校准三块都是「（数据源待接入）」空态；权重公式行不在。
7. **左卡片 vs 右面板的口径差**：24 卡片 3 个标签 / 右侧 4 条，26 卡片 2 / 右侧 3，23 卡片 2 / 右侧 3。
8. **高亮**：点开一条后左卡片蓝描边，点另一条跟过去，始终只有一个。
9. **切作业**：点开 24 → 点 hw13 → 右侧回空状态（不是刘思琪）→ 点回 hw12 → 左侧 5 条回来、右侧仍空。
10. **竞态**：快速连点两张不同卡片（24 → 26）→ 右侧最终是孙志远，不能停在刘思琪；连点同一张两次 → 不闪回。
11. **错误态**：停掉 Flask（Ctrl-C 那个终端）后点卡片 → 右侧「⚠️ 加载失败」+「重试」；重新起 `.venv/bin/python app-d.py` 后点「重试」→ 正常加载。
12. **学生端**：登出后 `stu001` 登录 → 左侧「待批改提交仅教师可见」、右侧停在「选择左侧提交进行批改」、Network 面板里**没有** `/detail` 请求。

- [ ] **Step 4: 确认库没被动过**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
.venv/bin/python scripts/check_db.py
```

Expected：与基线一致（本项目在干净 main 上本就有既有漂移：`demo_versions` 表 + `teacher_demos` 三列）——**与本次改动前逐字相同**，本次不动库、不动模型。

- [ ] **Step 5: 同步 DOC_ISSUES 的三处过时表述**

三处都按本文档已有的体例**追加一行更新**，不改写原判断（保留决策史）。

5a. §34.5（`DOC_ISSUES.md:1069` 结尾）：

```markdown
**2026-10-08 更新**：批改详情（F5）前端**已接入**，见 `docs/superpowers/specs/2026-10-08-submission-detail-page-design.md`。`homework.html` 的左侧列表与右侧批改面板现在都是真数据，`HOMEWORKS` / `SUBMISSIONS` 两个 mock 常量已删除——**第 34.5 条「同一页真数据与 mock 并存」至此消失**。右侧三块（逐字偏差 4.4 / 加权融合 4.5 / 校准 4.10）因库里没有数据源而渲染显式空态，不是遗漏。
```

5b. §35.4（`:1116` 那段「2026-10-08 更新」之后）：

```markdown
**2026-10-08 再更新**：批改详情面板（F5）也已接入，`homework.html` 右侧不再是 mock。上面这条 35.4 的标题与表格里「右侧仍是 mock」「`HOMEWORKS` / `SUBMISSIONS` 保留未删」的描述**均已过时**，保留原文作为当时的决策记录：F4 落地时右侧面板还没有数据源，保留常量比删掉再抄回来省事。
```

5c. §36 开头（`:1150`）那句：

```markdown
F5 于 2026-10-08 实现（设计 `docs/superpowers/specs/2026-10-08-submission-detail-api-design.md`、计划 `docs/superpowers/plans/2026-10-08-submission-detail-api.md`、代码 `app/api/homeworks.py` / `app/services/homework_service.py` / `app/repositories/homeworks_repo.py` / `app/schemas/homework.py`）。**前端未接入**——`homework.html` 右侧批改面板仍是 mock。
```

改为：

```markdown
F5 于 2026-10-08 实现（设计 `docs/superpowers/specs/2026-10-08-submission-detail-api-design.md`、计划 `docs/superpowers/plans/2026-10-08-submission-detail-api.md`、代码 `app/api/homeworks.py` / `app/services/homework_service.py` / `app/repositories/homeworks_repo.py` / `app/schemas/homework.py`）。**前端已于同日接入**（设计 `docs/superpowers/specs/2026-10-08-submission-detail-page-design.md`）——`homework.html` 右侧批改面板已走真接口，下面 36.1 / 36.2 / 36.4 三处的「无数据源 / 数据不全」在页面上表现为显式空态。
```

- [ ] **Step 6: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add DOC_ISSUES.md
git commit -F - <<'EOF'
docs: 同步 DOC_ISSUES 里「右侧仍是 mock」的三处过时表述

§34.5 / §35.4 / §36 开头都还写着右侧批改面板是 mock。按本文档体例
追加更新行、保留原判断作为当时的决策记录。
EOF
```

---

## 自查记录

**1. spec 覆盖：**

| spec 章节 | 落在哪个任务 |
|---|---|
| §3.1 七个区块保留、三块空态 | Task 4（三块空态）+ Task 2/3（两块真渲染） |
| §3.2 四态状态机 | Task 1 Step 6 |
| §3.3 首帧快照还原 idle | Task 1 Step 5 |
| §3.4 自增序号竞态守卫 | Task 1 Step 6 |
| §3.5 CDM severity 两套映射 / confidence null / 不过滤 | Task 2 Step 3 |
| §3.6 BKT null 兜底 / flat 显式判 / 空数组文案 | Task 3 Step 3 |
| §3.7 终审区只回显 / `??` vs `\|\|` | Task 1 Step 6 |
| §3.8 卡片高亮接线 | Task 5 Step 3 |
| §3.9 切作业复位右侧 | Task 5 Step 4 |
| §3.10 两句静态文案 | Task 2 Step 5（`:566`）+ Task 4 Step 5（`:561`） |
| §3.11 不显示的字段 | 全任务（一律不渲染这些字段，Task 4 Step 3 的注释说明理由） |
| §3.12 删两个 mock 常量 | Task 6 Step 3 |
| §4.2 函数清单 | Task 1（7 个）+ Task 2（3 个）+ Task 3（2 个）+ Task 4（3 个） |
| §5 验证清单 | Task 7 Step 3 |
| §6 待确认项 | 无代码（Task 4 Step 3 的注释交叉引用 DOC_ISSUES §37） |

**2. 占位符扫描：** 无 TBD / TODO / 「类似 Task N」/「加上适当的错误处理」；每个改代码的步骤都给了完整代码与确切锚点。

**3. 类型与命名一致性：** `DETAIL_IDLE_HTML` / `detailState` / `detailData` / `detailError` / `detailSeq` / `renderDetail` / `fillDetail` / `selectSubmission` / `fetchDetail` / `retryDetail` / `emptyBlock` / `cdmItemHtml` / `renderDetailCdm` / `bktItemHtml` / `renderDetailBkt` / `renderDetailLyrics` / `renderDetailFusion` / `renderDetailCalib` —— 在 Task 1 的 Produces 里声明，后续任务逐字复用，未出现改名。`fillDetail` 的最终形态只在 Task 4 出现一次完整版。

**4. 与 spec 的已知偏离（评审可驳回）：**

- **加了测试夹具。** spec 没提测试；这是本计划的决定，理由见开头「为什么有测试脚本」一节。
- **`CDM_SEV_KNOWN` 白名单。** spec §3.5 只说「其它档回落中性」，没写「要防 Object 原型键」。真库里 severity 只有三档，这一行是为 spec 那句「兜住其它」字面成立而加的；若评审认为多余，删掉它、把 `const sev = CDM_SEV_KNOWN.includes(...) ? ... : "unknown"` 换成 `const sev = t.severity` 即可（测试里那两条 `constructor`/`toString` 的用例要一并删）。
- **`fillDetail` 分四次长成。** 每个任务往里加自己的调用行，好处是每个任务都能独立跑；代价是中间态（Task 1–3 结束时）右侧有几块是空的。
