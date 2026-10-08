# F6 教师终审批改前端接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `homework.html` 右侧终审区的「✅ 通过并发布」接到已落地的 `POST /api/submissions/<id>/review`，让教师能在页面里真的完成一次终审。

**Architecture:** 只改一个纯静态页面。置一个按钮的 `onclick` 从假 alert 换成真 `fetch`；成功后刷新左侧两条列表（F4 待批、F1 作业），右侧复位回空态。另两个按钮（保存草稿、语音）保持原来的 alert 桩不动。验证靠 `node:vm` 夹具跑页面里**真正的那个 `<script>` 块**（不复制页面代码）+ 真接口 curl + `psql` 核库。

**Tech Stack:** 纯静态 HTML/JS（无构建、无依赖、无 package.json）；Node 原生 `node:vm` 做夹具；Flask 后端 + PostgreSQL（`docker_postgres`）。

## Global Constraints

- 交流、注释、提交信息、文档**一律简体中文**；代码标识符保持英文。
- **只改 `homework.html` 一个源文件**，加上最后一条任务的 `DOC_ISSUES.md`。**后端一行不动**（F6 后端已交付并验过）。
- `API_BASE` 必须保持 `""`（同源、经 nginx 代理）。**绝不改成 `location.host + ':8877'`**——跨源 fetch 默认不带 Cookie，后端 `login_required` 只会看到空 session 并回 401。
- 不引入任何前端依赖、不加构建步骤、不加 `package.json`、不改 `requirements.txt`。
- **不装 pytest**，项目没有测试框架；夹具是 `node` 直接跑的 `.mjs`，零依赖。
- 页面无 `localStorage`、无持久化；不改这个现状。
- 所有提交**直接落在 `main`**，不开分支、不发 PR。提交信息用中文。
- **临时库改动只能按抓到的 id 逐列改回**：绝不 `DELETE FROM submissions WHERE <别的列>`、绝不 `DELETE FROM submissions;`、绝不整表清空。
- 验证脚本一律放 `/tmp/f6fe/`，不进仓库。
- 真库基线（2026-10-08 实测，动手前与收尾时各核一次）：

  | id | hw | stu | teacher_score | teacher_comment | voice_comment_text | voice_comment_audio_id | status | reviewed_at |
  |---|---|---|---|---|---|---|---|---|
  | 24 | 12 | 50 | 75.2 | 音准偏差较大，建议先进行单音模唱训练。 | NULL | NULL | ai_scored | NULL |
  | 25 | 12 | 53 | NULL | NULL | NULL | NULL | ai_scored | NULL |

  hw12 下共 5 条待批提交（id 23/24/25/26/27）。

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `homework.html` | 修改 4 处 | 唯一的产品代码改动：按钮 id、`fetchHomeworks` 加参数、两个纯函数、`submitReview` 换真实现 |
| `DOC_ISSUES.md` | 追加第 39 条 | 登记本轮自拟口径与四条待确认（草稿无承载物、4.11 读侧无出口、`closed` 双语义、无通知途径） |
| `/tmp/f6fe/harness.mjs` | 新建（从 `/tmp/f5fe/harness.mjs` 演进） | 把首段 `<script>` 放进假 DOM 跑；本轮新增 `location.replace` 与 `alert` 两样捕获 |
| `/tmp/f6fe/t1.test.mjs` `/tmp/f6fe/t2.test.mjs` `/tmp/f6fe/t3.test.mjs` | 新建 | 三段夹具用例（纯函数 / `keepSelection` / `submitReview` 全分支） |
| `/tmp/f6fe/api.mjs` | 新建（从 `/tmp/f5fe/api.mjs` 演进） | node 直连真接口，自己管 Cookie；`post` 加 body 参数 |
| `/tmp/f6fe/e2e.mjs` | 新建 | 把页面发出的那个 body 原样喂给真接口 |

**为什么夹具演进而不是重写**：`/tmp/f5fe/` 那套（现仍在）已经在 F5 那一轮验过页面里 6 个真实函数，假 DOM 的坑（`#emptyState` 初值来自标记、`let` 声明只能靠 `run()` 读）都趟平了。本轮只缺两样：页面代码会读 `location.replace`、会调 `alert`。

---

## Task 1: 夹具 + 两个空值纯函数

**Files:**
- Create: `/tmp/f6fe/harness.mjs`
- Create: `/tmp/f6fe/t1.test.mjs`
- Modify: `homework.html`（在 `:1125-1127` 的「交互操作」横幅之后、`confirmCDM` 之前插入两个函数）

**Interfaces:**
- Consumes: 无
- Produces:
  - `textOrNull(v: string|null) -> string|null`
  - `scoreOrNull(v: string|null) -> number|null`
  - `/tmp/f6fe/harness.mjs` 导出 `loadPage(path?, opts?) -> {run, el, has, nav, alerts}`，以及 `check/acheck/eq/ok/report`。`nav` 收集 `location.replace` 的实参，`alerts` 收集 `alert` 的实参——Task 3 要用。

- [ ] **Step 1: 建目录并从 F5 夹具复制一份**

```bash
mkdir -p /tmp/f6fe
cp /tmp/f5fe/api.mjs /tmp/f6fe/api.mjs
ls -l /tmp/f6fe/
```

Expected: 打印出 `api.mjs` 一行（`harness.mjs` 下一步手写，不从 F5 直接复制——它要加两样东西）。

- [ ] **Step 2: 写夹具 `/tmp/f6fe/harness.mjs`**

