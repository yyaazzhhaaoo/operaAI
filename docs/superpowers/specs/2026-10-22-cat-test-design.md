# 摸底测试（CAT）端到端设计

日期：2026-10-22
范围：J1–J3、新增 `POST /api/cat/skip`、B4 附加字段、`cat_test.html` 真实录音接线、摸底题库种子
关联：《1-PRD-V1.0》4.8 模块8；《3-功能清单V1.0》模块8；《5-接口清单-V1.0》2.10；《4-数据库设计-V1.1》第 13 节 `cat_questions`；`DOC_ISSUES.md` 第 47 条

## 背景

`cat_test.html` 已有完整的介绍页、逐题页、分析动画、结果卡与完成页，但数据全是 mock：

- 8 句题写死在 `PHRASE_POOL`，与数据库无关；
- 录音是 3 秒定时器，不调 `getUserMedia`；
- 评分、BKT 前后值、雷达、Top3 全是随机数；
- 除 `/api/auth/me` 外不调任何后端。

后端 `app/api/cat.py` 的 J1–J3 三个路由都只 `return ok()`，`app/api/cat_test.py` 是 0 字节文件却被 `app/api/__init__.py` import。线上 `cat_questions` 表 **0 行**，`seed.sql` 只有 1 行指向伪造 `segments.id=1` 的占位。

本轮把页面接到真实链路：真实录音 → B1 上传 → J2 提交 → B3 轮询 → B4 结果 → J3 报告。分析管线、落库与 BKT 规则全部复用 D1（`practice_service`），不另起一套。

文档只给了三句话（《5-接口清单》2.10）：

- J1 `GET /api/cat/questions`：启用中的题目列表（功能 8.2）；
- J2 `POST /api/cat/submit`：逐题提交录音 → 走分析管线 → 写 `practice_records(source=cat_test)` + BKT 更新；
- J3 `GET /api/cat/report/<record_id>`：雷达图数据 + 技能 P(L) 列表 + Top3 路径（功能 8.7–8.9）。

请求/响应体、`record_id` 语义、跳过接口、维度口径均未定义，本设计定的口径登记在 `DOC_ISSUES.md` 第 47 条。

## 已确认的产品口径

1. 交付端到端全链路。
2. J3 用 `record_id` 定位学生，返回该生**最新** BKT 画像 + Top3；逐题分数由前端用 B4 结果汇总。不新增 CAT session 表。
3. 雷达图与技能列表只画 5 个可评维度：音准控制、气息支撑、拖腔、归韵咬字、节奏感知。滑音、颤音、装饰音技巧没有分析维度，不展示、不填默认值。
4. 题库用现有真实分段（demo 34 的 6 段）过渡，正式题目仍待教师录制。
5. 跳过摸底新增 `POST /api/cat/skip`，只给尚无 BKT 记录的技法写默认值 0.35。
6. Top3 = 按 P(L) 升序取最弱的 3 个技法。

## 1. 题库数据

从 demo 34（`teacher_demos.title='测试06'`，即为《穆桂英挂帅》Excel 分段上传的测试剧目）选 6 段。选择依据：都有 `segments.audio_id` 段音频、本机文件齐全、`lyrics_json` 有逐字数据，且合起来覆盖 5 个可评维度。

| seq | segment_id | 标题 | 时长 | focus_dims |
|---|---|---|---|---|
| 1 | 207 | 辕门外三声炮如同雷震 | 12.15s | 音准、气息、拖腔 |
| 2 | 208 | 天波府里走出来我保国臣 | 9.10s | 音准、节奏、咬字 |
| 3 | 209 | 头戴金冠压双鬓 | 4.50s | 节奏、咬字 |
| 4 | 211 | 帅字旗飘入云 | 11.40s | 气息、拖腔 |
| 5 | 212 | 斗大的穆字震乾坤 | 4.30s | 音准、咬字 |
| 6 | 216 | 谁料想我五十三岁又管三军 | 7.40s | 节奏、气息、拖腔 |

`segment_id` 是当前库里的实测 id；种子脚本不写死 id，按下面的规则定位：

