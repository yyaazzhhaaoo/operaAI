#!/usr/bin/env node
// sing_along.html「纯算法」段的断言测试。
//
// 页面是单文件自包含原型，没有构建步骤也没有测试框架，所以这里不复制一份
// 实现来测——那迟早会与页面漂移。做法是从 sing_along.html 里把标记之间的
// 那段纯函数抽出来，在 Node 的 vm 里执行，测的就是浏览器里真正跑的那段码。
//
// 跑法：node scripts/test_sing_along_algo.js
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const HTML = path.join(__dirname, "..", "sing_along.html");
const BEGIN = "// ===== BEGIN 纯算法";
const END = "// ===== END 纯算法";
// 算法段应当导出的函数名；写测试时先加名字，实现后自然出现在导出里
const ALGO_NAMES = [
  "dtwAlign", "rhythmMetrics", "wordDeviations", "breathMetrics",
  "logistic", "thinTeacher", "nearestTeacherIdx", "wordDurationByMapping",
  "breathScoreFromCv",
];

function loadAlgo() {
  const src = fs.readFileSync(HTML, "utf8");
  const a = src.indexOf(BEGIN);
  const b = src.indexOf(END);
  if (a < 0 || b < 0) {
    console.log("⚠  没找到「纯算法」段标记，本次全部按未实现处理");
    return vm.runInNewContext("({})");
  }
  // 标记行结尾还有个 " ====="，从该行的换行符之后开始切
  const code = src.slice(src.indexOf("\n", a) + 1, b);
  // 逐个探测名字：还没实现的函数给 undefined，让断言以「未定义」失败，
  // 而不是让整段抽取崩在一个 ReferenceError 上（那样看不出是哪个函数缺）。
  const probe = ALGO_NAMES.map(
    n => `typeof ${n} === "function" ? {${n}} : {}`
  ).join(", ");
  // 只给 Math，页面里的 DOM/音频句柄一律拿不到——算法段必须保持纯函数，
  // 一旦有人往里塞了 document.xxx，这里会当场抛错而不是悄悄通过。
  return vm.runInNewContext(code + `\n;Object.assign({}, ${probe})`, { Math });
}

// ===== 断言小工具 =====
let passed = 0;
const failures = [];
function test(name, fn) {
  try {
    fn();
    passed++;
    console.log("  ✓ " + name);
  } catch (e) {
    failures.push(name);
    console.log("  ✗ " + name + "\n      " + e.message);
  }
}
function assert(cond, msg) {
  if (!cond) throw new Error(msg || "断言失败");
}
function close(actual, expected, tol, what) {
  assert(
    Number.isFinite(actual) && Math.abs(actual - expected) <= tol,
    `${what}: 期望 ${expected} ±${tol}，实际 ${actual}`
  );
}
function isFn(v, name) {
  assert(typeof v === "function", `${name} 未定义——算法段里还没有这个函数`);
}

// ===== 合成数据 =====
// 一段三小节的乐谱：0–1s 唱 C4，1–2s 唱 E4，2–3s 唱 G4
function melody(t) {
  if (t < 1) return 60;
  if (t < 2) return 64;
  return 67;
}
// 教师侧：与页面 prepareTeacherCurve 同构，20ms 均匀采样
function makeTeacher(dur, dt) {
  const pts = [];
  for (let t = 0; t <= dur; t += dt) pts.push({ t, pitch: melody(t) });
  return pts;
}
// 学生侧：33Hz 采样。speed=1.1 表示同样内容唱了 1.1 倍时间（拖拍）
function makeStudent(dur, dt, speed) {
  const pts = [];
  for (let t = 0; t <= dur * speed; t += dt) pts.push({ t, pitch: melody(t / speed) });
  return pts;
}

// ===== dtwAlign =====
console.log("\ndtwAlign");
const algo = loadAlgo();

