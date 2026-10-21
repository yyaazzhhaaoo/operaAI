# 学生提交作业设计（我的作业页 + 跟唱作业模式 + F3）

日期：2026-10-21
范围：`GET /api/homeworks/mine`、`GET /api/homeworks/mine/<homework_id>`、`POST /api/homeworks/<homework_id>/submit`（F3）、`my_homework.html`、`sing_along.html` 作业模式
关联：《5-接口清单-V1.0》F3；《3-功能清单》模块 4（作业）；《6-登录与数据隔离方案》
前置：F1（作业列表）、F2（布置作业）、B1–B5、D1–D3 均已实现

## 1. 背景与目标

教师端已经有「布置作业 → 待批改 → 批改」的完整链路（F1/F2/F4–F7），但学生端没有任何作业入口：`homework.html` 只对教师可见，`sing_along.html` 的录音只落 `practice_records`，`submissions` 表里的数据全部是种子数据。F3 `POST /api/homeworks/<id>/submit` 至今是一个直接 `return ok(id)` 的桩。

目标：让学生能看到布置给自己的作业、进入跟唱页录制作业音频、提交后由 B2 同一分析管线评分，结果落 `submissions`，教师端原有的 F1/F4/F5 自动看到这条提交。

**形态选择（已与用户确认）**：不做独立的「提交作业页」，而是「轻量【我的作业】列表页 + 带 `homework_id` 参数跳转 `sing_along.html` 进入作业模式」。理由：`sing_along.html` 已经拥有完整的录音、实时音高、B1 上传、B3 轮询、B4 展示链路，复制一套录音器到新页面既昂贵又容易漂移；`my_homework.html` 只承担列表、详情与入口。

**业务规则（已与用户确认）**：

1. **逾期仍可提交**，列表与详情显示「已逾期」徽标；逾期口径与教师端「逾期提交组合数」一致。
2. **每份作业每个学生只允许提交一次**；已有提交后 F3 回 422，前端不再显示「去完成」。

## 2. 范围

**做**：

- 学生作业列表与详情接口（文档没有，新增，登记 `DOC_ISSUES.md` 第 46 条）。
- F3 真实实现：校验 → 建提交行（`status='submitted'`）→ 复用 B2 分析管线 → worker 回填 `ai_scored`。
- `submissions` 补 `segment_id` 列与 `(homework_id, student_id)` 唯一索引。
- 新页面 `my_homework.html`；`sing_along.html` 增加作业模式；学生侧导航补入口。
- 冒烟脚本、`check_db.py`、`CLAUDE.md`、`DOC_ISSUES.md` 同步。

**不做**：

- 不做整曲录音的作业模式（`segment_ids=[]` 时仍按「该曲目任一分段」提交，见 4.4）。
- 不做重交/补交、教师退回、作业关闭、班级维度。
- 不重构 F1/F4/F5 的教师端展示；不把 `submissions.dimensions` 补进 F5。
- 不做学生端分页、筛选。

## 3. 关键决策

### 3.1 提交行在 F3 当场创建，而不是 worker 成功后才创建

`submissions.status` 的 DDL 注释本来就定义了 `submitted / ai_scored / reviewed` 三档，但全项目至今没有代码写 `submitted`（`DOC_ISSUES.md` 第 38 条已登记）。本设计让 F3 在提交时插入一行：

```
status='submitted', audio_id=..., segment_id=..., submitted_at=DEFAULT NOW()
```

worker 成功后在同一行上回填 `ai_score / ai_detail / bkt_before / bkt_after` 并把 `status` 改为 `ai_scored`。

这样做的收益：

- `submitted_at` 是学生真正点击提交的时间，不是分析完成时间；教师端的逾期统计用的正是这一列。
- 提交后立即在「我的作业」里显示「分析中」，不会在分析期间又出现「去完成」而被重复提交。
- 唯一索引在两个并发请求下能真正挡住第二条。

失败语义：worker 抛异常时，`run_analysis` 的失败分支会**删除仍处于 `submitted` 且 `ai_score IS NULL` 的占位行**，学生刷新后可以重交。若只是 Celery 没起、任务一直 `queued`，占位行会停在「分析中」——这与 B2/D1 任务停在 `queued` 是同一类部署问题，不另做超时清理。

### 3.2 每份作业一次提交，提交对象是学生选定的一个唱段