```js
// 把 homework.html 首段 <script> 放进一个假 DOM 里跑，从而直接测页面里的真函数。
// 不复制粘贴任何页面代码——测的就是 homework.html 里那一份。
import fs from 'node:fs';
import vm from 'node:vm';

const HTML = process.argv[2] || 'homework.html';

export function loadPage(path = HTML, opts = {}) {
  const html = fs.readFileSync(path, 'utf8');
  // 页面有两段 <script>，非贪婪匹配拿到的就是第一段（`<style>` 在 head 里，
  // 不干扰）。第二段是登录/登出那一段，不测。
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

  // F6 比 F5 多两样：401 分支要读 location.replace，失败分支要弹 alert。
  // 都收进数组，用例里断言。
  const nav = [];
  const alerts = [];
  const sandbox = {
    document, console, JSON, Math, String, Object, Array, Number, Date, setTimeout,
    location: { replace: (u) => { nav.push(u); } },
    alert: (m) => { alerts.push(m); },
  };
  sandbox.window = sandbox;
  sandbox.fetch = opts.fetch || (() => {
    throw new Error('测试里不该发请求（请给 loadPage 传 opts.fetch）');
  });
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox, { filename: path });
  return {
    // 顶层 `function` 声明会变成 sandbox 的属性，但 `let`/`const` 是词法声明、
    // 只能靠 run() 求值去读——所以读 currentSubId 这类变量必须走 run()。
    run: (code) => vm.runInContext(code, sandbox),
    el: (id) => document.getElementById(id),
    has: (name) => vm.runInContext(`typeof ${name}`, sandbox),
    nav, alerts,
  };
}

// 断言
export const results = [];
export function check(name, fn) {
  try { fn(); results.push([true, name, '']); }
  catch (e) { results.push([false, name, e.message]); }
}
export function eq(actual, expected, what = '') {
  if (actual !== expected) {
    throw new Error(`${what}\n  期望: ${JSON.stringify(expected)}\n  实际: ${JSON.stringify(actual)}`);
  }
}
export function ok(cond, what = '') { if (!cond) throw new Error(`应为真: ${what}`); }
export async function acheck(name, fn) {
  try { await fn(); results.push([true, name, '']); }
  catch (e) { results.push([false, name, e.message]); }
}
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

- [ ] **Step 3: 写失败测试 `/tmp/f6fe/t1.test.mjs`**

```js
import { loadPage, check, eq, report } from './harness.mjs';

const p = loadPage();

// 这两个函数的核心就是「空串不是 0、空白不是内容」（spec 3.10）。
check('1) scoreOrNull("") 是 null，不是 0', () => eq(p.run('scoreOrNull("")'), null));
check('2) scoreOrNull("  ") 是 null', () => eq(p.run('scoreOrNull("  ")'), null));
check('3) scoreOrNull("88.25") 是数字 88.25', () => {
  const v = p.run('scoreOrNull("88.25")');
  eq(typeof v, 'number', '类型');
  eq(v, 88.25, '值');
});
check('4) scoreOrNull("0") 是 0（合法的 0 分不能当空）', () => {
  const v = p.run('scoreOrNull("0")');
  eq(typeof v, 'number', '类型');
  eq(v, 0, '值');
});
check('5) textOrNull("   ") 是 null', () => eq(p.run('textOrNull("   ")'), null));
check('6) textOrNull 会 trim', () => eq(p.run('textOrNull(" 拖腔再稳一点 ")'), '拖腔再稳一点'));
check('7) textOrNull(null) 是 null（输入框取不到值时）', () => eq(p.run('textOrNull(null)'), null));

report();
```

- [ ] **Step 4: 跑测试，确认它失败**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
node /tmp/f6fe/t1.test.mjs
```

Expected: 7 条全 FAIL，每条信息里含 `scoreOrNull is not defined` / `textOrNull is not defined`，退出码 1。

- [ ] **Step 5: 在 `homework.html` 里加这两个函数**

在 `:1127`（`// ============================================` 那条「交互操作」横幅的下边框）之后、`function confirmCDM(btn) {`（`:1129`）之前插入：

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

- [ ] **Step 6: 跑测试，确认通过**

```bash
node /tmp/f6fe/t1.test.mjs
```

Expected:

```
PASS  1) scoreOrNull("") 是 null，不是 0
PASS  2) scoreOrNull("  ") 是 null
PASS  3) scoreOrNull("88.25") 是数字 88.25
PASS  4) scoreOrNull("0") 是 0（合法的 0 分不能当空）
PASS  5) textOrNull("   ") 是 null
PASS  6) textOrNull 会 trim
PASS  7) textOrNull(null) 是 null（输入框取不到值时）

7 PASS / 0 FAIL
```

- [ ] **Step 7: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add homework.html
git commit -m "feat: homework.html 加终审区两个空值纯函数"
```

---

## Task 2: `fetchHomeworks` 加 `keepSelection`

**Files:**
- Modify: `homework.html:728`（函数签名）、`homework.html:751`（自动选中那句）
- Create: `/tmp/f6fe/t2.test.mjs`

**Interfaces:**
- Consumes: Task 1 的夹具
- Produces: `fetchHomeworks(keepSelection = false)`。`keepSelection` 为真时不调 `selectHomework`，因此不改 `currentHwId`；为假（默认、也是页面加载时的调用）时保持原行为。

**为什么需要它**：`fetchHomeworks` 结尾是 `selectHomework(items[0].homework_id)`。终审成功后要刷新作业列表，直接复用会把教师正看着的作业**跳回第一份**（F1 按「待办优先」排序，`items[0]` 与 `currentHwId` 无关）。`renderHwList` 自己会按 `currentHwId` 刷选中态，所以只重渲列表就够。

- [ ] **Step 1: 写失败测试 `/tmp/f6fe/t2.test.mjs`**

```js
import { loadPage, acheck, eq, ok, report } from './harness.mjs';

const HW = {
  data: {
    homeworks: [{
      homework_id: 12, title: '气息控制练习', status: 'grading', deadline: null,
      total: 5, submitted_count: 5, pending_review_count: 5,
      demo_role: null, demo_banshi: null,
    }],
  },
};

// 桩 fetch 记录每次请求；两条列表接口都给一个能渲染的最小响应。
function mk() {
  const calls = [];
  const p = loadPage(undefined, {
    fetch: async (url) => {
      calls.push(url);
      if (url.endsWith('/api/homeworks')) {
        return { ok: true, status: 200, json: async () => HW };
      }
      if (url.includes('/submissions')) {
        return { ok: true, status: 200, json: async () => ({ data: { submissions: [] } }) };
      }
      throw new Error('意外请求: ' + url);
    },
  });
  // currentUser 是顶层 let（词法声明），只能靠 run 赋值。
  p.run('currentUser = { role: "teacher", display_name: "王老师" }');
  return { p, calls };
}