test("映射长度等于乐谱点数，且值为合法的学生下标", () => {
  isFn(algo.dtwAlign, "dtwAlign");
  const tea = makeTeacher(3, 0.02);
  const stu = makeStudent(3, 0.03, 1.0);
  const m = algo.dtwAlign(stu, tea, { bandSec: 3 });
  assert(m.length === tea.length, `长度应为 ${tea.length}，实际 ${m.length}`);
  assert(
    m.every(i => Number.isInteger(i) && i >= 0 && i < stu.length),
    "存在越界或非整数的学生下标"
  );
});

test("两条一模一样的曲线映射成对角（j → j）", () => {
  isFn(algo.dtwAlign, "dtwAlign");
  const tea = makeTeacher(3, 0.02);
  const stu = makeTeacher(3, 0.02);
  const m = algo.dtwAlign(stu, tea, { bandSec: 3 });
  for (let j = 0; j < tea.length; j++) {
    assert(Math.abs(m[j] - j) <= 1, `第 ${j} 个乐谱点映射到了 ${m[j]}，应约等于 ${j}`);
  }
});

test("学生慢 10% 时，映射点与乐谱点的时间比约为 1.1", () => {
  isFn(algo.dtwAlign, "dtwAlign");
  const tea = makeTeacher(3, 0.02);
  const stu = makeStudent(3, 0.03, 1.1);
  const m = algo.dtwAlign(stu, tea, { bandSec: 3 });
  const ratio = stu[m[m.length - 1]].t / tea[tea.length - 1].t;
  close(ratio, 1.1, 0.05, "末点时间比");
});

// ===== rhythmMetrics =====
console.log("\nrhythmMetrics");

test("两条一致：抖动为 0、速度比为 1、整体无偏移", () => {
  isFn(algo.rhythmMetrics, "rhythmMetrics");
  const tea = makeTeacher(3, 0.02);
  const stu = makeTeacher(3, 0.03);
  const m = algo.dtwAlign(stu, tea, { bandSec: 3 });
  const r = algo.rhythmMetrics(stu, tea, m);
  // 抖动不可能真的为 0：映射落在离散的学生帧上，量化下限就是半个帧长（30ms 采样
  // → 约 8.7ms）。契约是「不超过半个帧」，不是「等于 0」。
  assert(r.warpStd < 0.02, `抖动应接近 0（≤ 半个学生帧），实际 ${r.warpStd}`);
  close(r.tempo, 1, 0.02, "速度比");
  close(r.offset, 0, 0.02, "整体偏移");
});

test("整体晚起唱 0.5s：偏移报 0.5，但抖动仍为 0、速度比仍为 1", () => {
  isFn(algo.rhythmMetrics, "rhythmMetrics");
  const tea = makeTeacher(3, 0.02);
  const dt = 0.03;
  const stu = [];
  for (let t = 0; t <= 3; t += dt) stu.push({ t: t + 0.5, pitch: melody(t) });
  const m = algo.dtwAlign(stu, tea, { bandSec: 3 });
  const r = algo.rhythmMetrics(stu, tea, m);
  close(r.offset, 0.5, 0.03, "整体偏移");
  close(r.tempo, 1, 0.02, "速度比");
  close(r.warpStd, 0, 0.02, "抖动");
});

test("慢 10%：速度比约 1.1，抖动大于 0.05", () => {
  isFn(algo.rhythmMetrics, "rhythmMetrics");
  const tea = makeTeacher(3, 0.02);
  const stu = makeStudent(3, 0.03, 1.1);
  const m = algo.dtwAlign(stu, tea, { bandSec: 3 });
  const r = algo.rhythmMetrics(stu, tea, m);
  close(r.tempo, 1.1, 0.03, "速度比");
  assert(r.warpStd > 0.05, `抖动应明显大于 0，实际 ${r.warpStd}`);
});