`submissions` 原本没有 `segment_id`，而 DDL 也没有唯一约束。本设计：

- 新增 `submissions.segment_id`（**普通 INT，不加外键**）。不加外键的原因：`library_repo.replace_segments` 会按 `demo_id` 整批删除旧分段再插入，外键会让「重新解析一个已经有作业提交的曲目」直接失败。分段被重解析后这个 id 可能悬空，它与 `homeworks.segment_ids` 的 JSONB 一样，是历史引用而不是强引用。
- 新增唯一索引 `uq_submissions_homework_student (homework_id, student_id)`。教师端 F1 的提交人数本来就是按 `(homework_id, student_id)` 去重的，这个索引把页面上的口径变成库级事实。

**多段作业的口径**：`homeworks.segment_ids` 是「本次作业的指定唱段集合」，学生可在集合内任选一段录制并提交；提交一次后作业即完成，其余唱段不再接受提交。这与现有种子数据一致：12 号作业挂了 10 个分段，5 个学生各只有 1 条提交。

### 3.3 作业的 `segment_ids` 为空 = 该曲目任一分段都可选

F2 的既有口径是「不选唱段 = 按整曲布置」。跟唱页是以分段为单位的，本轮不实现整曲录音，因此：

- `segment_ids` 为空时，可选集合 = 该曲目当前的全部分段（按 `seq` 升序）。
- 曲目一个分段都没有（`demo_id` 为空，或解析失败留下 0 段）时，`can_submit=false`，F3 回 422「该作业没有可提交的唱段」。
- 这是本轮明确的降级，登记在 `DOC_ISSUES.md` 第 46 条。

### 3.4 截止日与 `homeworks.status` 都不阻止提交

用户已确认逾期可交。`homeworks.status` 目前没有「关闭」入口（F2 恒写 `open`，全项目没有写 `closed` 的代码），本轮不发明关闭语义，F3 不检查它。学生端的状态徽标只看「有没有提交」与「是否逾期」。

## 4. 接口设计

### 4.1 `GET /api/homeworks/mine`（新增）

- 权限：`@login_required` + `@student_required`；无学生档案 → 403「当前账号没有学生档案」。
- 查询：全部作业（`homeworks` 没有班级/名单字段，与 F1 一致，不按教师过滤），左连 `teacher_demos` 取曲目名，左连该学生的 `submissions`。
- 响应：

```json
{
  "homeworks": [
    {
      "homework_id": 12,
      "title": "《穆桂英挂帅》· 辕门外三声炮",
      "demo_id": 16,
      "demo_title": "穆桂英挂帅",
      "segment_count": 10,
      "focus_skills": ["音准控制", "颤音"],
      "deadline": "2026-08-02",
      "status": "todo",
      "overdue": true,
      "submission": null
    },
    {
      "homework_id": 47,
      "title": "测试06 跟唱作业",
      "demo_id": 34,
      "demo_title": "测试06",
      "segment_count": 10,
      "focus_skills": [],
      "deadline": "2026-10-28",
      "status": "ai_scored",
      "overdue": false,
      "submission": {
        "submission_id": 28,
        "status": "ai_scored",
        "ai_score": 82.5,
        "teacher_score": null,
        "submitted_at": "2026-10-21T09:30:00"
      }
    }
  ]
}
```

字段口径：

| 字段 | 口径 |
|---|---|
| `status` | 无提交 → `todo`；有提交 → `submission.status`（`submitted` / `ai_scored` / `reviewed`；列值为 NULL 的脏数据按 `submitted` 处理） |
| `overdue` | 无提交：`deadline` 非空且早于北京时间今天；有提交：`submitted_at` 的日期晚于 `deadline`（与 `homeworks_repo.get_submission_stats` **逐字同源**，`deadline` 为空一律 false） |
| `segment_count` | `len(segment_ids)`；0 表示「按整曲布置」，与 F1 同义 |
| `demo_title` | `demo_id` 为空时为 `null` |
| `focus_skills` | JSONB 原样；NULL 时出 `[]` |
| `submission` | 轻量对象，不含逐字与 CDM（详情接口才返回）；无提交为 `null`。其 `status` 与上行的归一化口径相同（列值 NULL 按 `submitted`） |

排序：无提交在前（`deadline` 升序、NULL 沉底、id 降序），有提交在后（`submitted_at` 降序、NULL 沉底、id 降序）。不分页。