// 默认行为不能变：页面加载时那句 fetchHomeworks() 要自动选中第一份。
const a = mk();
await a.p.run('fetchHomeworks()');
eq(a.p.run('currentHwId'), 12, '默认应自动选中第一份');

// keepSelection：只刷列表，不动选中。
const b = mk();
b.p.run('currentHwId = 99');            // 假装教师正看着别的作业
await b.p.run('fetchHomeworks(true)');
eq(b.p.run('currentHwId'), 99, 'keepSelection 不该改 currentHwId');
ok(b.p.run('hwItems.length') === 1, '列表数据仍要更新（hwItems 应被重写）');
ok(b.calls.filter(u => u.includes('/submissions')).length === 0,
   'keepSelection 不该顺带拉待批列表');

// 学生分支不受影响（回归）。
const c = mk();
c.p.run('currentUser = { role: "student" }');
await c.p.run('fetchHomeworks()');
eq(c.calls.length, 0, '学生不发请求');
ok(c.p.el('hwList').innerHTML.includes('仅教师可见'), '学生看到权限文案');

report();
```

- [ ] **Step 2: 跑测试，确认它失败**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
node /tmp/f6fe/t2.test.mjs
```

Expected: `keepSelection 不该改 currentHwId` 那条 FAIL（实际得到 `12`，期望 `99`），因为参数还不存在、`keepSelection` 是 `undefined`（假值），自动选中照旧执行。其余条目 PASS。

- [ ] **Step 3: 改函数签名（`homework.html:728`）**

把：

```js
async function fetchHomeworks() {
```

改成：

```js
async function fetchHomeworks(keepSelection = false) {
```

- [ ] **Step 4: 改自动选中那一句（`homework.html:751`）**

把：

```js
    if (items.length) selectHomework(items[0].homework_id);
```

改成：

```js
    // keepSelection：终审成功后刷新用。默认（页面加载时那句 fetchHomeworks()）
    // 要自动选中第一份；刷新时若照做，教师正看着 hw13 会被跳回 hw12——items[0]
    // 与 currentHwId 无关。renderHwList 自己会按 currentHwId 刷选中态，
    // 所以刷新时只重渲列表就够。
    if (items.length && !keepSelection) selectHomework(items[0].homework_id);
```

- [ ] **Step 5: 跑测试，确认通过**

```bash
node /tmp/f6fe/t2.test.mjs
```

Expected:

```
PASS  默认应自动选中第一份
PASS  keepSelection 不该改 currentHwId
PASS  列表数据仍要更新（hwItems 应被重写）
PASS  keepSelection 不该顺带拉待批列表
PASS  学生不发请求
PASS  学生看到权限文案

6 PASS / 0 FAIL
```

- [ ] **Step 6: 回归 Task 1，确认没打坏**

```bash
node /tmp/f6fe/t1.test.mjs
```

Expected: `7 PASS / 0 FAIL`。

- [ ] **Step 7: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add homework.html
git commit -m "feat: fetchHomeworks 加 keepSelection，刷新时不抢选中"
```

---

## Task 3: `submitReview` 换真实现（本轮的主体）

**Files:**
- Modify: `homework.html:591`（按钮加 id）、`homework.html:1145-1148`（函数体）
- Create: `/tmp/f6fe/t3.test.mjs`

**Interfaces:**
- Consumes: Task 1 的 `textOrNull` / `scoreOrNull`；Task 2 的 `fetchHomeworks(keepSelection)`
- Produces: `async submitReview(): Promise<void>`。成功时刷新 F4 + F1 列表并在「教师没换过提交」时复位右侧；失败时 `alert` 后端 `message`；401 时 `location.replace("/login.html")`。

- [ ] **Step 1: 给按钮加 id（`homework.html:591`）**

把：

```html
                <button class="btn-success" onclick="submitReview()">✅ 通过并发布</button>
```

改成：

```html
                <button class="btn-success" id="btnSubmitReview" onclick="submitReview()">✅ 通过并发布</button>
```

- [ ] **Step 2: 写失败测试 `/tmp/f6fe/t3.test.mjs`**

```js
import { loadPage, check, acheck, eq, ok, report } from './harness.mjs';

const ok200 = () => ({
  ok: true, status: 200,
  json: async () => ({
    code: 0, message: 'ok',
    data: {
      submission_id: 24, status: 'reviewed', reviewed_at: '2026-10-08T12:00:00',
      teacher_score: 88.25, teacher_comment: '拖腔再稳一点',
      voice_comment_text: null, voice_comment_audio_id: null,
    },
  }),
});
const err = (status, message) => ({
  ok: false, status,
  json: async () => ({ code: status, message }),
});

const HW = {
  data: {
    homeworks: [{
      homework_id: 12, title: '气息控制练习', status: 'grading', deadline: null,
      total: 5, submitted_count: 5, pending_review_count: 5,
      demo_role: null, demo_banshi: null,
    }],
  },
};

// 装载一页：教师身份、选中 hw12 + 提交 24、终审区填好值。
// fetchImpl 收到 (url, opt) 决定怎么回。
function mk(fetchImpl) {
  const calls = [];
  const p = loadPage(undefined, {
    fetch: async (url, opt) => {
      calls.push({ url, opt });
      if (url.endsWith('/review')) return fetchImpl();          // 只有本接口由用例决定
      if (url.endsWith('/api/homeworks')) {
        return { ok: true, status: 200, json: async () => HW };
      }
      if (url.includes('/submissions')) {
        return { ok: true, status: 200, json: async () => ({ data: { submissions: [] } }) };
      }
      throw new Error('意外请求: ' + url);
    },
  });
  p.run('currentUser = { role: "teacher", display_name: "王老师" }');
  p.run('currentHwId = 12');
  p.run('currentSubId = 24');
  p.el('finalScore').value = '88.25';
  p.el('teacherComment').value = ' 拖腔再稳一点 ';
  return { p, calls };
}
const reviewCalls = (calls) => calls.filter(c => c.url.endsWith('/review'));

