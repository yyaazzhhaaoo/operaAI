# 音准对比页异步化改造设计

日期：2026-09-20 ｜ 状态：已评审待实现 ｜ 关联：《5-接口清单-V1.0》3.1 / 3.2、B1–B5；`DOC_ISSUES.md` 第 11、12 条

## 1. 背景与目标

`pitch_comparison.html` 是唯一一个真实调用后端的页面。它的音准对比分析至今走的是 `app-d.py` 里 `demo_bp` 的**同步阻塞**接口 `GET /api/analyze?t=&s=&job=`——浏览器发一个请求挂在那儿等 80–100 秒，靠另一个轮询 `/api/progress` 读服务端内存里的日志文案来猜进度。

B 组接口（B1–B5）已于 2026-09-14 落地，是文档 3.1 定义的异步协议：B2 提交立即返回 `task_id`，B3 轮询进度，B4 取结果，真正的算法在 Celery worker 里跑。本次要把这个页面从同步迁到异步，并把其余仍在调 `demo_bp` 的接口一并迁到 `audio_analyze.py`。

迁移后：

1. 页面的分析请求不再是长连接，改由 B3 轮询驱动进度条与日志
2. 进度从「按日志文案猜」变成后端真值
3. 页面所有请求都经 `api_bp`，全部受 `@login_required` 保护（`demo_bp` 的 4 条路由**至今没有任何鉴权**）
4. `demo_bp` 不再被任何页面调用，成为待下线代码

## 2. 范围之外（明确不做）

- **不删 `demo_bp`**。按本次决策保留原样，仅登记「已无调用方」到 `DOC_ISSUES.md` 第 11 条。删除是独立的一次清理
- **不给 `demo_bp` 的 4 条路由加鉴权**——它们已是死代码，加鉴权等于给待删代码增加维护面
- **不在前端渲染 `words` / `regions`**。B4 会返回逐字结果与着色片段，但该页现有的偏差着色由 `aligned` 分片算出，视觉等价。逐字展示是独立需求（YAGNI）
- **不改 B3/B4 的路由、入参、状态枚举**。只往 B4 的 `result` 里加字段
- **不修 `analyze_service.submit()` 不校验音频归属的问题**（见第 8 节遗留）
- 不引入任何新依赖

## 3. 现状：前端调用的接口与契约缺口

### 3.1 调用点对照

| 前端位置 | 现在调到 | 目标 |
|---|---|---|
| `:527` 上传 | `POST /api/audio/upload`（B1） | ✅ 已迁移（工作区已有改动） |
| `:534` 取音频 | `j.data.url` → B5 | ✅ 已迁移 |
| `:809` 进度轮询 | `GET /api/progress?job=`（`demo_bp`） | B3 `GET /api/analyze/status/<task_id>` |
| `:829` 分析 | `GET /api/analyze?t=&s=&job=`（`demo_bp`，同步） | B2 提交 → B3 轮询 → B4 取结果 |

### 3.2 结果契约不同构

前端 `drawTimeline()` 消费的是 demo 形状：

```
{ aligned: [{t_time, s_time, t_cents, s_cents, diff, t_f0, s_f0, ...}],
  teacher: {times, cents, f0}, student: {...},
  score, dimensions, ref_hz, teacher_onset, student_onset, octave_shift }
```

B4 按文档 3.2 返回的是：

```
{ overall, dimensions, timeline: {duration, teacher_pitch, student_pitch, deviation_cents},
  regions, words }
```

其中大部分可无损转换（见 5.2），但有 4 个字段 B4 不返回、前端也反推不出：

| 字段 | 用途 | 为什么反推不出 |
|---|---|---|
| `octave_shift` | 「学生整体低 N 个八度，已自动对齐」提示、tooltip 原始 Hz | `student_pitch` 已是修正后的值，原始 Hz 已丢失 |
| `teacher_onset` | 同步播放起点的 seek 位置 | `words[].start` 已减掉 onset |
| `student_onset` | 同上 | 同上 |
| `ref_hz` | 把 Hz 曲线还原成音分（绘图坐标系） | 前端只能在抽稀后的 1500 点上估中位数，与后端在全帧上算的有微差 |

### 3.3 B1 / B2 响应形状偏离文档

工作区当前有两处为了迁就旧前端而改动的响应形状，与文档/实测记录不符：

| | 文档 / `test_audio/README.md` 记载 | 工作区当前 |
|---|---|---|
| B1 | `data.file_id` | `data.{id, filePath, url}` |
| B2 | `data.task_id`（文档示例见 `DOC_ISSUES.md` 第 9 条） | `data` 是裸字符串 |

前端要重写，就没有理由再迁就旧形状。本次一并改回。

## 4. 后端改动

### 4.1 `app/services/analyze_service.py`：`result` 补 4 个字段