### 4.2 `GET /api/homeworks/mine/<int:homework_id>`（新增）

- 权限同 4.1。作业不存在 → 404「作业不存在」。
- 不校验归属：所有学生看到的是同一批作业（同 F1）。
- 响应在 4.1 的字段基础上增加：

```json
{
  "homework_id": 12,
  "...": "同 4.1 的字段",
  "segment_ids": [110, 111, 112],
  "allowed_segment_ids": [110, 111, 112],
  "can_submit": true,
  "submission": {
    "submission_id": 28,
    "status": "ai_scored",
    "ai_score": 82.5,
    "teacher_score": 85,
    "teacher_comment": "气息比上次稳",
    "submitted_at": "2026-10-21T09:30:00",
    "reviewed_at": null,
    "segment_id": 111,
    "words": [
      {"index": 0, "word": "辕", "start": 0.0, "end": 0.42,
       "deviation_cents": 12.3, "warning": false}
    ],
    "cdm_tags": [
      {"id": "d1", "label": "气息支撑不足", "severity": "low",
       "confidence": 0.81, "category": "气息", "evidence": "…", "features": null}
    ]
  }
}
```

- `submission.status` 的归一化与 4.1 相同（列值 NULL 按 `submitted`）。
- `segment_ids`：`homeworks.segment_ids` 原样（顺序保持教师选择顺序）；为空数组表示按整曲。
- `allowed_segment_ids`：与当前 `segments` 表求交后的实际可选集合，按 `seq` 升序；
  - `segment_ids` 非空 → 只保留仍存在的那些；
  - `segment_ids` 为空 → 该曲目当前全部分段；
  - `demo_id` 为空 → 空数组。
- `can_submit`：`submission == null` 且 `allowed_segment_ids` 非空。
- `submission.words` 复用 F5 的 `LyricWord` 形状（`ai_detail.words`，缺失出 `[]`）；`cdm_tags` 复用 `CdmTag`（`ai_detail.defects` 全量、按置信度降序，缺失出 `[]`）。`segment_id` 来自 3.2 新增的列；历史行没有该列值时为 `null`。
- **不返回 `dimensions` / `timeline` / `regions`**：这些只存在于 redis 的 B4 结果里（TTL 1 小时），`ai_detail` 按文档只存逐字与 CDM。分析完成当时，跟唱页用 B4 展示五维；回看时只有总分、逐字与 CDM。这是有意的口径，不把整份 B4（最多 1500 个时间轴点）塞进 JSONB。

### 4.3 `POST /api/homeworks/<int:homework_id>/submit`（F3）

- 权限：`@login_required` + `@student_required`。
- 请求：`multipart/form-data`（与 D1 一致，前端已有 `apiPostForm`）
  - `segment_id`：必填，整数
  - `audio_id`：必填，整数，B1 返回的 `file_id`
- 处理顺序（全部校验通过才落库）：

  1. `user_id → students.id`；无档案 → 403。
  2. 作业不存在 → 404「作业不存在」。
  3. `audio_id` 不存在 → 404「音频不存在」；`uploader_id != user_id` → 403「只能提交本人录音」（同 D1）。
  4. 解析 `allowed_segment_ids`（同 4.2）；`segment_id` 不在集合内 → 422「唱段不在本次作业范围内」；集合为空 → 422「该作业没有可提交的唱段」。
  5. 已有该学生该作业的提交 → 422「该作业已提交，不能重复提交」。
  6. 插入 `Submission(homework_id, student_id, segment_id, audio_id, status='submitted')` 并 `flush()`；`IntegrityError`（并发撞唯一索引）→ `rollback()` 后 422 同上文案。
  7. `analyze_service.submit(db, AnalyzeSubmitIn(segment_id=..., student_audio_id=audio_id), persist={"kind": "homework", "submission_id": sub.id})`。
  8. 第 7 步抛任何异常（含分段没绑示范音频的 404、broker 不可达等）→ 删除占位行、commit、原样抛出，避免留下一条永远「分析中」的提交。成功 → `db.commit()`，返回 `{"task_id": "..."}`。

  先 `flush` 拿 id、再派发、最后 `commit`：派发失败时占位行还没提交，可以干净删除；派发成功但 `commit` 失败时，worker 末尾找不到提交行会把任务置 `failed`，不会写出错误数据。`save_result` 在分析结束前才执行，正常情况下远晚于这次 `commit`。