// ---- 6) 没选中提交：一个请求都不发 ----
await acheck('6) currentSubId 为 null 时不发请求', async () => {
  const { p, calls } = mk(ok200);
  p.run('currentSubId = null');
  await p.run('submitReview()');
  eq(calls.length, 0, '请求条数');
});

// ---- 7) 成功路径：URL / 方法 / 凭证 / 头 / body ----
await acheck('7) 请求的形状与 body 都对', async () => {
  const { p, calls } = mk(ok200);
  await p.run('submitReview()');
  const r = reviewCalls(calls);
  eq(r.length, 1, '终审请求条数');
  eq(r[0].url, '/api/submissions/24/review', 'URL');
  eq(r[0].opt.method, 'POST', 'method');
  eq(r[0].opt.credentials, 'same-origin', 'credentials');
  eq(r[0].opt.headers['Content-Type'], 'application/json', 'Content-Type');
  const body = JSON.parse(r[0].opt.body);
  eq(JSON.stringify(body), JSON.stringify({ teacher_score: 88.25, teacher_comment: '拖腔再稳一点' }),
     'body（分数是数字不是字符串，评语已 trim，只发这两个字段）');
});

// ---- 8) 成功且教师没换提交：右侧复位 + O(1) 两条列表都刷 ----
await acheck('8) 成功后复位右侧并刷新两条列表', async () => {
  const { p, calls } = mk(ok200);
  p.run('detailState = "content"');     // 假装右侧正显示着这名学生
  await p.run('submitReview()');
  eq(p.run('detailState'), 'idle', '右侧应回 idle');
  eq(p.run('currentSubId'), null, '高亮应被取消');
  ok(calls.some(c => c.url === '/api/homeworks/12/submissions'), 'F4 待批列表被重拉');
  ok(calls.some(c => c.url === '/api/homeworks'), 'F1 作业列表被重拉');
  eq(p.run('currentHwId'), 12, 'F1 刷新不该把选中跳走');
});

// ---- 9) 成功但提交期间教师点了别人：只刷左侧，右侧不动 ----
await acheck('9) 提交期间换了提交时不清空右侧', async () => {
  let release;
  const gate = new Promise(r => { release = r; });
  const { p, calls } = mk(async () => { await gate; return ok200(); });

  p.run('detailState = "content"');
  const flight = p.run('submitReview()');   // 不 await，让它停在 gate 上
  p.run('currentSubId = 25');               // 教师点了另一名学生
  release();
  await flight;

  eq(p.run('detailState'), 'content', '右侧不该被复位');
  eq(p.run('currentSubId'), 25, '教师新点的提交不该被清掉');
  ok(calls.some(c => c.url === '/api/homeworks/12/submissions'), 'F4 仍要刷（被批的那条要消失）');
  ok(calls.some(c => c.url === '/api/homeworks'), 'F1 仍要刷');
});

// ---- 10) 401：跳登录页，不弹 alert，不刷列表 ----
await acheck('10) 401 跳登录页', async () => {
  const { p, calls } = mk(() => err(401, '未登录'));
  await p.run('submitReview()');
  eq(JSON.stringify(p.nav), JSON.stringify(['/login.html']), 'location.replace 实参');
  eq(p.alerts.length, 0, '不该弹 alert');
  eq(calls.length, 1, '不该刷列表');
});

// ---- 11) 422：alert 后端原话，且不刷列表 ----
await acheck('11) 422 显示后端 message', async () => {
  const { p, calls } = mk(() => err(422, 'teacher_score: 终审评分必须在 0 到 100 之间'));
  await p.run('submitReview()');
  eq(p.alerts.length, 1, 'alert 条数');
  ok(p.alerts[0].includes('teacher_score: 终审评分必须在 0 到 100 之间'), 'alert 正文');
  eq(calls.length, 1, '失败不该刷列表');
});

// ---- 12) 404 ----
await acheck('12) 404 显示「提交不存在」', async () => {
  const { p } = mk(() => err(404, '提交不存在'));
  await p.run('submitReview()');
  ok(p.alerts[0].includes('提交不存在'), 'alert 正文');
});

// ---- 13) 网络异常 ----
await acheck('13) 网络异常兜底', async () => {
  const { p } = mk(() => { throw new Error(''); });
  await p.run('submitReview()');
  ok(p.alerts[0].includes('网络异常'), 'alert 正文');
});

// ---- 14) / 15) 按钮的飞行中态与复位 ----
await acheck('14) 飞行中按钮禁用且文案改变', async () => {
  let release;
  const gate = new Promise(r => { release = r; });
  const { p } = mk(async () => { await gate; return ok200(); });
  const flight = p.run('submitReview()');
  eq(p.el('btnSubmitReview').disabled, true, 'disabled');
  ok(p.el('btnSubmitReview').textContent.includes('发布中'), '文案');
  release();
  await flight;
});

await acheck('15) 失败后按钮复位', async () => {
  const { p } = mk(() => err(500, '服务器内部错误'));
  await p.run('submitReview()');
  eq(p.el('btnSubmitReview').disabled, false, 'disabled 应复位');
  eq(p.el('btnSubmitReview').textContent, '✅ 通过并发布', '文案应复位');
});

report();
```

- [ ] **Step 3: 跑测试，确认它失败**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
node /tmp/f6fe/t3.test.mjs
```

Expected: 用例 7 / 8 / 9 / 10 / 11 / 12 / 14 / 15 **FAIL**（当前的 `submitReview` 只弹一句 alert、一个请求都不发，也没有 `#btnSubmitReview` 这个元素）；
用例 6 **PASS**（现在这个函数确实不发请求——但它是「因为压根不发」而不是「因为守卫」，Step 5 改完后它才真正测到守卫）；
用例 13 的 alert 文案对不上（现在弹的是「✅ 终审已发布…」，不含「网络异常」）→ FAIL。

- [ ] **Step 4: 替换函数体（`homework.html:1145-1148`）**

把这四行：