- 对每个标题，找 `segments.title` 完全相同、`audio_id IS NOT NULL` 的行；
- 有多行时取 `demo_id` 最大的那条（最近一次上传）；
- 找不到就报错退出，不静默跳过。

脚本 `scripts/seed_cat_questions.py`：

- 用 `with session_scope() as s:`，与其它脚本一致；
- 幂等：先按 `seq` 删除已有行，再插入 6 行；不整表清空，避免误删未来的自定义题目；
- 写入 `is_active=TRUE`；
- 打印每题定位到的 `segment_id` 与标题。

`seed.sql` 不改成引用 demo 34：全新安装时只有伪造的 segment 1，真实剧目是后续数据准备导入的。保留现有占位行，并在注释里指向 `scripts/seed_cat_questions.py`。

## 2. J1 `GET /api/cat/questions`

- 权限：`@login_required`（教师也可读，便于预览题库；文档权限列就是「登录」）。
- 查询：`cat_questions.is_active IS TRUE`，按 `seq ASC`；内连接 `segments`（`segment_id` 为 NULL 或分段已删的题跳过）。用 `selectinload(CatQuestion.segment).selectinload(Segment.demo)` 一次取回，避免 N+1。
- 响应：

```json
{
  "questions": [
    {
      "id": 1,
      "seq": 1,
      "segment_id": 207,
      "title": "辕门外三声炮如同雷震",
      "demo_title": "测试06",
      "duration": 12.15,
      "focus_dims": ["音准", "气息", "拖腔"],
      "lyrics": "辕门外三声炮如同雷震",
      "audio_url": "/api/audio/139"
    }
  ]
}
```

字段口径：

- `title`：`segments.title`；为空时用 `第 {seq} 句`。
- `demo_title`：`segments.demo.title`；为空时 `""`。demo 34 的剧目名就是「测试06」，页面原样显示，正式题库替换后自然消失。
- `duration`：`segments.duration`，可为 `null`。
- `focus_dims`：`cat_questions.focus_dims`，不是列表时回 `[]`。
- `lyrics`：`segments.lyrics_json` 里各 `word` 顺序拼接；`null`/空时回 `""`。
- `audio_url`：`url_for("api.audio_download", file_id=segments.audio_id)`；无段音频时为 `null`。在 API 层生成，与 C2 的 `demos_segments_annotations.py:55` 同口径，service 只返回 `audio_id`。
- 不返回 `difficulty` / `description`：两者在库里没有数据源，由前端处理（见第 7 节）。

题库为空时回 `{"questions": []}`，不是 404。

## 3. J2 `POST /api/cat/submit`

- 权限：`@login_required` + `@student_required`。
- 请求：`multipart/form-data`
  - `segment_id`：必填，`segments.id`
  - `audio_id`：必填，B1 返回的 `file_id`
  - `duration_sec`：选填，正数；不传则 NULL
- 校验顺序：
  1. 当前账号没有学生档案 → 403；
  2. `audio_id` 不存在 → 404；`audio.uploader_id != 当前用户` → 403（同 D1，防止拿别人的录音冒充）；
  3. `segment_id` 不是启用中的 CAT 题目 → 404（防止把普通练习记成摸底）；
  4. 分段/示范音频缺失交给 `analyze_service.submit` 统一判 404。
- 行为：调用 `analyze_service.submit` 的模式二（`segment_id` + `student_audio_id`），persist 传纯数据：

```python
{
    "kind": "cat_test",
    "student_id": student_id,
    "segment_id": segment_id,
    "audio_id": audio_id,
    "duration_sec": duration_sec,
}
```

- 响应：`{"task_id": "<id>"}`。
- 两个表单解析函数（`_form_int` / `_duration_sec`）在 `cat.py` 内复写，校验口径与 D1 相同；不去动 `practice.py` 的私有函数。

### 3.1 落库与 BKT 的复用改动

`practice_service.save_result` 目前把 `source` 写死成 `"practice"`。改为：

```python
source = metadata.get("kind") or "practice"
record = PracticeRecord(..., source=source, ...)
before, after = apply_bkt(..., source_type=source, source_id=record.id)
return {"record_id": record.id, "bkt": {"before": before, "after": after}}
```