- 说明：`analyze_service.submit` 内部会再次校验分段与教师轨（404「片段不存在或未绑定示范音频」），这是 F3 之外的第二道闸门，不重复实现音轨查找逻辑。

### 4.4 错误码

| 场景 | HTTP / code |
|---|---|
| 未登录 | 401 |
| 教师调学生接口 | 403 |
| 学生无档案 | 403 |
| 作业不存在 | 404 |
| 音频不存在 | 404 |
| 音频不属于本人 | 403 |
| 唱段不在作业范围 / 作业无可提交唱段 | 422 |
| 已提交（含并发） | 422 |
| 缺表单字段或不是整数 | 400 |
| 分段没绑示范音频 | 404（由 `analyze_service.submit` 抛出） |

## 5. 后端实现

### 5.1 文件与函数

| 文件 | 改动 |
|---|---|
| `schema.sql` | `submissions` 加 `segment_id INT`（无外键，带注释）；末尾加 `CREATE UNIQUE INDEX uq_submissions_homework_student ON submissions(homework_id, student_id);` |
| `app/models/homework.py` | `Submission.segment_id`（`Integer`，无 FK）；`__table_args__` 加同名唯一索引 |
| `scripts/add_submission_segment_id.sql` | 新增，`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` |
| `scripts/add_submission_unique_index.sql` | 新增，`CREATE UNIQUE INDEX IF NOT EXISTS`；执行前先查重（本机已确认无重复） |
| `app/repositories/homeworks_repo.py` | 新增 `get_homeworks_with_submission(db, student_id)`、`get_homework_with_submission(db, homework_id, student_id)`、`get_submission_for_student(db, homework_id, student_id)`、`add_submission(db, sub)`（只 flush）。`get_progress_rows` / `get_submission_stats` 里「表上没有唯一约束、所以要去重」的注释同步改为「历史数据可能重复，去重保留为防御；2026-10-21 起有唯一索引」 |
| `app/schemas/homework.py` | 新增 `StudentHomeworkItem` / `StudentHomeworkListResponse` / `StudentHomeworkDetail` / `StudentSubmissionBrief` / `StudentSubmissionDetail` |
| `app/services/homework_service.py` | 新增 `list_my_homeworks`、`my_homework_detail`、`submit_homework`、`save_result`（worker 用）、`discard_pending`（worker 失败用）、`_allowed_segment_ids`、`_student_id_or_403` |
| `app/api/homeworks.py` | 新增两条 GET；F3 桩替换为真实实现（路由参数改为 `<int:homework_id>`）；加本地 `_form_int` |
| `app/services/analyze_service.py` | `practice` 形参改名 `persist`；末尾按 `persist["kind"]` 分派到 `practice_service.save_result` 或 `homework_service.save_result`；失败分支调用 `homework_service.discard_pending` |
| `app/services/practice_service.py` | `submit` 的 metadata 加 `"kind": "practice"`；`_update_bkt` 改为公开的 `apply_bkt(db, *, student_id, dimensions, source_type, source_id) -> (before, after)`，`save_result` 调用它但忽略返回值 |

`analyze_service` 对 `persist` 的分派放在现有 `if practice:` 的位置（`analyze_service.py:328-330`），函数内惰性 import，避开循环导入：

```python
if persist:
    kind = persist.get("kind", "practice")   # 老任务没有 kind，默认练习
    if kind == "homework":
        from app.services import homework_service
        homework_service.save_result(persist, result)
    else:
        from app.services import practice_service
        practice_service.save_result(persist, result)
```

`run_analysis` 的 `except` 分支在写 `failed` 状态之后做一次 best-effort 清理：`persist["kind"] == "homework"` 时调用 `homework_service.discard_pending(persist)`，自身包一层 try/except 并记日志——清理失败不能掩盖原始失败。先写失败状态再清理，是为了即使清理抛错，前端也能拿到 `failed`。

### 5.2 worker 成功落库

`homework_service.save_result(metadata, result)` 用 `session_scope()`（请求之外，不能用 `get_db()`）：