// ===== wordDeviations =====
console.log("\nwordDeviations");
// 逐字歌词：三个字，各 0.5s（与页面 lyrics_json 的字段同构）
const LYRICS = [
  { char: "一", pitch: 60, start: 0.0, duration: 0.5 },
  { char: "二", pitch: 64, start: 0.5, duration: 0.5 },
  { char: "三", pitch: 67, start: 1.0, duration: 0.5 },
];

test("准时起唱：每个字的偏差都接近 0，且给出中位数", () => {
  isFn(algo.wordDeviations, "wordDeviations");
  const tea = makeTeacher(3, 0.02);
  const stu = makeStudent(3, 0.03, 1.0);
  const m = algo.dtwAlign(stu, tea, { bandSec: 3 });
  const r = algo.wordDeviations(stu, tea, m, LYRICS);
  assert(r.items.length === 3, `应给出 3 个字，实际 ${r.items.length}`);
  for (const it of r.items) {
    assert(Math.abs(it.diff) < 0.05, `第 ${it.index} 个字偏差 ${it.diff}，应接近 0`);
  }
  assert(Math.abs(r.median) < 0.05, `中位数 ${r.median} 应接近 0`);
});

test("整体晚 0.5s 起唱：每个字的偏差都约为 +0.5", () => {
  isFn(algo.wordDeviations, "wordDeviations");
  const tea = makeTeacher(3, 0.02);
  const dt = 0.03;
  const stu = [];
  for (let t = 0; t <= 3; t += dt) stu.push({ t: t + 0.5, pitch: melody(t) });
  const m = algo.dtwAlign(stu, tea, { bandSec: 3 });
  const r = algo.wordDeviations(stu, tea, m, LYRICS);
  for (const it of r.items) {
    close(it.diff, 0.5, 0.05, `第 ${it.index} 个字的偏差`);
  }
});

test("没有音高的标点不进明细", () => {
  isFn(algo.wordDeviations, "wordDeviations");
  const tea = makeTeacher(3, 0.02);
  const stu = makeStudent(3, 0.03, 1.0);
  const m = algo.dtwAlign(stu, tea, { bandSec: 3 });
  const lyrics = LYRICS.concat([{ char: "，", pitch: null, start: 1.5, duration: null }]);
  const r = algo.wordDeviations(stu, tea, m, lyrics);
  assert(r.items.length === 3, `标点应被跳过，实际给出 ${r.items.length} 条`);
});

// ===== breathMetrics =====
console.log("\nbreathMetrics");
// 学生轨迹（带能量）：pitchFn/rmsFn 给什么就是什么
function makeRmsStu(dt, dur, rmsFn, pitchFn) {
  const pts = [];
  for (let t = 0; t <= dur; t += dt) pts.push({ t, pitch: pitchFn(t), rms: rmsFn(t) });
  return pts;
}

test("匀速长音：变异系数为 0，且数出一个长音段", () => {
  isFn(algo.breathMetrics, "breathMetrics");
  const stu = makeRmsStu(0.03, 1.2, () => 0.1, () => 60);
  const r = algo.breathMetrics(stu);
  assert(r.sustainCount === 1, `长音段数应为 1，实际 ${r.sustainCount}`);
  close(r.cv, 0, 0.01, "变异系数");
});

test("忽大忽小的长音：变异系数明显大于 0", () => {
  isFn(algo.breathMetrics, "breathMetrics");
  const stu = makeRmsStu(0.03, 1.2, t => (Math.round(t / 0.12) % 2 ? 0.20 : 0.05), () => 60);
  const r = algo.breathMetrics(stu);
  assert(r.cv > 0.3, `变异系数应明显大于 0，实际 ${r.cv}`);
});

test("短于 0.4s 的段不算长音", () => {
  isFn(algo.breathMetrics, "breathMetrics");
  const stu = makeRmsStu(0.03, 0.3, () => 0.1, () => 60);
  const r = algo.breathMetrics(stu);
  assert(r.sustainCount === 0, `不应数出长音段，实际 ${r.sustainCount}`);
  assert(r.cv === null, `没有长音段时变异系数应为 null，实际 ${r.cv}`);
});