`practice_records.source` 与 `bkt_history.source_type` 都是 `VARCHAR(10)` / `VARCHAR(20)`，`"cat_test"`（8 字符）放得下，不改 schema。D1 的 persist 仍传 `kind="practice"`，行为不变。

`analyze_service._analyze` 的落库分发增加：

```python
saved = practice_service.save_result(persist, result)
if isinstance(saved, dict):
    result.update(saved)
```

`homework` 分支不动（`homework_service.save_result` 目前返回 None，`isinstance` 判断自然跳过）。落库仍在 `task_repo.update(status="done")` 之前，失败即任务 failed，保持现有语义。

### 3.2 B4 附加字段

B4 的 `data` 增加两个字段，仅当本次任务有 persist 时存在：

```json
{
  "record_id": 123,
  "bkt": {
    "before": {"音准控制": 0.5, "气息支撑": 0.5},
    "after":  {"音准控制": 0.59, "气息支撑": 0.56}
  }
}
```

- 已有字段（`overall`/`dimensions`/`timeline`/`regions`/`words`/`cdm`/`octave_shift` 等）不变；前端按需读取，多出的键不影响既有调用方。
- `bkt.before` / `bkt.after` 只含本次真正更新的技法；B4 的五维总是齐全，因此实际是 5 个技法。
- 前端 8.6 的 P(L) 前后对比直接用这两个字典，不再调额外接口。

## 4. J3 `GET /api/cat/report/<int:record_id>`

- 权限：`@login_required`。学生只能看本人记录；教师可看任意学生的记录。
- 行为：
  1. 取 `practice_records.id = record_id`；不存在、`source != 'cat_test'`、`student_id` 为空 → 404；
  2. 学生调用时，`students.id`（由 `users.id` 查）与 `record.student_id` 不一致 → 403；
  3. `bkt_history_repo.get_latest_per_skill_for_student(db, student_id)` 取该生每个技法最新一行；
  4. 只保留 5 个可评技法，顺序固定：音准控制、气息支撑、拖腔、归韵咬字、节奏感知。没有 BKT 行的技法 `p_l`/`confidence` 为 `null`；
  5. Top3：按 `p_l` 升序取前 3，`null` 排最后。
- 响应：

```json
{
  "record_id": 123,
  "student_id": 2,
  "profile": [
    {"skill": "音准控制", "p_l": 0.59, "confidence": 0.45},
    {"skill": "气息支撑", "p_l": 0.56, "confidence": 0.45},
    {"skill": "拖腔", "p_l": null, "confidence": null},
    {"skill": "归韵咬字", "p_l": 0.31, "confidence": 0.45},
    {"skill": "节奏感知", "p_l": 0.62, "confidence": 0.45}
  ],
  "top3": [
    {"skill": "归韵咬字", "p_l": 0.31, "confidence": 0.45},
    {"skill": "气息支撑", "p_l": 0.56, "confidence": 0.45},
    {"skill": "音准控制", "p_l": 0.59, "confidence": 0.45}
  ]
}
```

- `record_id` 只是「定位学生 + 校验这是摸底记录」的锚点；报告内容是**当前最新画像**，不是某一次测试的历史快照。口径见 `DOC_ISSUES.md` 第 47 条。
- 状态标签（已掌握/学习中/薄弱/未掌握）与雷达配色是前端 UI 词汇，后端只返回 `p_l`，不在响应里造标签。

## 5. 新增 `POST /api/cat/skip`

- 权限：`@login_required` + `@student_required`。
- 行为：对 5 个可评技法逐一检查 `bkt_history` 是否有该生记录：
  - 没有 → 插入一行 `p_l=0.35`、`confidence=0.4`、`source_type='cat_test'`、`source_id=NULL`；
  - 已有 → 不动，不覆盖学生已有画像。
- `db.commit()` 后返回与 J3 相同结构的画像与 Top3，外加本次写入条数：

```json
{"created": 5, "profile": [...], "top3": [...]}
```

- 幂等：重复调用 `created=0`，不重复写行。
- 不写 `practice_records`：跳过没有录音，不应产生一条成绩记录。

## 6. 权限与错误码