1. 按 `metadata["submission_id"]` 取行；不存在 → 抛 `BusinessError(500, ...)`。
2. 若 `status != 'submitted'` → 抛错（重复任务或已被处理），由 `run_analysis` 置 failed；`discard_pending` 的 `status='submitted'` 守卫确保不会删掉已评分的行。
3. `before, after = practice_service.apply_bkt(db, student_id=sub.student_id, dimensions=result.get("dimensions"), source_type="homework", source_id=sub.id)`。
4. 写回：

```python
sub.ai_score = result.get("overall")
cdm = result.get("cdm") or {}
sub.ai_detail = {
    "words": result.get("words"),
    "defects": cdm.get("defects") if cdm else None,
    "overallConfidence": cdm.get("overallConfidence") if cdm else None,
}
sub.bkt_before = before
sub.bkt_after = after
sub.status = "ai_scored"
```

`ai_detail` 与既有 5 条种子提交同形（`defects` / `overallConfidence` 两个键），并补上 F5 已经在读的 `words`；**不写 `featureMatrix`**（B4 没有这个数据源，F5 的 `feature_matrix` 仍为 `None`），**不写 `dimensions`**（见 4.2）。

BKT：`apply_bkt` 的规则与 D1 完全一致（先验 0.5、学习率 0.3、confidence +0.05、维度→技法五条映射），只把写 `bkt_history` 的两列换成 `source_type='homework'`、`source_id=submissions.id`。`before` / `after` 只包含本次真正更新了的技法（维度分非数值的跳过），形状是 `{"音准控制": 0.5, ...}`，正好是 F5 `_bkt_changes` 读取的扁平字典。

### 5.3 worker 失败清理

`discard_pending(metadata)`：

```python
with session_scope() as db:
    sub = db.get(Submission, metadata.get("submission_id"))
    if sub is not None and sub.status == "submitted" and sub.ai_score is None:
        db.delete(sub)
```

删除后学生可重交。若 `save_result` 已经成功、只是 redis 的 `done` 写失败，行的 `status` 已是 `ai_scored`，不会被删——代价是学生看到「分析失败」但作业已算分，重交会 422。这是极窄的窗口，按「不丢已算出的成绩」处理。

## 6. 前端：`my_homework.html`

新页面，单文件自包含，复制现有学生页的 `:root` 设计 token、顶部栏、侧边栏与登录条。

### 6.1 布局

- 左侧作业卡片列表，右侧详情面板（与 `homework.html` 的「列表 + 详情」同构，但只读 + 一个「去完成」按钮）。
- 顶部筛选/计数不做；页面标题「我的作业」，副标题显示「待完成 N 份」。

### 6.2 卡片

| 元素 | 内容 |
|---|---|
| 标题 | `title` |
| 曲目 | `demo_title`，为空显示「未挂曲目」 |
| 截止 | `deadline`，为空显示「未设截止」 |
| 状态徽标 | `todo` → 待完成；`submitted` → 分析中；`ai_scored` → 待批改；`reviewed` → 已批改；`overdue=true` 另加红色「已逾期」徽标（无论是否已提交都显示） |
| 分数 | `submission.teacher_score ?? submission.ai_score`，无则「—」 |

### 6.3 详情

- 标题、曲目、截止日、重点技法 chips（`focus_skills`，空则「未指定」）。
- 唱段：显示 `segment_count`；详情接口不返回段名，页面按 `allowed_segment_ids.length` 显示「可选 N 段」。
- 已提交：显示提交时间、AI 分、教师分与评语、逐字偏差表（`words`，字段与 F5 页面同色规则：绿 <20c / 黄 20–50c / 红 >50c）、CDM 标签（`cdm_tags`）。
- 主按钮：
  - `can_submit=true` → 「去完成」，`location.href = 'sing_along.html?homework_id=<id>'`；
  - `can_submit=false` 且有提交 → 「已提交」，禁用；
  - `can_submit=false` 且无提交 → 「暂无可提交唱段」，禁用。
- 逾期提示：`overdue=true` 且无提交时，按钮旁写「已逾期，仍可提交」。

### 6.4 取数

- `init()` → `GET /api/homeworks/mine`；`fetch` 401 → `location.replace('/login.html')`；403 → 渲染「我的作业仅学生可见」并隐藏列表（同 `demo_library.html` 对学生身份的处理）。
- 选中卡片 → `GET /api/homeworks/mine/<id>`；切换卡片时丢弃旧响应（请求令牌，防竞态）。
- 所有库内文本用 `textContent` 或现有 `escapeHtml`，不拼 `innerHTML`。