```js
function submitReview() {
  const score = document.getElementById("finalScore").value;
  alert(`✅ 终审已发布\n终审评分: ${score}分\n点评已保存，BKT 状态已更新`);
}
```

整个替换成：

```js
// 教师终审：POST /api/submissions/<id>/review（F6，统一信封）。
// 只发终审区那两个字段——语音点评本轮不做（spec 3.1）。
// 原来这里那句 alert 宣称「点评已保存，BKT 状态已更新」，而实际什么都没发生
// （BKT 更不归本接口管），换成真调用后它连同假文案一起消失。
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
      // 教师还停在被批的那条 → 右侧整块复位回 idle（spec 3.4）。它已经从待批
      // 列表里消失，留着内容会让左下没有对应的高亮卡片。selectHomework 会
      // 顺带重拉一次 F4，所以这条分支里不再单独调 fetchSubmissions。
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

- [ ] **Step 5: 跑测试，确认全部通过**

```bash
node /tmp/f6fe/t3.test.mjs
```

Expected:

```
PASS  6) currentSubId 为 null 时不发请求
PASS  7) 请求的形状与 body 都对
PASS  8) 成功后复位右侧并刷新两条列表
PASS  9) 提交期间换了提交时不清空右侧
PASS  10) 401 跳登录页
PASS  11) 422 显示后端 message
PASS  12) 404 显示「提交不存在」
PASS  13) 网络异常兜底
PASS  14) 飞行中按钮禁用且文案改变
PASS  15) 失败后按钮复位

10 PASS / 0 FAIL
```

- [ ] **Step 6: 全量回归三支夹具**

```bash
node /tmp/f6fe/t1.test.mjs && node /tmp/f6fe/t2.test.mjs && node /tmp/f6fe/t3.test.mjs
```

Expected: 三支都是 `0 FAIL`（7 + 6 + 10 = 23 条）。

- [ ] **Step 7: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add homework.html
git commit -m "feat: homework.html 终审区接上 F6 终审接口"
```

---

## Task 4: 真接口端到端（**会写库，必须复原**）

**Files:**
- Modify: `/tmp/f6fe/api.mjs`（`post` 加 body 参数）
- Create: `/tmp/f6fe/e2e.mjs`

**Interfaces:**
- Consumes: Task 3 的 `submitReview`（本任务发出去的 body 与 Task 3 用例 7 断言的**逐字相同**）
- Produces: 无仓库产物

**本任务不改仓库文件，因此没有提交步骤。**

- [ ] **Step 1: 起后端**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
.venv/bin/python app-d.py > /tmp/f6fe/server.log 2>&1 &
sleep 3
curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:8877/api/homeworks
```

Expected: `HTTP 401`（未登录，说明服务起来了）。F6 不走 redis、不走 celery，**不需要 worker**。

- [ ] **Step 2: 抓快照（动手前必做）**

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -At -c \
 "SELECT id, coalesce(teacher_score::text,'<NULL>'), coalesce(teacher_comment,'<NULL>'), \
  coalesce(voice_comment_text,'<NULL>'), coalesce(voice_comment_audio_id::text,'<NULL>'), \
  status, coalesce(reviewed_at::text,'<NULL>') FROM submissions WHERE id=25;"
```

Expected（与 Global Constraints 的基线一致）：

```
25|<NULL>|<NULL>|<NULL>|<NULL>|ai_scored|<NULL>
```

**把这一行抄进 `/tmp/f6fe/snapshot.txt`**，Step 6 按它逐列改回。

- [ ] **Step 3: 给 `api.mjs` 的 `post` 加 body 参数**

`/tmp/f6fe/api.mjs` 现在是（从 F5 复制来的）：

```js
    async post(path) {
      const res = await fetch(`${BASE}${path}`, { method: 'POST', headers: { Cookie: cookie } });
      return { status: res.status, body: await res.json().catch(() => null) };
    },
```

改成：

```js
    async post(path, json) {
      const headers = { Cookie: cookie };
      const init = { method: 'POST', headers };
      if (json !== undefined) {
        headers['Content-Type'] = 'application/json';
        init.body = JSON.stringify(json);
      }
      const res = await fetch(`${BASE}${path}`, init);
      return { status: res.status, body: await res.json().catch(() => null) };
    },
```

- [ ] **Step 4: 写 `/tmp/f6fe/e2e.mjs`**

```js
// 把页面在「终审 25 号」时会发出的那个 body 原样喂给真接口。
// 这个 body 必须与 t3.test.mjs 用例 7 断言的一致。
import { login } from './api.mjs';

const BODY = { teacher_score: 88.25, teacher_comment: '拖腔再稳一点' };

const t = await login('teacher01', 'xiyun@2026');
console.log('发出的 body:', JSON.stringify(BODY));

const r = await t.post('/api/submissions/25/review', BODY);
console.log('HTTP', r.status);
console.log(JSON.stringify(r.body));

const d = r.body && r.body.data;
const bad = [];
if (r.status !== 200) bad.push(`状态码应为 200，实得 ${r.status}`);
if (r.body && r.body.code !== 0) bad.push(`code 应为 0，实得 ${r.body.code}`);
if (d) {
  if (d.status !== 'reviewed') bad.push(`status 应为 reviewed，实得 ${d.status}`);
  if (!d.reviewed_at) bad.push('reviewed_at 应非空');
  if (d.teacher_score !== 88.25) bad.push(`teacher_score 应为 88.25，实得 ${d.teacher_score}`);
  if (d.teacher_comment !== '拖腔再稳一点') bad.push(`teacher_comment 不符：${d.teacher_comment}`);
  // 页面本轮不发语音两个字段，PATCH 语义下它们必须保持不动（原本都是 NULL）
  if (d.voice_comment_text !== null) bad.push('voice_comment_text 不该被写');
  if (d.voice_comment_audio_id !== null) bad.push('voice_comment_audio_id 不该被写');
} else {
  bad.push('响应里没有 data');
}

if (bad.length) { console.log('\nFAIL:\n - ' + bad.join('\n - ')); process.exit(1); }
console.log('\nPASS：契约与预期一致（别忘了 Step 6 复原）');
```