`_analyze()` 里这 4 个值**全都已经算好**，只是没往 `result` 里放：

| 字段 | 现有来源 |
|---|---|
| `octave_shift` | `_best_octave()` 的返回值（第 270 行） |
| `teacher_onset` | `_load_vocal(t_path, ...)` 的返回值 `t_onset`（第 250 行） |
| `student_onset` | 同上，`s_onset` |
| `ref_hz` | `np.median(voiced)`（第 264 行） |

```python
result = {
    "overall": ...,
    "dimensions": dimensions,
    "timeline": _timeline(...),
    "regions": _regions(...),
    "words": words,
    # 文档 3.2 未定义这四个字段，但前端展示需要 → DOC_ISSUES 第 14 条。
    # 尤其 octave_shift：student_pitch 已经是它修正后的结果，不单独给出，
    # 前端无从知道修正发生过、也无从还原原始音高。
    "octave_shift": octave_shift,
    "teacher_onset": round(t_onset, 3),
    "student_onset": round(s_onset, 3),
    "ref_hz": round(ref_hz, 2),
}
```

`app/api/audio_analyze.py` **不动**——B4 是 `return ok(analyze_service.result(task_id))`，加字段自动透出。

**副作用**：`DOC_ISSUES.md` 第 12 条第 2 项写着「全局偏移量没有单独字段可放（契约里没有），仅进日志」，本次给 `octave_shift` 找到了放处，该项随之了结。

### 4.2 `app/api/audio_analyze.py`：B1 / B2 改回文档形状

```python
# B1
return ok({"file_id": audio.id, "url": url_for("api.audio_download", file_id=audio.id)})

# B2
return ok({"task_id": task_id})
```

**去掉 `filePath`**。它不只是无用：`audio.file_path` 是服务端存储名（uuid + 扩展名），而 `app/common/storage.py` 的模块文档明确写着「库里 `audio_files.file_path` 只存文件名，不存绝对路径……也不会把服务器目录结构泄漏到接口响应里」。回给客户端正好违背这条原则。

**保留 `url`**。前端要拿一个地址喂给 WaveSurfer；由 `url_for("api.audio_download", ...)` 生成能保证路径永远跟着 B5 的真实路由走，前端不必硬编码 `/api/audio/${id}`——硬编码路径与后端漂移正是 `DOC_ISSUES.md` 第 1 条记录的那类问题。代价是 B1 响应比文档多一个字段，与 4.1 一并登记为第 14 条。

同时更新文件末尾那段关于 `pitch_comparison.html` 去留的注释：去留问题已随本次迁移了结，但 `demo_bp` 保留未删。

## 5. 前端改动（`pitch_comparison.html`）

### 5.1 删除

| 目标 | 位置 | 理由 |
|---|---|---|
| `estimateProgressFromLogs()` 整段 | `:761–783` | B3 直接给 `progress` 真值，不再从日志文案猜 |
| `waves[role].filePath` | `:536` | B2 认的是 `audio_files.id`；且该字段已从 B1 响应移除。`:829` 那处读取随 `doAnalyze()` 一起被重写掉（见 5.3） |
| `updateDimensions` 的 mock 兜底分支 | `:857–866` | B4 必返回 `dimensions`，兜底分支不可达 |
| `AbortController` 300s 超时 | `:827–832` | 迁成异步后没有任何长请求 |

### 5.2 新增 `adaptResult(b4)`

把 3.2 契约转成绘图层认识的形状。三条曲线的自洽关系（`_pitch_pairs` 的 docstring）是转换的依据：

- `student_pitch = ref_hz · 2^(s_cents/1200)`
- `deviation_cents = s_cents − t_cents`

于是 `t_cents = 1200·log2(t_hz / ref_hz)`，`s_cents = t_cents + deviation`。

```js
function adaptResult(b4) {
    const tl  = b4.timeline;
    const tHz = tl.teacher_pitch;        // [[t, hz], ...]
    const sHz = tl.student_pitch;
    const dev = tl.deviation_cents;      // [[t, cents], ...] 带符号
    const toCents = hz => 1200 * Math.log2(hz / b4.ref_hz);

    const aligned = tHz.map((p, i) => {
        const t_cents = toCents(p[1]);
        const d = dev[i][1];
        return {
            t_time: p[0],
            t_cents,
            s_cents: t_cents + d,
            t_f0: p[1],
            s_f0: sHz[i][1],
            diff: Math.abs(d),           // ← 必须取绝对值，见下
        };
    });

    return {
        aligned,
        duration: b4.timeline.duration,
        score: b4.overall,
        dimensions: b4.dimensions,
        octave_shift: b4.octave_shift,
        teacher_onset: b4.teacher_onset,
        student_onset: b4.student_onset,
    };
}
```