## 7. 前端：`sing_along.html` 作业模式

### 7.1 URL 参数与初始化

- `const homeworkId = Number(new URLSearchParams(location.search).get('homework_id')) || null;`
- 有 `homework_id` 时，`init()` 先 `GET /api/homeworks/mine/<id>`，再加载 C1/C2：
  - 曲目锁定为 `homework.demo_id`；`loadDemos()` 不再自动选第一条，改为选中该 id；
  - `segments` 过滤为 `allowed_segment_ids`（保持 C2 的 `seq` 顺序）；
  - 不自动选段，仍由学生点选（避免默认把某一段当成本次作业）。
- 取详情失败：列表/详情页能进来说明作业存在；这里只可能是网络或权限（教师打开带参 URL → 403），显示提示并退回普通跟唱模式。

### 7.2 作业条

在录音区上方加一条常驻横幅（默认隐藏）：

- 作业标题、截止日、「已逾期」徽标、重点技法；
- 状态文案：可提交 / 分析中 / 已提交（AI 分 X）/ 已批改（教师分 X）。

### 7.3 录音与提交

`analyzeRecording()` 在 B1 上传后分叉：

```js
const subForm = new FormData();
subForm.append("segment_id", String(seg.id));
subForm.append("audio_id", String(up.file_id));
const sub = homeworkMode
  ? await apiPostForm(`/api/homeworks/${homeworkId}/submit`, subForm)
  : /* 原 D1：追加 duration_sec 后 POST /api/practice/submit */;
```

作业模式下：

- F3 成功 → `homeworkSubmitted = true`，横幅显示「已提交，AI 分析中…」，录音按钮禁用；继续用现有 `pollAnalysis` 轮询 B3/B4。B4 返回后照常 `renderAnalysisResult`，横幅显示「已提交（AI 分 X）」。
- B3 返回 `failed` → 横幅显示失败原因，`homeworkSubmitted = false`，允许重试（worker 已删除占位行）。
- F3 回 422「已提交」→ 视为已提交：禁用录音并刷新详情（处理「刷新页面后重交」的竞态）。
- 页面加载时详情里已有 `submission` → 只读模式：禁用录音与选段提交，横幅显示分数与状态；仍可播放示范与查看唱词。
- 不调用 D3 `loadLastPractice`（作业模式结果以本次提交为准，避免把练习记录误认成作业成绩）；普通模式保持原样。

`stopAll()` 的既有行为会触发 `mediaRecorder.onstop` 从而上传——作业模式下与普通模式一致，不额外改。

## 8. 导航与页面注册

- `app/pages.py` 的 `PROTECTED_PAGES` 加 `"my_homework"`；模块 docstring 的页面数从 14 改为 15。
- 所有带学生导航组的页面，在学生组「实时跟唱」之前加一项：
  `<a href="my_homework.html" class="nav-item"><span class="icon">📝</span>我的作业</a>`
  涉及 11 个文件：`dashboard.html`、`tracking.html`、`recommendation.html`、`homework.html`、`demo_library.html`、`annotation.html`、`cdm_report.html`、`knowledge_graph.html`、`sing_along.html`、`AI_teacher.html`、`cat_test.html`（行号见调研记录；以各页学生组实际位置为准）。`my_homework.html` 自身标 `active`。

## 9. 文档与运维同步

- `DOC_ISSUES.md` 新增第 46 条：F3 契约、学生作业列表/详情接口、`submissions.segment_id`、唯一索引、整曲作业降级、逾期口径。
- `CLAUDE.md`：
  - 「运行方式」补学生作业链路（F3 需要 Celery worker；`my_homework.html` 经 HTTP 访问）。
  - 「架构」补 `my_homework.html` 的常量/数据源（全部真接口，无 mock）。
  - 数据库一节把 `check_db.py` 的「15 表 / 111 列 / 23 外键 / 2 索引」更新为「15 表 / 112 列 / 23 外键 / 3 索引」。
- `scripts/smoke_homework_submit.sh` 新增（见 10.1）。

## 10. 测试与验收

### 10.1 后端冒烟 `scripts/smoke_homework_submit.sh`

前置：后端 + **Celery default worker**（`celery -A app.worker:celery_app worker -n default@%h --concurrency=2`）+ 一段真实录音（沿用 `smoke_analyze.sh` 的 `AUDIO_DIR` / `AUDIO_FILE`）。单轮约 2 分钟。