| 场景 | HTTP |
|---|---|
| 未登录 | 401 |
| 非学生调用 J2 / skip；学生没有学生档案；学生查他人报告 | 403 |
| `segment_id` 不是启用中的题目、`audio_id` 不存在、分段缺示范音频 | 404 |
| 报告记录不存在或不是 `cat_test` | 404 |
| 参数缺失/非法（`segment_id`、`audio_id`、`duration_sec`） | 400 |
| J2 提交后未起 Celery default worker | 任务停在 `queued`，不是 HTTP 错误 |

J1/J3 都是「登录」权限；J2/skip 是「学生」。教师进 `cat_test.html` 时前端提示并禁用开始/跳过（见第 7 节）。

## 7. 前端 `cat_test.html`

### 7.1 数据加载与角色守卫

- 保留现有 `/api/auth/me` 调用；读完 `user.role` 后：
  - `student`：拉 J1，渲染介绍页的题目数与开始按钮；
  - 非 `student`：显示「摸底测试仅学生可用」，禁用开始/跳过按钮（后端也会 403）。
- 删除写死的 `PHRASE_POOL`；改为 `let questions = []`，由 J1 填充。J1 失败显示空状态与重试按钮，**不回落 mock**。
- `TECHNIQUES` 从 8 个减到 5 个：音准控制、气息支撑、拖腔、归韵咬字、节奏感知（顺序与 J3 一致）。
- 题目卡字段映射：`phraseTitle ← question.title`、`phrasePiece ← question.demo_title`、`phraseLyrics ← question.lyrics`、`phraseDuration ← question.duration`（格式化为秒）、`phraseSkill ← question.focus_dims`（标签写「考察维度」，不复用「技法」一词）。`phraseDiff` 的难度 chip 删除——库里没有难度数据源。`phraseDesc` 由前端按 `focus_dims` 生成：「本句重点考察：音准、气息。请先播放示范，再跟唱。」

### 7.2 真实录音

移植 `sing_along.html` 的录音链路：

- `navigator.mediaDevices.getUserMedia({audio: true})` + `MediaRecorder`；
- 录音中显示计时与波形占位，手动「停止」；超过 `question.duration + 3` 秒自动停；
- 停录后 `recordedWav(chunks, mimeType)`：先 `decodeAudioData`，再用 `OfflineAudioContext` 重采样到 16k 单声道，手写 WAV 头；
- 录音不足 0.5 秒提示「录音太短」，不提交；
- 麦克风权限被拒 → toast 提示，恢复按钮。

### 7.3 上传、提交、轮询

1. `POST /api/audio/upload`，`FormData` 字段名 `audio`，文件名 `cat_<题目id>_<时间戳>.wav`；
2. `POST /api/cat/submit`，`FormData` 传 `segment_id`、`audio_id`、`duration_sec`；
3. `GET /api/analyze/status/<task_id>` 每秒轮询，超时 180 秒；
4. `done` 后 `GET /api/analyze/result/<task_id>`，拿 B4 结果。

页面需要补三个小助手：`apiGet` / `apiPostForm` / `pollAnalysis`，语义照抄 `sing_along.html`（同源 `credentials: "same-origin"`，统一解 `{code,message,data}` 信封，`failed` 抛 message）。

### 7.4 4 步进度映射

B3 的 6 个 `stage` 映射到页面已有的 4 步：

| B3 stage | 4 步 |
|---|---|
| 上传完成、人声分离 | 第 1 步 预处理 |
| 音高提取、八度修正 | 第 2 步 音高提取 |
| 时间对齐、评分计算 | 第 3 步 基准对比 |
| `status=done` | 第 4 步 BKT 更新 |

`simulateAnalysis()` 删除，改为按轮询结果推进 `.analyzing-step` 的 `active/done` 类；进度条用 B3 的 `progress`。

### 7.5 本句结果

