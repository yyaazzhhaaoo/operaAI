# 实时跟唱页实时节奏偏差与气息稳定性 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `sing_along.html` 实时卡片「节奏偏差 (秒)」「气息稳定性」从按唱到第几个字查表的硬编码值，改成用真实录音数据经 DTW 映射计算的读数，并把新算法纳入 `scripts/test_sing_along_algo.js` 的覆盖范围。

**Architecture:** 全部算术落在页面既有的「纯算法」段（`// ===== BEGIN/END 纯算法` 之间，该段不碰 DOM，被测试脚本用 Node `vm` 原样抽出来跑断言）；实时链路复用停录后那套对齐原语（`thinTeacher` → `dtwAlign` → `rhythmMetrics` 的 `tempo` 门限），逐字时值偏差从 DTW 映射上读，不靠在字附近找发声帧（库里的歌词是无缝的，那条路会退化）。段外只加一层每 500ms 调一次的 DOM 薄壳。

**Tech Stack:** 单文件自包含 HTML 原型（无构建、无框架、无依赖）+ Node.js 内置 `vm`/`fs` 测试脚本。

**Spec:** `docs/superpowers/specs/2026-10-10-sing-along-live-metrics-design.md`

## Global Constraints

- 注释与 UI 文案一律简体中文；代码标识符保持英文。
- **「纯算法」段内不得出现 `document`、DOM 节点、音频句柄或页面可变全局**。测试脚本 `scripts/test_sing_along_algo.js:39` 只往 `vm` 上下文里给 `Math`，一旦往里塞 `document.xxx` 会当场抛错。抽取边界是 `// ===== BEGIN 纯算法` 行的换行符之后 到 `// ===== END 纯算法` 之前。
- 不新增任何 npm / pip 依赖；不新增接口；后端一行不动；**不碰停录后的评分流程与音准实时卡片**。
- 新增常数只有三个，值固定：`LIVE_CALC_INTERVAL_MS = 500`、`DEV_GOOD_SEC = 0.10`、`DEV_WARN_SEC = 0.25`。**不新增算法常数**（复用 `RHYTHM_BAND_SEC` / `WORD_MATCH_SEC` / `DTW_MAX_CELLS` / `RYTHM_MID` 等既有常数）。
- 门限照搬停录后的判据 `tempo ∈ [0.5, 2]`，不新造标准。
- 测试命令恒为 `node scripts/test_sing_along_algo.js`（在项目根目录跑），**必须全绿才提交**。本次断言由 20 条增至 34 条。
- 直提 `main`，不开分支。提交信息用中文。
- 每个函数名、参数顺序、返回字段名必须与本计划写的一字不差——后续任务的代码直接调用前面任务产出的函数。
- **行号一律是"本计划写下时"的快照**。前面任务的插入/删除会让后面任务的行号整体下移，所以**每次改动都用本计划给出的代码原文去定位**，不要按行号跳转。找不到原文说明文件已被改过，先停下来核对，不要凭行号硬改。

## File Structure

| 文件 | 类型 | 职责 |
|---|---|---|
| `sing_along.html` | 改 | 算法段：新增 `nearestTeacherIdx`、`wordDurationByMapping`、`breathScoreFromCv`，`wordDeviations` 改调 `nearestTeacherIdx`。段外：删 `updateMetrics` 内的查表假值段，新增实时薄壳（`startLiveCards` / `latestItem` / `updateLiveMetrics` / `applyRhythmCard` / `applyBreathCard`），`recordLoop` 加节流调用、`toggleRecord` 加卡片初始化、`stopAll` 加缓存清理 |
| `scripts/test_sing_along_algo.js` | 改 | `ALGO_NAMES` 增 3 个名字；新增 4 个小节共 14 条断言；`runPipeline` 改调 `algo.breathScoreFromCv` |

无新增文件。

## 任务总览

| # | 任务 | 交付物 | 新增断言 |
|---|---|---|---|
| 1 | 抽出 `nearestTeacherIdx`，`wordDeviations` 改调它 | 算法段去重（行为不变） | 2 → 22 |
| 2 | `wordDurationByMapping`：逐字时值偏差 | 卡片主数的算法 | 6 → 28 |
| 3 | `breathScoreFromCv`：稳定度式子去重 | 实时与停录后共用同一式子 | 5 → 33 |
| 4 | 实时薄壳接线：删假值、两张卡出真数 | 页面行为改变 | 1 → 34 |

---

### Task 1: 抽出 `nearestTeacherIdx`，`wordDeviations` 改调它

**Files:**
- Modify: `sing_along.html:1528-1547`（`wordDeviations`，含其上方注释块）
- Modify: `scripts/test_sing_along_algo.js:17-20`（`ALGO_NAMES`）、文件末尾 `// ===== 汇总 =====` 之前（新增断言）