- [ ] **Step 5: 跑**

```bash
cd /tmp/f6fe && node e2e.mjs
```

Expected:

```
发出的 body: {"teacher_score":88.25,"teacher_comment":"拖腔再稳一点"}
HTTP 200
{"code":0,"message":"ok","data":{"submission_id":25,"status":"reviewed","reviewed_at":"2026-10-08T...","teacher_score":88.25,"teacher_comment":"拖腔再稳一点","voice_comment_text":null,"voice_comment_audio_id":null}}

PASS：契约与预期一致（别忘了 Step 6 复原）
```

- [ ] **Step 6: 复核库里的值**

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -At -c \
 "SELECT id, teacher_score, teacher_comment, coalesce(voice_comment_text,'<NULL>'), \
  coalesce(voice_comment_audio_id::text,'<NULL>'), status, (reviewed_at IS NOT NULL) \
  FROM submissions WHERE id=25;"
```

Expected: `25|88.25|拖腔再稳一点|<NULL>|<NULL>|reviewed|t`

- [ ] **Step 7: 复原（按抓到的 id 逐列改回）**

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -c \
 "UPDATE submissions SET teacher_score=NULL, teacher_comment=NULL, \
  voice_comment_text=NULL, voice_comment_audio_id=NULL, \
  status='ai_scored', reviewed_at=NULL WHERE id=25;"
```

Expected: `UPDATE 1`

- [ ] **Step 8: 独立复核（不信脚本、也不信上一步的输出）**

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -At -c \
 "SELECT id, coalesce(teacher_score::text,'<NULL>'), coalesce(teacher_comment,'<NULL>'), \
  coalesce(voice_comment_text,'<NULL>'), coalesce(voice_comment_audio_id::text,'<NULL>'), \
  status, coalesce(reviewed_at::text,'<NULL>') FROM submissions WHERE id=25;"
```

Expected: 与 Step 2 抄进 `snapshot.txt` 的那一行**逐字相同**：

```
25|<NULL>|<NULL>|<NULL>|<NULL>|ai_scored|<NULL>
```

- [ ] **Step 9: 顺带核一遍 F4 的待批数也回到 5**

本轮的验证脚本是 node 直连（`api.mjs` 自己管 Cookie），**没有 cookie jar 文件**，所以这里也走 node：

```bash
cd /tmp/f6fe && node -e "
import('./api.mjs').then(async ({ login }) => {
  const t = await login();
  const r = await t.get('/api/homeworks/12/submissions');
  console.log('HTTP', r.status, '待批条数 =', r.body && r.body.data ? r.body.data.submissions.length : '?');
});
"
```

Expected: `HTTP 200 待批条数 = 5`（复原后 25 号重新计入待批）。

---

## Task 5: 人在浏览器里走一遍完整流程（**会写库，必须复原**）

**Files:** 无（不改仓库文件，**无提交步骤**）

**为什么还要走这一步**：Task 1–3 的夹具用假 DOM，验的是「函数发出的请求对不对」；Task 4 用 node 直连，验的是「接口收不收」。两者都碰不到真 DOM 的渲染路径——右侧复位是不是真的把 `#reviewContent` 藏起来了、左侧列表是不是真的少了一条、作业列表的待批数有没有变，只有真页面能看。

- [ ] **Step 1: 确认后端在跑（Task 4 Step 1 起的那个还在）**

```bash
curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:8877/login.html
```

Expected: `HTTP 200`。不在就按 Task 4 Step 1 重新起。

- [ ] **Step 2: 抓快照**

hw12 下 5 条待批（id 23/24/25/26/27）全抓一份——**事先不知道会点中哪一条**：

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -At -c \
 "SELECT id, coalesce(teacher_score::text,'<NULL>'), coalesce(teacher_comment,'<NULL>'), \
  coalesce(voice_comment_text,'<NULL>'), coalesce(voice_comment_audio_id::text,'<NULL>'), \
  status, coalesce(reviewed_at::text,'<NULL>') FROM submissions WHERE id IN (23,24,25,26,27) ORDER BY id;" \
 | tee /tmp/f6fe/snapshot_browser.txt
```

Expected: 5 行，其中 23/24 有 `teacher_score` 与评语、25/26/27 两列都是 `<NULL>`。

- [ ] **Step 3: 用 `/browse` 打开页面并登录**

按 `CLAUDE.md` 的规定，**所有网页浏览走 `/browse` 技能**，不要用 `mcp__claude-in-chrome__*`。

打开 `http://127.0.0.1:8877/login.html`，用 `teacher01` / `xiyun@2026` 登录，然后进 `http://127.0.0.1:8877/homework.html`。

- [ ] **Step 4: 核对初始态**

| 观察点 | 期望 |
|---|---|
| 左侧待批列表 | 5 条（默认选中的作业应是 hw12——F1 按「待办优先」排序，`grading` 排最前） |
| 右侧面板 | 显示「选择左侧提交进行批改」空态 |
| 作业列表里 hw12 | 状态「批改中」，待批数 5 |

若默认选中的不是 hw12，**以实际选中的那份为准**记下它的待批数与提交 id 集合，后续按它核对。

- [ ] **Step 5: 走一次终审**

1. 点左侧第一条待批提交
2. 把「终审评分」改成 `88.25`
3. 把「老师终审点评」改成 `F6 前端联调测试`
4. 点「✅ 通过并发布」

| 观察点 | 期望 |
|---|---|
| 按钮 | 短暂变成「⏳ 发布中…」且不可点，然后恢复成「✅ 通过并发布」 |
| 左侧待批列表 | 该条消失，条数 5 → 4 |
| 右侧面板 | 回到「选择左侧提交进行批改」空态（不是停在刚才那名学生上） |
| 作业列表那份作业 | 待批数 5 → 4；**批完最后一条前状态仍是「批改中」** |
| 顶部计数 | 不变（它只数 `ongoing`，批改中与已截止都不算） |
| 弹窗 | **一个都没有** |

- [ ] **Step 6: 核库**