**`diff` 必须取绝对值**：demo 版本给的 `diff` 是 `abs(t_c - s_c)`，而 B4 的 `deviation_cents` 是**带符号**的 `s_cents - t_cents`。不取绝对值，`drawTimeline` 里所有 `diff < 20 / < 50` 的判断会把「偏低」判成负值从而恒为绿——**偏低半音会比偏低一个全音看起来更准**，着色完全反了。

三条曲线的长度由 `_timeline()` 保证一致（同一个 `kept` 时间数组、同一个 `stride`），可以按下标直接配对。

### 5.3 重写 `doAnalyze()`

同步单请求 → 三阶段：

```
① B2 POST /api/analyze/submit  {teacher_audio_id, student_audio_id}
   → {code:0, data:{task_id}}              立即返回，不阻塞
② B3 GET  /api/analyze/status/<task_id>   每秒一次
   → {status, progress, stage, message}
   queued     → 进度条停在 progress，日志「排队中」
   processing → 进度条 = progress；stage/message 变化时追加一行日志
   done       → 停轮询，进 ③
   failed     → 停轮询，红色日志 + alert（message 由后端保证可读）
③ B4 GET  /api/analyze/result/<task_id>
   → 3.2 契约  →  adaptResult()  →  drawTimeline()
```

要点：

- **轮询护栏 10 分钟**。`test_audio/README.md` 实测单对 77–99 秒，10 分钟留足余量；worker 挂掉时任务会永远停在 `queued`，没有护栏前端会无限轮询
- **日志追加式**：只在 `stage + message` 变化时 append，不每轮刷 `innerHTML`。日志条数从原来的十几行变成 6 个阶段的进入记录
- **进度条用真值**：原来靠 `estimateProgressFromLogs` 猜（且只支持单对分析），现在直接 `st.progress`，与文档 3.1 的 `STAGE_RANGE` 一致
- **不用调 B4 前先判状态**：B4 在任务未完成时回 409，只在 `done` 后调

### 5.4 `drawTimeline()` 改 1 行

```js
- maxTime = data.teacher.times[data.teacher.times.length - 1];
+ maxTime = data.duration;
```

B4 的 `timeline.duration` 就是同一个值（栅格末端）。其余绘图逻辑、tooltip 一行不动——它们消费的 `aligned[i].*`、`data.octave_shift`、`data.score` 全部由 `adaptResult` 供给。

### 5.5 401 统一处理

B1–B5 全挂了 `@login_required`，会话过期时会回 `401 {"code":401,"message":"未登录"}`。上传与分析入口加一处判断：命中 401 就提示「会话已过期，请重新登录」并 `location.replace('/login.html')`，不再把 401 的 JSON 当普通错误弹 alert。

### 5.6 上传处读新形状

`j.data.id` → `j.data.file_id`，`waves[role] = { ws, id: j.data.file_id, url: audioUrl }`。

## 6. 文档改动

### 6.1 `DOC_ISSUES.md`

**新增第 14 条**：3.2 结果契约与 B1 响应缺前端展示所必需的字段。

要写清的内容：3.2 只定义 `overall / dimensions / timeline / regions / words`，未定义 `octave_shift`、`teacher_onset`、`student_onset`、`ref_hz`；且 `student_pitch` 是八度修正**之后**的值，不给出 `octave_shift` 则修正与否在结果里无处可查（这是第 12 条第 2 项在 `octave_fixed` 粒度之外的另一个面）。B1 同理未定义 `url`。实现按第 4 节补上，待文档方确认。

**更新第 11 条**：`pitch_comparison.html` 已随本次迁移到 B1/B2/B3/B4/B5。该条记录的两个悬案（「音频加载是坏的」「结果契约无法平滑切换」）均已解决——前者由 B1 返回 B5 的 `url` 解决，后者由前端的 `adaptResult()` 转换层解决。`demo_bp` 按本次决策**保留未删**，四条路由已无任何调用方。

**更新第 12 条第 2 项**：全局八度偏移量现在有了字段（`result.octave_shift`），原文「没有单独字段可放，仅进日志」不再成立。

**新增第 15 条**：B2 未校验音频归属（见第 8 节）。文档 3.1 只规定了 B2 的入参与返回，没有规定「提交分析时是否要校验这两个 `audio_id` 属于调用者」。实现现状是只查存在性，于是任何登录用户可以对任意 `audio_id` 提交分析并读到 B4 的完整音高曲线——包括他人 `access=private` 的录音。B5 有 `get_playable()` 做权限判定，B2 没有对应的一层。登记为待文档方明确，本次不修。

### 6.2 `CLAUDE.md`

改 3 段：