**Interfaces:**
- Consumes: 无（`WORD_MATCH_SEC` 已在算法段内定义，`sing_along.html:1430`）
- Produces: `nearestTeacherIdx(tea, t) -> number` —— `tea` 是 `[{t, pitch}, ...]`，返回离时刻 `t` 最近的乐谱点下标；`t` 非有限、或最近距离 > `WORD_MATCH_SEC` 时返回 `-1`。Task 2 直接调它。

- [ ] **Step 1: 写失败的测试**

打开 `scripts/test_sing_along_algo.js`，把 `ALGO_NAMES`（`:17-20`）改成：

```js
const ALGO_NAMES = [
  "dtwAlign", "rhythmMetrics", "wordDeviations", "breathMetrics",
  "logistic", "thinTeacher", "nearestTeacherIdx",
];
```

在文件末尾 `// ===== 汇总 =====` 那一行（当前 `:371`）**之前**插入：

```js
// ===== nearestTeacherIdx（wordDeviations 与 wordDurationByMapping 共用的判定）=====
console.log("\nnearestTeacherIdx");

test("窗内有样本：返回离该时刻最近的乐谱点下标", () => {
  isFn(algo.nearestTeacherIdx, "nearestTeacherIdx");
  const tea = makeTeacher(3, 0.02);   // t = 0, 0.02, …, 3.00
  const j = algo.nearestTeacherIdx(tea, 1.0);
  assert(j >= 0, "1.0 落在曲线上，不该返回 -1");
  close(tea[j].t, 1.0, 0.02, "最近点的时刻");
});

test("窗内没有样本：返回 -1", () => {
  isFn(algo.nearestTeacherIdx, "nearestTeacherIdx");
  const tea = makeTeacher(3, 0.02);
  assert(algo.nearestTeacherIdx(tea, 9.0) === -1, "离曲线 6s 远，应返回 -1");
  assert(algo.nearestTeacherIdx(tea, NaN) === -1, "非有限时刻应返回 -1");
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `node scripts/test_sing_along_algo.js`
Expected: FAIL —— 2 条 `nearestTeacherIdx` 断言报 `nearestTeacherIdx 未定义——算法段里还没有这个函数`，末尾 `✗ 2 个失败，20 个通过`

- [ ] **Step 3: 实现**

在 `sing_along.html` 里，把下面这段（`wordDeviations` **连同它上方那 4 行注释**，本计划写下时在 `:1524-1547`）：

```js
// 逐字偏差：每个字起唱时刻相对乐谱的偏移（秒）。
// 取法不是「在字起点附近找发声帧」——学生连着唱时字间没有静音，那样找出来的
// 永远是搜索窗的左边缘。改为直接读 DTW 映射：字起点处的学生时刻 vs 乐谱时刻，
// 与 rhythmMetrics 的残差同源，漏唱一段时也只是偏差变大而不会崩。
function wordDeviations(stu, tea, mapping, lyrics) {
  const items = [];
  if (!lyrics || lyrics.length === 0) return { items, median: 0 };
  for (let k = 0; k < lyrics.length; k++) {
    const ly = lyrics[k];
    // 标点：pitch 为 null，算不出偏差（C3 spec），跳过
    if (ly.pitch === null || !Number.isFinite(ly.pitch) || !Number.isFinite(ly.start)) continue;
    // 找离字起点最近的乐谱点；离得太远说明这个字的起点没有落在乐谱曲线上（如标点后的字）
    let j = -1, bestD = Infinity;
    for (let p = 0; p < tea.length; p++) {
      const d = Math.abs(tea[p].t - ly.start);
      if (d < bestD) { bestD = d; j = p; }
    }
    if (j < 0 || bestD > WORD_MATCH_SEC || j >= mapping.length) continue;
    const actualT = stu[mapping[j]].t;
    items.push({ index: k, expectedT: ly.start, actualT, diff: actualT - ly.start });
  }
  const median_ = items.length ? median(items.map(it => it.diff)) : 0;
  return { items, median: median_ };
}
```

替换为下面这段——注意 `nearestTeacherIdx` 放在 `wordDeviations` 之前：

```js
// 离时刻 t 最近的乐谱点下标；最近距离超过 WORD_MATCH_SEC 说明这个时刻没有落在
// 乐谱曲线上（例如标点之后的字），返回 -1。
// wordDeviations（读起点）与 wordDurationByMapping（读间隔）共用这一个判定，两处不会漂。
function nearestTeacherIdx(tea, t) {
  if (!Number.isFinite(t)) return -1;
  let j = -1;
  let bestD = Infinity;
  for (let p = 0; p < tea.length; p++) {
    const d = Math.abs(tea[p].t - t);
    if (d < bestD) { bestD = d; j = p; }
  }
  if (j < 0 || bestD > WORD_MATCH_SEC) return -1;
  return j;
}
// 逐字偏差：每个字起唱时刻相对乐谱的偏移（秒）。
// 取法不是「在字起点附近找发声帧」——学生连着唱时字间没有静音，那样找出来的
// 永远是搜索窗的左边缘。改为直接读 DTW 映射：字起点处的学生时刻 vs 乐谱时刻，
// 与 rhythmMetrics 的残差同源，漏唱一段时也只是偏差变大而不会崩。
function wordDeviations(stu, tea, mapping, lyrics) {
  const items = [];
  if (!lyrics || lyrics.length === 0) return { items, median: 0 };
  for (let k = 0; k < lyrics.length; k++) {
    const ly = lyrics[k];
    // 标点：pitch 为 null，算不出偏差（C3 spec），跳过
    if (ly.pitch === null || !Number.isFinite(ly.pitch) || !Number.isFinite(ly.start)) continue;
    const j = nearestTeacherIdx(tea, ly.start);
    if (j < 0 || j >= mapping.length) continue;
    const actualT = stu[mapping[j]].t;
    items.push({ index: k, expectedT: ly.start, actualT, diff: actualT - ly.start });
  }
  const median_ = items.length ? median(items.map(it => it.diff)) : 0;
  return { items, median: median_ };
}
```

行为与替换前逐字等价，唯一的差别是"找最近乐谱点"的循环被提出去了。

- [ ] **Step 4: 跑测试确认通过**

Run: `node scripts/test_sing_along_algo.js`
Expected: PASS —— `✓ 22 个全部通过`。**特别确认 `wordDeviations` 原有 3 条断言（准时、整体晚 0.5s、标点跳过）仍然通过**，它们就是这个重构的护栏。

- [ ] **Step 5: 提交**

```bash
git add sing_along.html scripts/test_sing_along_algo.js
git commit -m "refactor: 抽出 nearestTeacherIdx，wordDeviations 改调它"
```

---

### Task 2: `wordDurationByMapping`：逐字时值偏差

**Files:**
- Modify: `sing_along.html` 算法段内（插在 `wordDeviations` 之后、`breathMetrics` 之前，当前 `:1548` 附近）
- Modify: `scripts/test_sing_along_algo.js:17-20`（`ALGO_NAMES`）、文件末尾 `// ===== 汇总 =====` 之前