test("句尾越唱越弱：尾首能量比小于 1", () => {
  isFn(algo.breathMetrics, "breathMetrics");
  // 一句 1s，能量从 0.1 线性衰减到 0.05
  const stu = makeRmsStu(0.03, 1.0, t => 0.1 - 0.05 * t, () => 60);
  const r = algo.breathMetrics(stu);
  close(r.tailRatio, 0.61, 0.05, "尾首能量比");
});

test("开头一段底噪被判为没在唱，不拉低长音稳定度", () => {
  isFn(algo.breathMetrics, "breathMetrics");
  const pts = [];
  for (let t = 0; t <= 0.3; t += 0.03) pts.push({ t, pitch: 60, rms: 0.002 });   // 底噪
  for (let t = 0.33; t <= 1.2; t += 0.03) pts.push({ t, pitch: 60, rms: 0.2 });  // 真唱
  const r = algo.breathMetrics(pts);
  assert(r.sustainCount === 1, `应只数出真唱那一段，实际 ${r.sustainCount}`);
  assert(r.cv < 0.05, `底噪不该拉高能量波动，实际 ${r.cv}`);
});

test("中间换气：断成两句，各自算尾首比", () => {
  isFn(algo.breathMetrics, "breathMetrics");
  const pts = [];
  for (let t = 0; t <= 0.6; t += 0.03) pts.push({ t, pitch: 60, rms: 0.1 });      // 第一句，平稳
  for (let t = 1.2; t <= 1.8; t += 0.03) pts.push({ t, pitch: 64, rms: 0.1 - 0.05 * (t - 1.2) / 0.6 }); // 换气后第二句，渐弱
  const r = algo.breathMetrics(pts);
  // 两句的尾首比各为 1 与约 0.61，中位数取两者之间
  assert(r.tailRatio > 0.5 && r.tailRatio < 1.0, `尾首比应落在两句之间，实际 ${r.tailRatio}`);
});

// ===== logistic / thinTeacher =====
console.log("\nlogistic");
test("正好落在阈值上得 50 分，越小分越高，且始终在 0–100 内", () => {
  isFn(algo.logistic, "logistic");
  close(algo.logistic(1.0, 1.0, 2.0), 50, 0.01, "阈值处的分");
  assert(algo.logistic(0, 1.0, 2.0) > 80, "抖动为 0 时应给高分");
  assert(algo.logistic(2.0, 1.0, 2.0) < 20, "抖动翻倍时应给低分");
  for (const x of [0, 0.3, 1, 5, 100]) {
    const s = algo.logistic(x, 1.0, 2.0);
    assert(s >= 0 && s <= 100, `分数越界：${x} → ${s}`);
  }
});

console.log("\nthinTeacher");
test("点数在上限内时原样返回", () => {
  isFn(algo.thinTeacher, "thinTeacher");
  const tea = makeTeacher(3, 0.02);
  const out = algo.thinTeacher(tea, 100, 1e6);
  assert(out.length === tea.length, `不该抽稀，实际 ${out.length}/${tea.length}`);
});

test("超上限时抽稀到上限内，且首尾的时间点保留", () => {
  isFn(algo.thinTeacher, "thinTeacher");
  const tea = makeTeacher(60, 0.02); // 3001 个点
  const stuCount = 2000;
  const maxCells = 1e6;
  const out = algo.thinTeacher(tea, stuCount, maxCells);
  assert(out.length * stuCount <= maxCells, `抽稀后仍超限：${out.length * stuCount}`);
  assert(out.length > 2, "抽稀过头了");
  assert(out[0].t === tea[0].t && out[out.length - 1].t === tea[tea.length - 1].t,
    "首尾时间点必须保留，否则两端对不上");
});

// ===== 端到端：与 simulateAnalysisAfterRecord 里同样的调用顺序 =====
console.log("\n端到端（按页面里的调用顺序串联）");