1. 「例外 1 — `pitch_comparison.html`」：端点清单从 `demo_bp` 的 4 条改为 `B1 / B2 / B3 / B4 / B5`，并说明 `API` 为空字符串、走同源 nginx 代理
2. 「动那 4 条演示路由前先看这条」与「但 `pitch_comparison.html` 的音频加载现在是坏的」两条：`demo_bp` 已无调用方，两条警示的前提不再成立，合并改写成「4 条演示路由已无调用方，待删除」
3. 「`/api/upload`、`/api/progress`、`/api/analyze` 仍返回裸字段……要统一必须先改前端」：现在前端已改完，`audio_analyze.py` 的 B1/B2 已改用 `ok()` 统一信封

### 6.3 `/Users/meiyazhao/Desktop/test_audio/README.md`

「怎么用」一节里的 curl 示例标注了 `→ {"code":0,...,"data":{"file_id":<N>}}` 与 `→ {"data":{"task_id":"..."}}`，改后与新形状一致（B1 的 `file_id` 本来就是这个，B2 的 `task_id` 是改回来的）。需补上 B1 现在还会返回 `url`。

## 7. 验证

### 7.1 新增 `scripts/smoke_analyze.sh`

仿 `scripts/smoke_auth.sh`：不依赖 jq（JSON 解析交给 python3 标准库）、断言失败累计不中断、退出码可接 CI、EXIT trap 清理临时目录。音频目录参数化：

```bash
AUDIO_DIR="${AUDIO_DIR:-$HOME/Desktop/test_audio}"
```

前置：后端 + Celery worker 都已启动、数据库已灌种子。脚本开头打印「单轮约 2 分钟」的提示。

断言清单：

| # | 断言 | 防的是什么 |
|---|---|---|
| 1 | 未登录调 B2 → 401（非 302） | 迁移后 B2 确实受 `login_required` 保护 |
| 2 | B1 返回 `data.file_id` 为整数 | — |
| 3 | B1 响应**不含** `filePath` | 防存储路径泄漏回归 |
| 4 | B1 返回 `data.url` 形如 `/api/audio/<file_id>` | 前端据此加载音频 |
| 5 | B2 返回 `data.task_id` 为非空字符串 | — |
| 6 | B3 的 `stage` 始终落在文档 3.1 的枚举内 | 防 `DOC_ISSUES` 第 10 条那个「前端认不出 stage」的错配 |
| 7 | B3 的 `progress` 单调不减、终态为 100 | — |
| 8 | B4 含 `octave_shift / teacher_onset / student_onset / ref_hz` | 本次新增的 4 个字段 |
| 9 | **自洽性**：对每个采样点 `1200·log2(student_hz/teacher_hz) ≈ deviation_cents`（容差 0.5） | `adaptResult()` 的正确性完全建立在这条关系上 |
| 10 | **基准线**：同一条轨同时作教师与学生 → `overall == 92.6`、`dimensions.音准 == 100.0`、偏差严格为 0、`regions` 全部 `green` | 对齐 / 基准音高 / 八度修正任一步改坏都会立刻偏离 |

第 10 条的期望值取自 `test_audio/README.md` 的实测记录（「13 对 13」那一行）。它之所以是**基准线**：同一条轨做 DTW 偏差必然严格为 0，任何非零都说明流水线坏了，与录音质量无关。

注意 `overall` 是 **92.6 而非 100**，这是评分公式决定的（五维 `_logistic` 的 `mid` 都不为 0），不是 bug——README 里专门有一节解释。脚本注释里要指向它，避免后人把它当失败去「修」。

### 7.2 手工验证

脚本覆盖不到绘图与交互。需在浏览器里实际走一遍：上传两条音频 → 分析 → 观察进度条随 stage 推进、日志出现 6 个阶段、曲线与 tooltip 正常、八度提示文案正确、同步播放正常。

## 8. 风险与遗留

- **`analyze_service.submit()` 不校验音频归属**（本次不修）。`_require_audio()` 只查 `audio_files` 里有没有这个 id，不查 `uploader_id`，任何登录用户可以拿任意 `audio_id` 提交分析并读到 B4 的完整音高曲线。这是真实的信息泄露路径，但它是 B2 自身的鉴权缺口、独立于本次迁移。**本次登记到 `DOC_ISSUES.md`，不在这个页面改动里顺手修**——修它要定「教师能否分析他人录音」这类业务规则，不属于前端迁移的范围。
- **前端轮询期间关掉页面**，`setInterval` 随页面卸载消失，但 B2 已投出去的 Celery 任务会跑完，结果在 redis 里留 1 小时。无害。
- **`MAX_AUDIO_SEC = 180`** 会把 01/02/05 三条截到前 3 分钟（`test_audio/README.md` 已记）。冒烟脚本用 01，断言的第 10 条期望值正是在这个截断下测出来的，不要为此调大常量。
- **迁移后 `demo_bp` 成为死代码**，仍会随 `app-d.py` 一起加载并注册 4 条路由（含一段 librosa/DTW 实现）。保留是本次的明确决策，但它是后续清理项。