**Interfaces:**
- Consumes: `nearestTeacherIdx(tea, t) -> number`（Task 1）；`stu` 形如 `[{t, pitch, rms}, ...]`，`tea` 形如 `[{t, pitch}, ...]`，`mapping` 是 `Number[]` 且 `mapping[j]` = 乐谱第 `j` 点对应的学生下标，`lyrics` 形如 `[{char, pitch, start, duration}, ...]`（`pitch`/`start`/`duration` 均可为 `null`）
- Produces: `wordDurationByMapping(stu, tea, mapping, lyrics) -> { items }`，`items` 是 `{index, actual, expected, diff}[]`（`index` = 字在 `lyrics` 中的下标，`actual`/`expected`/`diff` 单位均为秒）。**没有 `median` 字段**——卡片只要最近一个字，不需要中位数。

- [ ] **Step 1: 写失败的测试**

`ALGO_NAMES` 追加 `"wordDurationByMapping"`（放在 `"nearestTeacherIdx"` 后面）：

```js
const ALGO_NAMES = [
  "dtwAlign", "rhythmMetrics", "wordDeviations", "breathMetrics",
  "logistic", "thinTeacher", "nearestTeacherIdx", "wordDurationByMapping",
];
```

在 `// ===== 汇总 =====` 之前插入：