覆盖：

1. 权限：匿名访问两条 GET 与 F3 → 401；教师 → 403。
2. 列表：学生 `GET /mine` → 200 且含教师刚布置的作业（F2 建）。
3. 详情：404（不存在）、`allowed_segment_ids` 与作业 `segment_ids` 一致。
4. F3 校验：缺字段 → 400；音频不存在 → 404；用另一学生的 `audio_id` → 403；不在作业范围的 `segment_id` → 422。
5. 成功路径：B1 上传 → F3 → 200 且返回 `task_id`；立即再提交 → 422；B3 轮询到 `done`。
6. 落库校验（直连库）：`submissions` 一行，`status='ai_scored'`、`ai_score` 非空、`ai_detail` 含 `words`/`defects`/`overallConfidence`、`segment_id`/`audio_id` 正确、`bkt_before`/`bkt_after` 非空且键为技法名；`bkt_history` 新增 5 行 `source_type='homework'`、`source_id=submission.id`。
7. 教师端回显：F4 `GET /homeworks/<id>/submissions` 能看到该提交；F5 详情的 `lyrics` 与 B4 `words` 一致。所选示范没有 `lyrics_json` 时两边都是空数组（Demucs 路径的曲目本来就没有逐字数据），脚本按该段是否有歌词分别断言，不硬写「非空」。
8. 清理：按 EXIT trap 删除 `bkt_history`（按 source_type/source_id）、`submissions`、F2 建的 `homeworks`、B1 的 `audio_files` 行与磁盘文件。脚本可重复执行。

### 10.2 前端验证

用 `/browse`：

- 学生登录 → `my_homework.html` 列表与详情渲染真实数据；教师访问显示「仅学生可见」。
- 点「去完成」→ URL 带 `homework_id`，跟唱页曲目锁定、分段只剩作业范围、横幅显示正确。
- 已有提交的作业进入跟唱页 → 录音按钮禁用、横幅显示分数。
- 录音提交链路（`getUserMedia`）若浏览器无麦克风权限，以后端冒烟脚本为准，页面侧只验到「点击后按钮禁用、请求发出」。

### 10.3 其他

- `python scripts/check_db.py` 通过（执行两个迁移脚本后）。
- `node --check` 通过 `my_homework.html` 与 `sing_along.html` 的脚本块。
- `scripts/smoke_homework_create.sh` / `smoke_analyze.sh` / `smoke_auth.sh` 回归通过。

## 11. 已知限制（写进 DOC_ISSUES 第 46 条）

1. 一份作业只收一次提交；多段作业只评学生选中的那一段，其余唱段不进 `submissions`。
2. 整曲作业（`segment_ids=[]`）退化为「任选一段」；曲目无分段时无法提交。
3. `submissions.segment_id` 不设外键，重解析后可能悬空。
4. 回看只有总分、逐字与 CDM；五维/时间轴/区域只在分析完成当次的 B4 结果里（redis TTL 1 小时）。
5. `submitted_at` 沿用库内 `NOW()`（UTC）；逾期判定与教师端一样按「UTC 日期 > deadline」比较，跨零点的极端情况会与北京时间直觉差一天。这是既有时间区口径，不在本轮修。
6. 无「重交/补交」「教师退回」「作业关闭」「班级维度」。
7. 唯一索引上线前的历史数据已确认无重复；若别的环境有重复行，迁移脚本会失败，需先人工清理（脚本头部写明）。

## 12. 实施顺序

1. `schema.sql` + 模型 + 两个迁移 SQL → 跑 `check_db.py`。
2. `analyze_service` 的 `persist` 改名与分派 + `practice_service.apply_bkt` 重构（保持 D1 行为不变，先跑 `smoke_analyze.sh`）。
3. `homeworks_repo` 查询/写入 + schemas + `homework_service` 的三个学生接口与 worker 落库/清理。
4. `app/api/homeworks.py` 两条 GET + F3。
5. `scripts/smoke_homework_submit.sh`，后端全绿。
6. `my_homework.html` + `pages.py` + 11 页导航。
7. `sing_along.html` 作业模式。
8. `/browse` 前端验证 + 回归三个既有冒烟脚本。
9. `DOC_ISSUES.md` 第 46 条、`CLAUDE.md`。