页面上看不到 submission id，**按写进去的评语反查**（这是我们自己刚写的值，不是猜的）：

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -At -c \
 "SELECT id, teacher_score, teacher_comment, coalesce(voice_comment_text,'<NULL>'), \
  coalesce(voice_comment_audio_id::text,'<NULL>'), status, (reviewed_at IS NOT NULL) \
  FROM submissions WHERE teacher_comment='F6 前端联调测试';"
```

Expected: 恰好 1 行，形如 `2x|88.25|F6 前端联调测试|<NULL>|<NULL>|reviewed|t`，且 id 落在 Task 5 Step 2 抓的 5 个 id 里。

- [ ] **Step 7: 复原这一条（按 Step 6 抓到的 id）**

把 `<ID>` 换成 Step 6 实际查到的 id，列值照 Step 2 的快照改回：

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -c \
 "UPDATE submissions SET teacher_score=NULL, teacher_comment=NULL, \
  voice_comment_text=NULL, voice_comment_audio_id=NULL, \
  status='ai_scored', reviewed_at=NULL WHERE id=<ID>;"
```

Expected: `UPDATE 1`

**若 Step 6 查到的 id 是 23 或 24**（这两条点选前就有分数与评语），上面的语句会把它们清空——必须先看 `snapshot_browser.txt` 里对应那一行，把 `teacher_score` / `teacher_comment` 改成快照里的原值再执行。**绝不用 `DELETE`**。

- [ ] **Step 8: 独立复核 5 条全回到基线**

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -At -c \
 "SELECT id, coalesce(teacher_score::text,'<NULL>'), coalesce(teacher_comment,'<NULL>'), \
  coalesce(voice_comment_text,'<NULL>'), coalesce(voice_comment_audio_id::text,'<NULL>'), \
  status, coalesce(reviewed_at::text,'<NULL>') FROM submissions WHERE id IN (23,24,25,26,27) ORDER BY id;"
```

Expected: 与 `/tmp/f6fe/snapshot_browser.txt` **逐字相同**。`diff` 一下更稳：

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -At -c \
 "SELECT id, coalesce(teacher_score::text,'<NULL>'), coalesce(teacher_comment,'<NULL>'), \
  coalesce(voice_comment_text,'<NULL>'), coalesce(voice_comment_audio_id::text,'<NULL>'), \
  status, coalesce(reviewed_at::text,'<NULL>') FROM submissions WHERE id IN (23,24,25,26,27) ORDER BY id;" \
 > /tmp/f6fe/after_browser.txt
diff /tmp/f6fe/snapshot_browser.txt /tmp/f6fe/after_browser.txt && echo "复原一致"
```

Expected: 无差异输出，最后一行 `复原一致`。

- [ ] **Step 9: 关掉后端**

```bash
pkill -f 'app-d.py'
```

Expected: 无输出；`curl` 再打 8877 应连不上。

---

## Task 6: 登记 `DOC_ISSUES.md` 第 39 条

**Files:**
- Modify: `DOC_ISSUES.md`（在 `## 待核实` 之前、`## 38.` 那条的收尾 `---` 之后插入）

**Interfaces:**
- Consumes: 无
- Produces: 无

- [ ] **Step 1: 确认插入位置**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
grep -n "^## 38\.\|^## 待核实" DOC_ISSUES.md
```

Expected:

```
1239:## 38. 教师终审批改（F6）只有一行描述，...
1270:## 待核实
```

（行号会随本轮前面的提交漂移，以实际输出为准；要插的就是 `## 待核实` 之前。）

- [ ] **Step 2: 插入第 39 条**

把这段：

```markdown
---

## 待核实
```

替换成（把新条目插在中间）：

```markdown
---

## 39. F6 前端已接入，但「保存草稿」「语音点评」两个按钮做不到名副其实的事

F6 后端（`POST /api/submissions/<id>/review`，见第 38 条）落地后，`homework.html` 的
「✅ 通过并发布」已接真接口（设计 `docs/superpowers/specs/2026-10-08-submission-review-page-design.md`）。
终审区另外两个按钮**本轮不动，仍是 alert 桩**，原因如下。

**① 「💾 保存草稿」在文档与库表里都没有承载物。** 4.9 的功能描述里列了这个动作，但
`submissions.status` 只有 `submitted / ai_scored / reviewed` 三档（还只活在 DDL 行尾注释里，
见第 38 条第 3 点），没有 `draft`；F6 的语义又是「调用即 `reviewed`」——真接上去，点一下
「保存草稿」学生那边就算批完了。按钮留在页面上，但它做不到名副其实的事：要么定义草稿态
（新档 / 新表 / 前端本地），要么从需求里去掉。

**② 功能 4.11（语音点评）的读侧在页面上也没有出口。** F5 的详情出参早就把
`voice_comment_text` / `voice_comment_audio_id` 送到了页面（`app/schemas/homework.py:269-270`，
F5 设计里还专门写了「不给的话功能 4.11 的语音点评音频就取不回来」），而 `homework.html` 里
对这两个名字的渲染是**零处**。加上服务端没有 ASR 组件（第 38 条第 1 点）、教师语音点评音频
该不该复用 B1 `POST /api/audio/upload` 没定、B5 的私有音频学生（非上传者）能不能播也没定，
4.11 目前是「写不了也读不出」——不只是缺一个录音控件。

**③ F6 让 `closed` 这一档第一次可以由「批改完成」产生。** `homework.html` 的
`HW_STATUS_TEXT` 把 `closed` 译成「已截止」，而 F6 之前 `closed` 只可能来自「截止时间已过」。
F6 之后，一份截止日期还没到的作业只要批完全部提交就会转成 `closed`（后端实测：hw12 的 5 条
全部批完后 `GET /api/homeworks` 返回 `status="closed"`、`pending_review_count=0`），
页面于是把它显示成「已截止」。同一个状态值现在承载两种语义，页面区分不了，教师也没法从
文案上看出「是截止了」还是「批完了」。

**④ 终审完成没有任何通知学生的途径。** 清单里没有通知类接口，`submissions` 也没有
`notified_at` 之类的列。教师点了「通过并发布」，学生在自己的页面上看不到任何变化。

**本轮前端另有两处自拟口径**（文档均未定义，随本条目一并登记）：终审请求体**两个字段都发**
（页面上的值即最终值，留空则发 `null` 清空该列——与 4.9「一键通过（终审保留）」并不等价，
页面没有那个入口）；`#finalScore` 与 `teacherComment` 清空时发 `null` 而**不是空串**
（空串会往 TEXT 列写长度 0 的字符串，且 `Number("")` 是 0 分）。