// 与 prepareTeacherCurve 同构：只给有音高的字落点，20ms 均匀采样
function teacherFromLyrics(lyrics) {
  let dur = 0;
  for (const ly of lyrics) {
    if (Number.isFinite(ly.start) && Number.isFinite(ly.duration)) dur = Math.max(dur, ly.start + ly.duration);
  }
  const pts = [];
  for (let t = 0; t <= dur; t += 0.02) {
    for (const ly of lyrics) {
      if (ly.pitch === null || !Number.isFinite(ly.pitch)) continue;
      if (!Number.isFinite(ly.start) || !Number.isFinite(ly.duration)) continue;
      if (t >= ly.start && t < ly.start + ly.duration) { pts.push({ t, pitch: ly.pitch }); break; }
    }
  }
  return pts;
}
// 学生跟唱：speed=1.1 表示整段拖慢一成
function singAlong(lyrics, speed, dt, rms) {
  let dur = 0;
  for (const ly of lyrics) {
    if (Number.isFinite(ly.start) && Number.isFinite(ly.duration)) dur = Math.max(dur, ly.start + ly.duration);
  }
  const pts = [];
  for (let t = 0; t <= dur * speed; t += dt) {
    const src = t / speed; // 学生时间轴 → 乐谱位置
    for (const ly of lyrics) {
      if (ly.pitch === null || !Number.isFinite(ly.pitch)) continue;
      if (!Number.isFinite(ly.start) || !Number.isFinite(ly.duration)) continue;
      if (src >= ly.start && src < ly.start + ly.duration) { pts.push({ t, pitch: ly.pitch, rms }); break; }
    }
  }
  return pts;
}
function runPipeline(lyrics, stu) {
  const tea = teacherFromLyrics(lyrics);
  const thinned = algo.thinTeacher(tea, stu.length, 4e6);
  const mapping = algo.dtwAlign(stu, thinned, { bandSec: 3 });
  const rhythm = algo.rhythmMetrics(stu, thinned, mapping);
  const breath = algo.breathMetrics(stu);
  const words = algo.wordDeviations(stu, thinned, mapping, lyrics);
  return {
    rhythm, breath, words,
    rhythmScore: Math.round(algo.logistic(rhythm.warpStd, 1.0, 2.0)),
    breathScore: algo.breathScoreFromCv(breath.cv),
  };
}

test("跟着乐谱准时唱：节奏高分、气息满稳、没有跑偏的字", () => {
  const stu = singAlong(LYRICS, 1.0, 0.03, 0.15);
  const r = runPipeline(LYRICS, stu);
  assert(r.rhythmScore > 80, `节奏分应偏高，实际 ${r.rhythmScore}`);
  assert(r.breathScore > 95, `气息稳定度应偏高，实际 ${r.breathScore}`);
  assert(r.words.items.length === 3, `应有 3 个字，实际 ${r.words.items.length}`);
  for (const it of r.words.items) {
    assert(Math.abs(it.diff) < 0.05, `第 ${it.index} 个字偏差 ${it.diff}`);
  }
});

test("整段拖慢一成：节奏分掉下来，速度比报 1.1 左右", () => {
  const onTime = runPipeline(LYRICS, singAlong(LYRICS, 1.0, 0.03, 0.15));
  const slow = runPipeline(LYRICS, singAlong(LYRICS, 1.1, 0.03, 0.15));
  close(slow.rhythm.tempo, 1.1, 0.05, "速度比");
  assert(
    slow.rhythmScore < onTime.rhythmScore,
    `拖拍后节奏分应更低：准时 ${onTime.rhythmScore} → 拖拍 ${slow.rhythmScore}`
  );
});

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

// ===== 汇总 =====
console.log("");
if (failures.length) {
  console.log(`✗ ${failures.length} 个失败，${passed} 个通过`);
  process.exit(1);
}
console.log(`✓ ${passed} 个全部通过`);