- 综合分：`result.overall`，配色阈值沿用页面现有 `>=80 绿 / >=60 黄 / 其余红`；
- 维度条：只渲染 5 个维度，`dimensions` 里缺值显示「待分析」，不写 `width: undefined%`；
- BKT 前后：用 `result.bkt.before/after` 渲染 5 行，标签与配色继续用 `getPLColor()`；
- 左侧能力预览：用 `result.bkt.after` 更新本地 5 个技法值，不再用随机数推进；首题之前各技法显示 0.35（与跳过默认值一致），只作过程预览，最终画像以 J3 为准；
- 鼓励文案：用真实主维度分数从 `ENCOURAGE_MESSAGES` 选档，删除 `randomBetween` 造分逻辑；
- 记录 `answers[currentIndex] = {questionId, segmentId, recordId, score, dimensions, bkt, timestamp}`。

### 7.6 完成页

- 统计：总时长（本地计时）、平均分（`answers` 的 `overall` 均值）、`P(L) ≥ 0.60` 的技法数。当前 mock 把 `>=0.60` 标成「已掌握」，与四档标签（`>=0.85` 才是已掌握）冲突；本轮把该统计的标签改成「P(L)≥60%」，四档标签本身不动。
- 最后一题完成（或点「查看完整画像」）后，用最后一条 `recordId` 调 J3：
  - 雷达图 5 维，值为 `p_l`；`null` 按 0 画并在 tooltip 标「未评估」；
  - 技能列表 5 行，`p_l` + 四档标签；
  - Top3 3 张卡：按返回顺序显示最弱 3 个技法，卡片文案由前端按技法生成（例：「优先练习：归韵咬字，当前 P(L) 31%」），不再造「难度匹配度 85%」这类读数。
- `answers` 为空（跳过）时平均分显示「—」，时长 0。

### 7.7 跳过

`skipTest()` 确认后调 `POST /api/cat/skip`，用返回的 `profile`/`top3` 渲染完成页；不调 J1 之外的分析接口。失败时 toast，不进入完成页。

### 7.8 重唱与下一题

- 「重唱」= 重新录音、上传、J2 提交；成功后**替换** `answers[currentIndex]`，不追加。BKT 会按同一规则再次更新（与 D1 反复练习一致），不做本地回滚。
- 「下一题」推进 `currentIndex`；最后一题文案改为「查看完整画像」。
- 步骤点、进度条按 `questions.length` 渲染。

### 7.9 播放示范

题目卡增加「▶ 播放示范」按钮：`new Audio(question.audio_url)` 播放；`audio_url` 为空时按钮禁用。同源请求自动带 Cookie，走 B5。文档 8.3 只写了录音，没有写播放，这是为了「跟唱」成立补的最小交互，登记 `DOC_ISSUES.md` 第 47 条。

### 7.10 安全

题目标题、剧目名、歌词来自数据库，插入 `innerHTML` 前必须转义（或一律用 `textContent`）。现有 `phraseTitle`/`phraseLyrics` 等已经是 `textContent`，新增列表渲染照此办理。

## 8. 后端文件清单

| 文件 | 改动 |
|---|---|
| `app/api/cat.py` | 实现 J1/J2/J3 + skip 路由；`<int:record_id>`；复写 `_form_int`/`_duration_sec` |
| `app/services/cat_service.py`（新） | `questions()`、`submit()`、`report()`、`skip()`、`_profile_and_top3()` |
| `app/schemas/cat.py`（新） | `CatQuestionOut`、`CatQuestionsOut`、`CatSubmitOut`、`CatSkillOut`、`CatReportOut`、`CatSkipOut` |
| `app/repositories/cat_questions_repo.py`（新） | `list_active(db)`、`get_active_by_segment(db, segment_id)` |
| `app/services/practice_service.py` | `save_result` 的 `source` 读 `metadata["kind"]`；返回 `record_id` + `bkt` 前后值 |
| `app/services/analyze_service.py` | `kind=cat_test` 走练习落库；把 `record_id`/`bkt` 合并进 B4 结果 |
| `app/api/__init__.py` | 删掉 `from . import cat_test` |
| `app/api/cat_test.py` | 删除（空文件） |
| `scripts/seed_cat_questions.py`（新） | 幂等灌 6 题 |
| `scripts/smoke_cat.sh`（新） | 端到端冒烟 |

不改 `schema.sql`、`app/models/`、`scripts/check_db.py`：`cat_questions` 表与模型已存在。

## 9. 验收

### 9.1 冒烟脚本 `scripts/smoke_cat.sh`