**待文档方确认**：① 「保存草稿」是不是正式功能点，若是则草稿存在哪；② 4.11 的语音转文字用
什么组件、教师语音音频走不走 B1、`access` 设什么学生才播得到；③ 终审能不能撤回/退回；
④ 4.9 的「一键通过」在页面上要不要有独立入口；⑤ 终审评分是否必填（4.8 带分数、4.9 又暗示
可以不打分）；⑥ 批改完成后的作业状态该显示什么（见上面第 ③ 点）；⑦ 要不要通知学生。

---

## 待核实
```

- [ ] **Step 3: 核对结构没被破坏**

```bash
grep -n "^## 38\.\|^## 39\.\|^## 待核实" DOC_ISSUES.md
```

Expected: 三行，顺序为 38 → 39 → 待核实，行号递增。

- [ ] **Step 4: 提交**

```bash
git add DOC_ISSUES.md
git commit -m "docs: 登记 DOC_ISSUES 第 39 条（F6 前端接入）"
```

- [ ] **Step 5: 收尾核对**

```bash
git status --short          # 期望：空（工作树干净）
git log --oneline -6        # 期望：本轮 4 条提交（Task 1/2/3/6 各一条）
grep -c "console.log" homework.html   # 期望：0（没留调试输出）
```

Expected: 工作树干净；提交历史能看到本轮 4 条；`homework.html` 里没有 `console.log`。

---

## 自审

### Spec 覆盖

| spec 章节 | 落在哪个任务 |
|---|---|
| §1.1 只接「通过并发布」 | Task 3（另两个按钮在 Task 3 Step 4 的替换范围外，一行未动） |
| §2.2 现状（三个桩、回显三行） | Task 3 Step 4 只换 `submitReview`；`fillDetail` 未在 Files 里出现 |
| §3.1 / §3.2 请求体两个字段都发 | Task 3 Step 2 用例 7、Step 4 |
| §3.3 一键通过无独立入口 | Task 3 Step 4（没有第二个按钮） |
| §3.4 成功后刷两条列表 + 右侧复位 | Task 3 Step 2 用例 8 |
| §3.5 刷新不抢选中 | Task 2（`keepSelection`）+ Task 3 Step 2 用例 8 末尾 |
| §3.6 提交期间切换提交的竞态 | Task 3 Step 2 用例 9 |
| §3.7 防双击 | Task 3 Step 2 用例 14 / 15 |
| §3.8 错误呈现 + 401 跳登录页 | Task 3 Step 2 用例 10 / 11 / 12 / 13 |
| §3.9 不做前端范围校验 | Task 3 Step 4（没有 range 判断）；后端 422 在 Task 4 覆盖 |
| §3.10 空值发 null | Task 1（两个纯函数）+ Task 1 用例 1-7 |
| §3.11 不用响应体 | Task 3 Step 4（成功分支不读 `data`） |
| §4.1 五处改动 | Task 1（纯函数）、Task 2（签名 + 自动选中）、Task 3（按钮 id + 函数体） |
| §4.6 批完后的页面表现 | Task 5 Step 5 |
| §5.1 16 条夹具用例 | Task 1（1-5 的纯函数部分）、Task 2（16）、Task 3（6-15） |
| §5.2 真链路 + 复原纪律 | Task 4 |
| §5.3 浏览器走一遍 | Task 5 |
| §7 第 39 条 | Task 6 |

### 与 spec 的差异（有意，说明理由）

- spec §5.1 用例 1-5 是纯函数用例，本计划把**「`scoreOrNull("0")` 是 0 不是 null」另立为用例 4**——
  这是 spec 没写但必须守的一条：合法 0 分不能被空值口径吃掉。加在 Task 1。
- spec §5.1 用例 16 把 `fetchHomeworks` 的两种调用写成一行，本计划把它拆进 Task 2 并**多加了
  一条学生分支回归**（`keepSelection` 改动碰的是同一个函数的入口，学生分支必须重测）。

### 占位符扫描

无 TBD / TODO / 「类似 Task N」/ 「加上适当的错误处理」。每个改代码的步骤都给了完整代码，
每个跑命令的步骤都给了预期输出。

### 类型与名字一致性

- `textOrNull` / `scoreOrNull`：Task 1 定义，Task 3 Step 4 调用，名字逐字一致。
- `fetchHomeworks(keepSelection = false)`：Task 2 定义，Task 3 Step 4 以 `fetchHomeworks(true)` 调用。
- `btnSubmitReview`：Task 3 Step 1 加在标记上，Step 2 用例 14/15 读它，Step 4 代码用它。
- 请求体字段名 `teacher_score` / `teacher_comment`：Task 3 用例 7 断言的字面量与 Task 4 `BODY`
  常量、与后端 `SubmissionReviewIn` 三者一致。
- Task 4 的 `t.post(path, json)` 与 `api.mjs` 改动后的签名一致。

### 两处**未经实测**的东西（老实标注）

1. **Task 5 的浏览器观察结果全部是按 DOM 代码推出来的**（`#reviewContent` 会被 `display:none`、
   左侧少一条、作业列表待批数减 1），没有真跑过——本轮执行时才第一次跑。若与预期不符，
   以页面实际行为为准，并回头查 `renderDetail` / `renderSubmitList` / `renderHwList` 的实现。
2. **Task 5 Step 4 说「默认选中的应是 hw12」是推断**：F1 的排序是「待办优先」，但真库此刻
   究竟哪份作业是 `grading` 没有实测过（Task 5 Step 2 只查了 `submissions`）。Step 4 已写明
   「以实际选中的那份为准」。