```js
// ===== wordDurationByMapping（实时卡片主数：逐字时值偏差）=====
console.log("\nwordDurationByMapping");

// 走与页面相同的顺序：乐谱采样 → 抽稀 → 对齐 → 读时值
function durations(lyrics, stu) {
  const tea = algo.thinTeacher(teacherFromLyrics(lyrics), stu.length, 4e6);
  const mapping = algo.dtwAlign(stu, tea, { bandSec: 3 });
  return algo.wordDurationByMapping(stu, tea, mapping, lyrics);
}

// 把「二」（乐谱 0.5–1.0s，长 0.5s）拉成学生时间 0.5–1.4s（长 0.9s），其余照旧：
// 学生时间轴 → 乐谱位置的分段映射
function stretchedScoreAt(t) {
  if (t < 0.5) return t;
  if (t < 1.4) return 0.5 + (t - 0.5) * (0.5 / 0.9);
  return 1.0 + (t - 1.4);
}
function singStretched(dt, dur) {
  const pts = [];
  for (let t = 0; t <= dur; t += dt) {
    const s = stretchedScoreAt(t);
    for (const ly of LYRICS) {
      if (s >= ly.start && s < ly.start + ly.duration) { pts.push({ t, pitch: ly.pitch, rms: 0.15 }); break; }
    }
  }
  return pts;
}

test("准时唱：每个字的时值偏差都接近 0", () => {
  isFn(algo.wordDurationByMapping, "wordDurationByMapping");
  const r = durations(LYRICS, singAlong(LYRICS, 1.0, 0.01, 0.15));
  assert(r.items.length === 3, `应给出 3 个字，实际 ${r.items.length}`);
  for (const it of r.items) {
    close(it.expected, 0.5, 1e-9, `第 ${it.index} 个字的乐谱时值`);
    assert(Math.abs(it.diff) < 0.05, `第 ${it.index} 个字时值偏差 ${it.diff}，应接近 0`);
  }
});

test("整段晚 0.5s 起唱：时值偏差仍接近 0（整体偏移不算进时值）", () => {
  isFn(algo.wordDurationByMapping, "wordDurationByMapping");
  const stu = singAlong(LYRICS, 1.0, 0.01, 0.15).map(p => ({ t: p.t + 0.5, pitch: p.pitch, rms: p.rms }));
  const r = durations(LYRICS, stu);
  assert(r.items.length === 3, `应给出 3 个字，实际 ${r.items.length}`);
  for (const it of r.items) {
    assert(
      Math.abs(it.diff) < 0.06,
      `第 ${it.index} 个字时值偏差 ${it.diff}——整体晚起唱不该记进时值（这是本口径的验收点）`
    );
  }
});

test("拖长某个字：该字偏差明显为正，前面的字不被牵连", () => {
  isFn(algo.wordDurationByMapping, "wordDurationByMapping");
  const r = durations(LYRICS, singStretched(0.01, 1.9));
  const byIdx = {};
  for (const it of r.items) byIdx[it.index] = it;
  assert(byIdx[1], `第 2 个字应能算出时值，实际只有 ${r.items.map(it => it.index).join(",")}`);
  assert(byIdx[1].diff > 0.3, `第 2 个字拉长 0.4s，应报明显偏长，实际 ${byIdx[1].diff}`);
  if (byIdx[0]) {
    assert(Math.abs(byIdx[0].diff) < 0.08, `第 1 个字不该被牵连，实际 ${byIdx[0].diff}`);
  }
});

test("整段慢一成：每个字的偏差都约为 +0.05s", () => {
  isFn(algo.wordDurationByMapping, "wordDurationByMapping");
  const r = durations(LYRICS, singAlong(LYRICS, 1.1, 0.01, 0.15));
  assert(r.items.length === 3, `应给出 3 个字，实际 ${r.items.length}`);
  for (const it of r.items) {
    close(it.diff, it.expected * 0.1, 0.03, `第 ${it.index} 个字的时值偏差`);
  }
});

test("标点与字段不全的字不进明细", () => {
  isFn(algo.wordDurationByMapping, "wordDurationByMapping");
  const lyrics = LYRICS.concat([
    { char: "，", pitch: null, start: 1.5, duration: null },
    { char: "四", pitch: 69, start: null, duration: 0.5 },
  ]);
  const r = durations(lyrics, singAlong(LYRICS, 1.0, 0.01, 0.15));
  assert(r.items.length === 3, `应只有 3 条，实际 ${r.items.length}`);
});

test("空歌词或空映射：返回空明细，不崩", () => {
  isFn(algo.wordDurationByMapping, "wordDurationByMapping");
  const tea = teacherFromLyrics(LYRICS);
  const one = [{ t: 0, pitch: 60, rms: 0.15 }];
  assert(algo.wordDurationByMapping(one, tea, [0], []).items.length === 0, "空歌词应返回空明细");
  assert(algo.wordDurationByMapping(one, tea, [], LYRICS).items.length === 0, "空映射应返回空明细");
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `node scripts/test_sing_along_algo.js`
Expected: FAIL —— 6 条新断言全部报 `wordDurationByMapping 未定义`，末尾 `✗ 6 个失败，22 个通过`

- [ ] **Step 3: 实现**

在 `sing_along.html` 算法段内，紧接 `wordDeviations` 的结束大括号之后（即 `breathMetrics` 上方注释块之前）插入：

```js
// 逐字时值偏差（PRD 2.9 的实时卡片口径）：每个字实际占用了多久，从 DTW 映射上读。
// 本字的乐谱终点由 start + duration 直接给出，不引用下一个字——对最后一个字同样成立。
// 与 wordDeviations 同源同映射，区别只在读的是「间隔」还是「起点」。
function wordDurationByMapping(stu, tea, mapping, lyrics) {
  const items = [];
  if (!lyrics || lyrics.length === 0 || !mapping || mapping.length === 0) return { items };
  for (let k = 0; k < lyrics.length; k++) {
    const ly = lyrics[k];
    // 标点没有音高，也就没有乐谱曲线上的落点，跳过
    if (ly.pitch === null || !Number.isFinite(ly.pitch)) continue;
    if (!Number.isFinite(ly.start) || !Number.isFinite(ly.duration)) continue;
    const jFrom = nearestTeacherIdx(tea, ly.start);
    const jTo = nearestTeacherIdx(tea, ly.start + ly.duration);
    // jTo <= jFrom 说明映射在这一段不单调，这个字不出数
    if (jFrom < 0 || jTo < 0 || jTo <= jFrom) continue;
    if (jFrom >= mapping.length || jTo >= mapping.length) continue;
    const actual = stu[mapping[jTo]].t - stu[mapping[jFrom]].t;
    items.push({ index: k, actual, expected: ly.duration, diff: actual - ly.duration });
  }
  return { items };
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `node scripts/test_sing_along_algo.js`
Expected: PASS —— `✓ 28 个全部通过`

- [ ] **Step 5: 提交**

```bash
git add sing_along.html scripts/test_sing_along_algo.js
git commit -m "feat: 算法段新增 wordDurationByMapping（逐字时值偏差）"
```

---

### Task 3: `breathScoreFromCv`：稳定度式子去重

**Files:**
- Modify: `sing_along.html` 算法段内（插在 `breathMetrics` 之后，当前 `:1607` 附近）
- Modify: `sing_along.html:1693`（停录后流程里手写的那一遍式子）
- Modify: `scripts/test_sing_along_algo.js:17-20`、`:346`（`runPipeline`）、`// ===== 汇总 =====` 之前

**Interfaces:**
- Consumes: `breathMetrics(stu) -> { cv, tailRatio, sustainCount }`（既有），其中 `cv` 是 `number | null`
- Produces: `breathScoreFromCv(cv) -> number | null` —— `cv` 为 `null` 或非有限数时返回 `null`，否则返回 `0–100` 的整数（`cv` 大于 1 时钳在 0）。Task 4 与停录后流程都调它。

- [ ] **Step 1: 写失败的测试**

`ALGO_NAMES` 追加 `"breathScoreFromCv"`：

```js
const ALGO_NAMES = [
  "dtwAlign", "rhythmMetrics", "wordDeviations", "breathMetrics",
  "logistic", "thinTeacher", "nearestTeacherIdx", "wordDurationByMapping",
  "breathScoreFromCv",
];
```

把 `runPipeline`（`:336-355`）里那行手写的式子改成调算法段的函数——测试脚本模拟的必须是页面真正走的那个函数，而不是一个复制品：

```js
    breathScore: algo.breathScoreFromCv(breath.cv),
```

在 `// ===== 汇总 =====` 之前插入：

```js
// ===== breathScoreFromCv（实时卡片与停录后面板共用的稳定度式子）=====
console.log("\nbreathScoreFromCv");

test("cv 为 0：满稳 100", () => {
  isFn(algo.breathScoreFromCv, "breathScoreFromCv");
  assert(algo.breathScoreFromCv(0) === 100, `实际 ${algo.breathScoreFromCv(0)}`);
});
test("cv 为 0.15：报 85（就是 1 − 0.15）", () => {
  isFn(algo.breathScoreFromCv, "breathScoreFromCv");
  assert(algo.breathScoreFromCv(0.15) === 85, `实际 ${algo.breathScoreFromCv(0.15)}`);
});
test("cv 为 1：报 0，不报负数", () => {
  isFn(algo.breathScoreFromCv, "breathScoreFromCv");
  assert(algo.breathScoreFromCv(1) === 0, `实际 ${algo.breathScoreFromCv(1)}`);
});
test("cv 超过 1：仍钳在 0", () => {
  isFn(algo.breathScoreFromCv, "breathScoreFromCv");
  assert(algo.breathScoreFromCv(1.5) === 0, `实际 ${algo.breathScoreFromCv(1.5)}`);
});
test("cv 为 null / NaN：返回 null（页面显示「待分析」，不装满分）", () => {
  isFn(algo.breathScoreFromCv, "breathScoreFromCv");
  assert(algo.breathScoreFromCv(null) === null, `null 应返回 null，实际 ${algo.breathScoreFromCv(null)}`);
  assert(algo.breathScoreFromCv(NaN) === null, `NaN 应返回 null，实际 ${algo.breathScoreFromCv(NaN)}`);
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `node scripts/test_sing_along_algo.js`
Expected: FAIL —— 5 条新断言报 `breathScoreFromCv 未定义`，末尾 `✗ 5 个失败，28 个通过`

- [ ] **Step 3: 实现**

在 `sing_along.html` 算法段内，紧接 `breathMetrics` 的结束大括号之后插入：

```js
// 气息稳定度 = 1 − 长音段能量变异系数，取整并钳在 0–100。
// 实时卡片与停录后的维度面板共用这一个式子——两处的「气息」数字在数学上不可能漂移。
// cv 为 null（全段没有 ≥0.4s 的平稳音）时返回 null，由调用方显示「待分析」而不是假装满分。
function breathScoreFromCv(cv) {
  if (cv === null || !Number.isFinite(cv)) return null;
  return Math.max(0, Math.round((1 - Math.min(1, cv)) * 100));
}
```

再把停录后流程里的这一行（本计划写下时在 `:1693`，Task 1/2 的插入会让它下移约 25 行，**按原文找**）：

```js
  const breathScore = breath.cv === null ? null : Math.max(0, Math.round((1 - Math.min(1, breath.cv)) * 100));
```

换成：

```js
  const breathScore = breathScoreFromCv(breath.cv);
```

- [ ] **Step 4: 跑测试确认通过**

Run: `node scripts/test_sing_along_algo.js`
Expected: PASS —— `✓ 33 个全部通过`。既有端到端两条断言（`:350` 起）仍须通过，它们现在走的是 `algo.breathScoreFromCv`。

- [ ] **Step 5: 提交**

```bash
git add sing_along.html scripts/test_sing_along_algo.js
git commit -m "refactor: 稳定度式子提成 breathScoreFromCv，实时与停录后共用"
```

---

### Task 4: 实时薄壳接线：删假值、两张卡出真数

**Files:**
- Modify: `sing_along.html:664` 附近（顶部调度常量区）
- Modify: `sing_along.html:1332`（`updateMetrics` 上方，插显示常量）
- Modify: `sing_along.html:1354-1395`（**删除**查表假值段，含两个 `val` / `trend` / `card` 的写入）
- Modify: `sing_along.html:1396` 之后（插入实时薄壳全部函数）
- Modify: `sing_along.html:1324-1328`（`recordLoop` 尾部加节流调用）
- Modify: `sing_along.html:1273` 附近（`toggleRecord` 加卡片初始化）
- Modify: `sing_along.html:1842` 附近（`stopAll` 加缓存清理）
- Modify: `scripts/test_sing_along_algo.js` `// ===== 汇总 =====` 之前

**Interfaces:**
- Consumes: `nearestTeacherIdx`、`wordDurationByMapping`、`breathScoreFromCv`（Task 1–3）；`thinTeacher(pts, stuCount, maxCells)`、`dtwAlign(stu, tea, {bandSec})`、`rhythmMetrics(stu, tea, mapping) -> {warpStd, tempo, offset}`、`wordDeviations(stu, tea, mapping, lyrics) -> {items, median}`、`breathMetrics(stu) -> {cv, tailRatio, sustainCount}`（均既有）
- Produces: `startLiveCards()`、`updateLiveMetrics()`（无入参、无返回值）。页面级副作用：`#valRhythm` / `#trendRhythm` / `#cardRhythm` / `#valBreath` / `#trendBreath` / `#cardBreath` 在录音中被真实读数写入。

- [ ] **Step 1: 写失败的测试（端到端实时链路）**

在 `// ===== 汇总 =====` 之前插入：

```js
// ===== 端到端（实时）：按 updateLiveMetrics 里的调用顺序串一遍 =====
console.log("\n端到端（实时卡片）");

test("整段拖慢一成：门限放行、逐字时值偏长、气息稳定度不为 null", () => {
  const lyrics = LYRICS;
  const stu = singAlong(lyrics, 1.1, 0.01, 0.15);
  const tea = algo.thinTeacher(teacherFromLyrics(lyrics), stu.length, 4e6);
  const mapping = algo.dtwAlign(stu, tea, { bandSec: 3 });
  const tempo = algo.rhythmMetrics(stu, tea, mapping).tempo;
  assert(tempo >= 0.5 && tempo <= 2, `可信度门限应放行，实际 tempo=${tempo}`);

  const durs = algo.wordDurationByMapping(stu, tea, mapping, lyrics).items;
  assert(durs.length > 0, "应至少给出一个字的时值");
  for (const it of durs) {
    assert(it.diff > 0, `第 ${it.index} 个字应报偏长，实际 ${it.diff}`);
  }

  const score = algo.breathScoreFromCv(algo.breathMetrics(stu).cv);
  assert(score !== null, "匀速长音应给出稳定度，不该是 null");
  assert(score > 80, `匀速长音的稳定度应偏高，实际 ${score}`);
});
```

- [ ] **Step 2: 跑测试确认先通过**

Run: `node scripts/test_sing_along_algo.js`
Expected: PASS —— `✓ 34 个全部通过`。这一步的断言只用到 Task 1–3 已交付的纯函数，所以它**应当直接通过**；这一条是纯算法侧的实时链路验收，DOM 接线由 Step 7 的人工验证覆盖。

- [ ] **Step 3: 加三个常数**

在 `sing_along.html` 顶部 `const TOLERANCE_CENTS = 30;`（`:665`）之后加一行：

```js
const LIVE_CALC_INTERVAL_MS = 500; // 实时节奏/气息的重算节流：两张卡都「完成才定格」，粒度不影响正确性
```

在 `function updateMetrics(elapsed, seg, widx) {`（`:1333`）**之前**插入：

```js
// 实时「节奏偏差」的配色阈值（秒）：配的是逐字时值偏差，与音准那套音分阈值无关。
// 0.10s 约当一个十六分音符的容差量级；未经真实素材标定，调参改这两行即可。
const DEV_GOOD_SEC = 0.10;
const DEV_WARN_SEC = 0.25;
```

- [ ] **Step 4: 删掉查表假值段**

删除 `sing_along.html` 的 `:1354-1395` —— 从 `  let rhythmOffset = 0;` 起，到 `  document.getElementById("cardBreath").className = ...` 那一行为止（含中间的三段 `if (widx === ...)` 分支）。删完后 `updateMetrics` 只剩音准那一半，函数以 `document.getElementById("trendPitch").style.color = ...` 那行之后的大括号收尾。

**注意**：删的是**整段 42 行**，`updateMetrics` 的签名 `(elapsed, seg, widx)` 与调用点 `:1324` 都不动（`elapsed`/`widx` 仍被音准那半用到）。

- [ ] **Step 5: 加实时薄壳**

紧接 `updateMetrics` 的结束大括号之后（即 `function updateProgress(elapsed) {` 之前）插入：

```js
// ===== 实时节奏/气息（薄壳：只做调度与 DOM，算术全在「纯算法」段）=====
// 每 LIVE_CALC_INTERVAL_MS 对已累积的落点重跑一次对齐，逐字时值偏差进节奏卡、
// 长音段能量变异系数进气息卡。单次约 20 万格 DTW，见 spec §11 的代价登记。
let lastLiveCalcAt = -Infinity;  // 上次重算的 rAF 时间戳
let lastRhythmKey = null;        // 上次落地的节奏读数（日志去重：同一个字会被反复结算出同一个值）
let lastBreathKey = null;        // 上次落地的气息读数

// 开始录音时把两张卡拨回等待态（停录后的重置在 stopAll 里，措辞是「等待开始…」）
function startLiveCards() {
  lastLiveCalcAt = -Infinity;
  lastRhythmKey = null;
  lastBreathKey = null;
  document.getElementById("valRhythm").textContent = "--";
  document.getElementById("valRhythm").style.color = "#C9A84C";
  document.getElementById("trendRhythm").textContent = "等待起唱…";
  document.getElementById("trendRhythm").style.color = "#8A7A6A";
  document.getElementById("cardRhythm").className = "metric-card";
  document.getElementById("valBreath").textContent = "--";
  document.getElementById("valBreath").style.color = "#4A8F6B";
  document.getElementById("trendBreath").textContent = "等待长音…";
  document.getElementById("trendBreath").style.color = "#8A7A6A";
  document.getElementById("cardBreath").className = "metric-card";
}

// 取 index ≤ maxIdx 中最靠后的一个读数；一个都没有、或最近那个也太陈（超过 back 个字）→ null。
// 回溯上限就是「不回溯超过 3 个字」这条容错规则，免得卡片停在很陈的读数上。
function latestItem(items, maxIdx, back) {
  let best = null;
  for (const it of items) {
    if (it.index > maxIdx || maxIdx - it.index > back) continue;
    if (!best || it.index > best.index) best = it;
  }
  return best;
}

function updateLiveMetrics() {
  const lyrics = currentLyrics;
  if (!lyrics.length || teacherPoints.length < 2) return;
  const stu = studentPoints;
  if (stu.length < 2) return;

  const tea = thinTeacher(teacherPoints, stu.length, DTW_MAX_CELLS);
  const mapping = dtwAlign(stu, tea, { bandSec: RHYTHM_BAND_SEC });
  if (!mapping.length) return;
  // 可信度门限：与停录后的维度面板同一个判据（tempo 越界就整轮不出数、不写日志）
  const tempo = rhythmMetrics(stu, tea, mapping).tempo;
  if (!(tempo >= 0.5 && tempo <= 2)) return;

  // 节奏：取最近一个已唱完的字（当前字还在唱，不出数）
  const durs = wordDurationByMapping(stu, tea, mapping, lyrics).items;
  const dur = latestItem(durs, currentWordIndex - 1, 3);
  if (dur) {
    const starts = wordDeviations(stu, tea, mapping, lyrics).items;
    applyRhythmCard(dur, starts.find(it => it.index === dur.index) || null);
  }

  // 气息：breathMetrics 只统计已完成的长音段，天然就是「长音唱完才定格」
  const breath = breathMetrics(stu);
  const score = breathScoreFromCv(breath.cv);
  if (score !== null) applyBreathCard(score, breath.cv, breath.sustainCount);
}

function applyRhythmCard(dur, start) {
  const diff = dur.diff;
  const abs = Math.abs(diff);
  const color = abs <= DEV_GOOD_SEC ? "#4A8F6B" : abs <= DEV_WARN_SEC ? "#C9A84C" : "#B83A2F";
  const cls = abs <= DEV_GOOD_SEC ? "success" : abs <= DEV_WARN_SEC ? "warn" : "danger";
  const shown = (diff >= 0 ? "+" : "-") + Math.abs(diff).toFixed(2) + "s";

  document.getElementById("valRhythm").textContent = shown;
  document.getElementById("valRhythm").style.color = color;
  document.getElementById("trendRhythm").textContent =
    abs <= DEV_GOOD_SEC ? "✓ 时值准确" : diff > 0 ? "↗ 时值偏长" : "↘ 时值偏短";
  document.getElementById("trendRhythm").style.color = color;
  document.getElementById("cardRhythm").className = `metric-card ${cls}`;

  const key = `${dur.index}:${shown}`;
  if (key !== lastRhythmKey) {
    lastRhythmKey = key;
    const s = start ? ` · 起唱 ${start.diff >= 0 ? "+" : "-"}${Math.abs(start.diff).toFixed(2)}s` : "";
    addLog(`节奏：时值 ${shown}${s}`, "info");
  }
}

function applyBreathCard(score, cv, sustainCount) {
  const color = score >= 80 ? "#4A8F6B" : score >= 70 ? "#C9A84C" : "#B83A2F";
  const cls = score >= 80 ? "success" : score >= 70 ? "warn" : "danger";

  document.getElementById("valBreath").textContent = score + "%";
  document.getElementById("valBreath").style.color = color;
  document.getElementById("trendBreath").textContent = score >= 80 ? "✓ 气息稳定" : "⚠ 气息波动";
  document.getElementById("trendBreath").style.color = color;
  document.getElementById("cardBreath").className = `metric-card ${cls}`;

  const key = `${score}:${sustainCount}`;
  if (key !== lastBreathKey) {
    lastBreathKey = key;
    addLog(`气息：稳定度 ${score}% · 能量波动 ${Math.round(cv * 100)}% · 长音 ${sustainCount} 段`, "info");
  }
}
```

- [ ] **Step 6: 三处调用点接线**

**(a)** `recordLoop` 尾部，在 `  if (isRecording) requestAnimationFrame(recordLoop);` 这一行**之前**插入：

```js
  // 实时节奏/气息：节流重算（两张卡都是「完成才定格」，粒度不影响正确性）
  if (now - lastLiveCalcAt >= LIVE_CALC_INTERVAL_MS) {
    lastLiveCalcAt = now;
    updateLiveMetrics();
  }

```

**(b)** `toggleRecord` 里，把

```js
  studentPoints = [];
  currentWordIndex = -1;
  document.getElementById("btnRecord").style.display = "none";
```

改成

```js
  studentPoints = [];
  currentWordIndex = -1;
  startLiveCards();
  document.getElementById("btnRecord").style.display = "none";
```

**(c)** `stopAll` 里，在 `  document.getElementById("cardBreath").className = "metric-card";` 这一行之后、`  drawTimeline();` 之前插入：

```js
  // 清掉实时读数的节流时间戳与去重缓存，下次录音从头来
  lastLiveCalcAt = -Infinity;
  lastRhythmKey = null;
  lastBreathKey = null;
```

- [ ] **Step 7: 跑测试 + 人工验证**

Run: `node scripts/test_sing_along_algo.js`
Expected: PASS —— `✓ 34 个全部通过`

人工验证（页面行为改在这一步，测试脚本覆盖不到）：

1. 起服务。若 8877 已被 PyCharm 调试会话占着（这是常态），**不要杀它**——那个实例的 reloader 会自动加载本次改动，直接访问即可；否则按 CLAUDE.md 起 Flask。
2. 用 HTTP 访问 `/sing_along.html`（`file://` 打不开，页面受登录保护），登录 `stu001` / `xiyun@2026`。
3. 打开浏览器控制台，确认**没有 JS 报错**。
4. 选一个练习段落，点录音。逐项确认：
   - 点录音那一刻，两张卡变 `--` + `等待起唱…` / `等待长音…`（不是 `等待开始…`）。
   - 跟着唱，节奏卡在**第一个字唱完之后**才出数（形如 `+0.07s`），趋势文案是 `✓ 时值准确` / `↗ 时值偏长` / `↘ 时值偏短`，不再是「↗ 偏慢」。
   - 日志里出现 `节奏：时值 +0.07s · 起唱 +0.02s`，且**同一个字反复重算不会重复刷同一条日志**。
   - 唱到一个 0.4s 以上的平稳长音并唱完，气息卡出 `85%` 这样的整数，日志出现 `气息：稳定度 85% · 能量波动 15% · 长音 1 段`。
   - 故意拖长一个字，节奏读数变正；故意整段晚一点起唱，节奏读数**不大幅变化**而日志里的起唱偏差明显为正（这是本口径的验收点）。
   - 录音中观察是否掉帧/卡顿（spec §11 第 2 条的代价）。若明显卡顿，把 `LIVE_CALC_INTERVAL_MS` 放宽到 800–1000 再测。
   - 点停止，两张卡回到 `--` + `等待开始…`。
5. **若无麦克风可测**：如实报告"人工验证未做"，只保留第 3 步的控制台无报错结论，不要写成"已验证"。

- [ ] **Step 8: 提交**

```bash
git add sing_along.html scripts/test_sing_along_algo.js
git commit -m "feat: 实时跟唱页的节奏偏差与气息稳定性改用真实录音数据计算"
```

---

## 收尾（全部任务完成后）

- [ ] 更新 `docs/superpowers/specs/2026-10-10-sing-along-live-metrics-design.md` 的状态行：`已评审待实现` → `已实现`。
- [ ] 检查 `DOC_ISSUES.md` 第 41 条是否需要补一句「已实现」；该条已登记的口径与代价在实现后仍成立，不改结论。
- [ ] 若 Step 7 实测掉帧并调整了 `LIVE_CALC_INTERVAL_MS`，把实际值与采用的理由补进 spec §11 第 2 条，并在 `DOC_ISSUES.md` 第 41 条同步。