前置：后端与 Celery default worker 都在跑；已执行 `scripts/seed_cat_questions.py`。用 `stu002`（当前无 BKT 记录）作测试学生。

1. `stu002` 登录；
2. 先调 skip → `created=5`，5 行 `p_l=0.35`；再调一次 → `created=0`，值不变；
3. `GET /api/cat/questions` 返回 6 题，`audio_url` 非空；
4. 上传 `uploads/segments/` 下一段现成 WAV 作为学生录音（B1）；
5. 用该题 `segment_id` + `audio_id` 调 J2，返回 `task_id`；
6. 轮询 B3 到 `done`；B4 含 `record_id` 与 5 个技法的 `bkt.before/after`；
7. `GET /api/cat/report/<record_id>` 返回 5 行 `profile` + 3 行 `top3`；
8. 查库：`practice_records.source='cat_test'` 新增一行；`bkt_history.source_type='cat_test'` 新增 5 行且 `source_id` = 该 record id；
9. 教师调 J2/skip → 403；学生用别人的 `record_id` 调 J3 → 403；不存在的 `record_id` → 404。

如果 `stu002` 已有 BKT（重复跑脚本），先清理该生的 `bkt_history`（仅测试库），或把 skip 断言改成 `created=0` 且值不变——不要在已有画像上写 0.35。

### 9.2 浏览器手工验收

- 学生登录 → 介绍页题目数 = 6；
- 播放示范 → 录音 → 4 步动画 → 本句分数、5 维条、BKT 前后；
- 逐题走完 → 雷达 5 维、技能列表、Top3 3 张卡；
- 重唱一题 → 记录替换，BKT 再次移动；
- 刷新后重进 → 开始新的摸底（无历史报告，符合本轮「不做 session」的口径）；
- 跳过 → 完成页显示默认画像，`bkt_history` 有 5 行 0.35；
- 教师进入 → 提示仅学生可用，开始/跳过不可点；
- 麦克风拒绝 → toast，不产生请求。

### 9.3 回归

- D1–D3 原有 behavior 不变：D1 仍写 `source='practice'`、BKT `source_type='practice'`；
- B4 原有字段不变，`index.html`/`pitch_comparison.html` 不读新键，不受影响；
- `python scripts/check_db.py` 仍通过（无 schema 变更）。

## 10. 不在本轮范围

- `m_cat_test.html` 与手机真机适配（《2-系统设计说明》8.3 标注「需确认使用场景」）；
- 教师录制专门题库的工具与正式题目；
- CAT session 表、历史测试报告、多次测评对比；
- 8 个技法中滑音/颤音/装饰音技巧的评估（没有分析维度与 BKT 数据源）；
- 教师端查看学生摸底报告的页面；
- 修改 `seed.sql` 引用 demo 34（全新安装仍用占位题）；
- 推荐算法与知识图谱的联动（Top3 只按 BKT 最弱项）。

## 11. DOC_ISSUES 第 47 条

实现后新增一条，至少覆盖：

1. J1–J3 的请求/响应体、错误码均未定义；本设计的口径。
2. J3 的 `record_id` 语义：没有 CAT session 表，按「当前最新画像」出报告，不是单次测试快照。
3. 8.10 跳过的后端接口未定义；新增 `POST /api/cat/skip`，只补缺失技法。
4. 页面 8 个技法 vs 分析 5 个维度：滑音/颤音/装饰音技巧无数据源，本轮只展示 5 个。
5. B4 新增 `record_id` / `bkt` 两个文档未定义的字段。
6. 题库过渡数据：demo 34 的 6 段真实录音；正式题目待教师录制；剧目名「测试06」原样显示。
7. 页面字段 `difficulty` / `description` 无数据库来源：难度 chip 删除，描述由 `focus_dims` 前端生成。
8. 重唱语义：重新提交并再次更新 BKT，不做回滚。
9. 8.3 只要求录音；为「跟唱」补「播放示范」按钮。
10. 完成页「已掌握」统计口径与四档标签冲突，改为「P(L)≥60%」。
11. `practice_records.source` / `bkt_history.source_type` 的长度足够 `cat_test`，无需改 schema。
