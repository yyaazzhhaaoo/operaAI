# 学生提交作业（我的作业页 + 跟唱作业模式 + F3）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让学生能看到自己的作业、进入跟唱页录制作业音频，F3 复用 B2 分析管线评分并把结果落进 `submissions`，教师端 F1/F4/F5 自动看到这条提交。

**Architecture:** 后端新增两条只读学生接口与真实 F3。F3 当场插入 `status='submitted'` 的占位行，`analyze_service` 按 `persist["kind"]` 把 worker 结果分派给 `homework_service.save_result` 原位回填成 `ai_scored`；失败时删除仍处于 `submitted` 且未评分的占位行。前端新增 `my_homework.html`（列表 + 详情 +「去完成」），`sing_along.html` 增加 `?homework_id=` 作业模式，复用现有录音与 B1/B3/B4 链路。

**Tech Stack:** Python 3.11 / Flask 3.1 / SQLAlchemy 2 / PostgreSQL 15 / Celery + redis / Pydantic v2；前端是单文件自包含 HTML + 原生 JS。

**Spec:** `docs/superpowers/specs/2026-10-21-student-homework-submission-design.md`

## Global Constraints

- 所有文档、注释、commit message 用简体中文；变量名、函数名、类名保持英文；UTF-8。
- Python 3.11；依赖清单是 `requirements.txt`。**不引入 Alembic**：表结构真源是 `schema.sql`，迁移 SQL 手工执行。
- 接口统一信封 `{"code","message","data"}`（`app/response.py` 的 `ok`/`fail`）；业务错误抛 `BusinessError(code, message)`，Pydantic `ValidationError` 由全局 handler 转 422。
- 仓储层写操作只 `db.flush()`，不 `commit`；事务边界在 service。`SessionLocal` 是 `autoflush=False`。
- `/api` 前缀只在 `app/api/__init__.py` 的 `url_prefix` 里写一次，路由一律写相对路径。
- 页面全部经 HTTP 访问、受登录保护；不要用 `file://` 打开。
- 网页浏览只用 `/browse` 技能，**禁止** `mcp__claude-in-chrome__*`。
- 无 pytest：验证靠冒烟脚本、直连库查询、`node --check`、`/browse`。
- 不修改 `../艺校_docs/` 下的需求文档；口径问题登记在 `DOC_ISSUES.md`（第 46 条已存在，本计划只核对不重写）。
- **`scripts/check_db.py` 在本计划开始前已经是红的**：真库多 `demo_versions` 表、`teacher_demos` 多 `parse_time_sec/parse_status/techniques_json` 三列，都是本次之前的历史漂移（实测 `15 张表 / 106 列 / 23 外键 / 2 索引`）。本计划的验收标准是「`submissions` 相关差异消失、列数 106→107、索引数 2→3」，**不是全绿**；不要顺手修那两处无关漂移。

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `schema.sql` | 修改 | `submissions` 加 `segment_id`；加唯一索引 |
| `app/models/homework.py` | 修改 | `Submission.segment_id` 映射 + 同名唯一索引 |
| `scripts/add_submission_segment_id.sql` | 创建 | 真库加列（`IF NOT EXISTS`） |
| `scripts/add_submission_unique_index.sql` | 创建 | 真库加唯一索引（附查重 SQL） |
| `app/repositories/homeworks_repo.py` | 修改 | 学生作业查询、提交查询、提交插入 |
| `app/schemas/homework.py` | 修改 | 学生列表/详情/提交出参模型 |
| `app/services/practice_service.py` | 修改 | `apply_bkt` 公共化；D1 的 metadata 加 `kind` |
| `app/services/analyze_service.py` | 修改 | `practice` 形参改名 `persist`；按 `kind` 分派；失败清理 |
| `app/services/homework_service.py` | 修改 | 学生列表/详情/F3；worker 成功落库与失败清理 |
| `app/api/homeworks.py` | 修改 | 两条 GET + F3 真实实现 |
| `scripts/smoke_homework_submit.sh` | 创建 | 端到端冒烟（约 2 分钟） |
| `my_homework.html` | 创建 | 学生作业列表 + 详情 + 入口 |
| `app/pages.py` | 修改 | 注册 `my_homework.html` |
| `dashboard.html` 等 11 页 | 修改 | 学生导航加「我的作业」 |
| `sing_along.html` | 修改 | 作业模式 |
| `CLAUDE.md` | 修改 | 运行方式、架构、`check_db` 计数 |
| `DOC_ISSUES.md` | 核对 | 第 46 条已写好，不重写 |

---

### Task 1: 数据库列、唯一索引与模型

**Files:**
- Modify: `schema.sql:131-147`
- Modify: `app/models/homework.py:3, 32-60`
- Create: `scripts/add_submission_segment_id.sql`
- Create: `scripts/add_submission_unique_index.sql`

**Interfaces:**
- Produces: `submissions.segment_id INT`（无外键）、唯一索引 `uq_submissions_homework_student (homework_id, student_id)`；后续任务用 `Submission.segment_id` 与 `homeworks_repo.add_submission`。

- [ ] **Step 1: 修改 `schema.sql` 的 submissions 表**

在 `audio_id INT REFERENCES audio_files(id),` 下一行加：

```sql
  segment_id INT,                          -- 学生提交的唱段（无外键，见下方索引注释）
```

在 `submissions` 的建表语句之后（`chat_messages` 之前）加：

```sql
-- 一份作业每个学生只能提交一次（2026-10-21，F3）。教师端「提交人数」本来就按
-- (homework_id, student_id) 去重，这个索引把页面口径变成库级事实。
--
-- submissions.segment_id 刻意不设外键：library_repo.replace_segments 会按 demo_id
-- 整批删除旧分段再插入，外键会让「重新解析一个已经有作业提交的曲目」直接失败。
-- 分段被重解析后这个 id 可能悬空；它与 homeworks.segment_ids 的 JSONB 一样，
-- 是历史引用而不是强引用。
CREATE UNIQUE INDEX uq_submissions_homework_student
  ON submissions(homework_id, student_id);
```

- [ ] **Step 2: 修改 `app/models/homework.py`**

第 3 行 import 加 `Index, Integer`：

```python
from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, func, text
```

`Submission` 里 `audio_id` 之后加：

```python
    segment_id: Mapped[int | None] = mapped_column(Integer)
```

`reviewed_at` 之后、`homework` relationship 之前加：

```python
    __table_args__ = (
        Index(
            "uq_submissions_homework_student",
            "homework_id",
            "student_id",
            unique=True,
        ),
    )
```

- [ ] **Step 3: 创建 `scripts/add_submission_segment_id.sql`**

```sql
-- submissions 增加 segment_id（2026-10-21，F3 学生提交作业）
--
-- 普通 INT，**故意不加外键**：重解析曲目时 library_repo.replace_segments 会
-- 先按 demo_id 整批删除旧分段再插入，外键会让这次删除直接失败。分段被重解析
-- 后本列可能悬空，它与 homeworks.segment_ids 的 JSONB 一样是历史引用。
--
-- 在真库手工执行（项目不用 Alembic）：
--   psql -U xiyun -d xiyun -f scripts/add_submission_segment_id.sql

ALTER TABLE submissions ADD COLUMN IF NOT EXISTS segment_id INT;

COMMENT ON COLUMN submissions.segment_id IS
  '学生提交的唱段 segments.id（无外键；重解析后可能悬空）';

-- 回滚：
-- ALTER TABLE submissions DROP COLUMN IF EXISTS segment_id;
```

- [ ] **Step 4: 创建 `scripts/add_submission_unique_index.sql`**

```sql
-- 一份作业每个学生只能提交一次（2026-10-21，F3）
--
-- 执行前先查重；本机已确认无重复。若别的环境有重复行，CREATE UNIQUE INDEX
-- 会失败，必须先人工清理（保留哪一条由业务决定，脚本不猜）：
--   SELECT homework_id, student_id, count(*)
--   FROM submissions GROUP BY 1, 2 HAVING count(*) > 1;
--
-- 在真库手工执行（项目不用 Alembic）：
--   psql -U xiyun -d xiyun -f scripts/add_submission_unique_index.sql

CREATE UNIQUE INDEX IF NOT EXISTS uq_submissions_homework_student
  ON submissions(homework_id, student_id);

-- 回滚：
-- DROP INDEX IF EXISTS uq_submissions_homework_student;
```

- [ ] **Step 5: 在真库执行两个迁移脚本**

本项目没有本地 `psql`/Docker（`.env` 的库在 192.168.31.217），用项目 venv 的 SQLAlchemy 执行：

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from sqlalchemy import text
from app.db import engine

for name in ("add_submission_segment_id.sql", "add_submission_unique_index.sql"):
    sql = Path("scripts", name).read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.execute(text(sql))
    print("已执行", name)
PY
```

预期输出：

```
已执行 add_submission_segment_id.sql
已执行 add_submission_unique_index.sql
```

- [ ] **Step 6: 核对列与索引真的存在**

```bash
.venv/bin/python - <<'PY'
from sqlalchemy import inspect
from app.db import engine

insp = inspect(engine)
print("segment_id:", [c["name"] for c in insp.get_columns("submissions") if c["name"] == "segment_id"])
print("indexes:", sorted(i["name"] for i in insp.get_indexes("submissions")))
PY
```

预期（顺序可能不同）：

```
segment_id: ['segment_id']
indexes: ['uq_submissions_homework_student']
```

- [ ] **Step 7: 跑 `check_db.py`，只盯 submissions 与计数**

```bash
.venv/bin/python scripts/check_db.py
```

预期输出**包含**这两行，且**不出现** `submissions 列名差异` / `submissions 索引差异`：

```
比对范围：15 张表 / 107 列 / 23 个外键 / 3 个自定义索引
结果：有差异 ✗
  - 表集合不一致：真库独有={'demo_versions'} 模型独有=无
  - teacher_demos 列名差异：真库独有={'parse_status', 'parse_time_sec', 'techniques_json'} 模型独有=无
```

如果 `submissions` 出现在差异列表里，先修本任务，不要继续。

- [ ] **Step 8: 提交**

```bash
git add schema.sql app/models/homework.py scripts/add_submission_segment_id.sql scripts/add_submission_unique_index.sql
git commit -m "feat: submissions 增加 segment_id 与作业提交唯一索引

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: 抽出 `apply_bkt`，`analyze_service` 按 `persist.kind` 分派

**Files:**
- Modify: `app/services/practice_service.py:63-95, 140-200`
- Modify: `app/services/analyze_service.py:94-130, 190-245, 325-330`

**Interfaces:**
- Consumes: 无。
- Produces:
  - `practice_service.apply_bkt(db, *, student_id, dimensions, source_type, source_id) -> tuple[dict, dict]`：返回 `(before, after)`，两个都是「技法名 → P(L)」扁平字典，只含本次真正更新的技法。
  - `analyze_service.submit(db, data, *, persist: dict | None = None) -> str`；`persist` 为 `{"kind": "practice", ...}` 或 `{"kind": "homework", "submission_id": int}`。
  - `analyze_service.run_analysis(..., persist: dict | None = None)` 在失败分支调用 `homework_service.discard_pending(persist)`。

- [ ] **Step 1: 改 `practice_service.submit` 的 metadata**

把 `practice={` 改成 `persist={`，并加 `kind`：

```python
    task_id = analyze_service.submit(
        db,
        AnalyzeSubmitIn(segment_id=segment_id, student_audio_id=audio_id),
        persist={
            "kind": "practice",
            "student_id": student_id,
            "segment_id": segment_id,
            "audio_id": audio_id,
            "duration_sec": duration_sec,
        },
    )
```

- [ ] **Step 2: 把 `_update_bkt` 改成公开的 `apply_bkt`**

把 `practice_service.py` 第 174-200 行的 `_update_bkt` 整段替换为：

```python
def apply_bkt(
    db: Session,
    *,
    student_id: int,
    dimensions: dict | None,
    source_type: str,
    source_id: int,
) -> tuple[dict, dict]:
    """按维度分数移动掌握度，返回 (本次更新前, 本次更新后) 的 P(L) 字典。

    规则是临时口径（DOC_ISSUES 第 44 条），第 4 周标定时替换。D1 练习与
    F3 作业提交共用这一份，只有 `source_type` / `source_id` 不同：两处各写
    一套的话，同一份 B4 结果会在两条链路里推出不同的掌握度。

    `before` / `after` 只包含本次真正更新了的技法（维度分非数值的跳过），
    形状是「技法名 → P(L)」的扁平字典，正好是 F5 `_bkt_changes` 读取的形状。
    """
    before: dict = {}
    after: dict = {}
    dims = dimensions if isinstance(dimensions, dict) else {}

    for dimension, skill in _SKILL_BY_DIMENSION.items():
        score = dims.get(dimension)
        # bool 是 int 的子类；JSONB 里的字符串/"80" 也不能当分数用。
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            continue

        previous = bkt_history_repo.get_latest_for_student_skill(
            db, student_id, skill
        )
        old_p_l = previous.p_l if previous else _BKT_PRIOR
        new_p_l = old_p_l + _BKT_LEARNING_RATE * (score / 100.0 - old_p_l)
        old_confidence = (
            previous.confidence
            if previous is not None and previous.confidence is not None
            else _BKT_PRIOR
        )

        before[skill] = old_p_l
        after[skill] = min(1.0, max(0.0, new_p_l))
        db.add(BktHistory(
            student_id=student_id,
            skill=skill,
            p_l=after[skill],
            confidence=min(1.0, old_confidence + _BKT_CONFIDENCE_STEP),
            source_type=source_type,
            source_id=source_id,
        ))
    return before, after
```

把 `save_result` 末尾的 `_update_bkt(db, record)` 改成：

```python
        db.flush()
        apply_bkt(
            db,
            student_id=record.student_id,
            dimensions=record.dimensions_json,
            source_type="practice",
            source_id=record.id,
        )
```

- [ ] **Step 3: `analyze_service.submit` 的形参改名**

第 94-96 行：

```python
def submit(
    db: Session, data: AnalyzeSubmitIn, *, persist: dict | None = None
) -> str:
```

第 127-130 行的注释与调用改成：

```python
    # persist 非空时表示这次任务完成后要落库：D1 练习写 practice_records，
    # F3 作业回填 submissions。它必须随 Celery 消息序列化过去，所以只装
    # int/float/str 这类纯数据。
    _dispatch(task_id, t_path, s_path, lyrics, persist)
    return task_id
```

- [ ] **Step 4: `_dispatch` 与 `run_analysis` 的形参改名，并加失败清理**

`_dispatch` 签名与 `apply_async`：

```python
def _dispatch(
    task_id: str,
    t_path: Path,
    s_path: Path,
    lyrics: list | None,
    persist: dict | None,
) -> None:
```

```python
    run_analysis.apply_async(
        args=(task_id, str(t_path), str(s_path), lyrics, persist),
        task_id=task_id,
    )
```

`run_analysis` 签名：

```python
def run_analysis(
    task_id: str,
    t_path: str,
    s_path: str,
    lyrics: list | None,
    persist: dict | None = None,
) -> None:
```

`run_analysis` 的 `except` 分支在写完 `failed` 之后调用清理：

```python
        try:
            task_repo.update(task_id, status="failed", message=message)
        except Exception:
            # 连状态都写不进去（redis 挂了），只能记日志——此时已无路可退。
            logger.exception("分析任务 %s 的失败状态写入 redis 也失败了", task_id)

        _discard_pending_homework(persist)
```

在 `run_analysis` 之后加：

```python
def _discard_pending_homework(persist: dict | None) -> None:
    """作业提交分析失败时删掉 F3 建的占位行，让学生能重交。

    清理是 best-effort：它自己出错不能掩盖原始失败，也不能让任务停在 queued。
    所以调用点先写 failed，再调这里，而且这里整体兜异常。
    """
    if not persist or persist.get("kind") != "homework":
        return
    try:
        from app.services import homework_service
        homework_service.discard_pending(persist)
    except Exception:
        logger.exception(
            "分析失败后清理作业占位提交失败：submission_id=%s",
            persist.get("submission_id"),
        )
```

- [ ] **Step 5: `_analyze` 的形参与落库分派**

`_analyze` 签名改成 `persist: dict | None = None`。第 325-330 行替换为：

```python
    # 先落库再报 done。反过来写的话，一旦落库失败，前端会看到一个已完成的
    # 分数，而库里没有对应行。函数内 import 是为了避开
    # homework_service → analyze_service 的循环导入。
    if persist:
        kind = persist.get("kind", "practice")   # 老任务没有 kind，默认练习
        if kind == "homework":
            from app.services import homework_service
            homework_service.save_result(persist, result)
        else:
            from app.services import practice_service
            practice_service.save_result(persist, result)
```

- [ ] **Step 6: 语法与导入检查**

```bash
.venv/bin/python -c "import app.services.analyze_service, app.services.practice_service; print('imports ok')"
```

预期：`imports ok`。

- [ ] **Step 7: 回归 B2（不落库路径）**

```bash
scripts/smoke_analyze.sh
```

预期最后一行是 `全部通过：<N> 项`。这一步同时证明 `persist` 改名没有影响 B2 的 `submit(db, data)` 调用。

- [ ] **Step 8: 回归 D1（落库路径，eager Celery）**

```bash
TD=$(mktemp -d)
cat > "$TD/check_d1.py" <<'PY'
from pathlib import Path

from sqlalchemy import func, select

from app import create_app
from app.db import session_scope
from app.models import AudioFile, BktHistory, PracticeRecord, Segment, Student, TeacherDemo, User

AUDIO = Path.home() / "Desktop/test_audio/01_xipi_1931.wav"
assert AUDIO.is_file(), f"缺少测试音频：{AUDIO}"

with session_scope() as s:
    student = s.scalar(
        select(Student).join(User, User.id == Student.user_id).where(User.username == "stu001")
    )
    seg_id = s.scalar(
        select(Segment.id)
        .join(TeacherDemo, TeacherDemo.id == Segment.demo_id)
        .where((Segment.audio_id.is_not(None)) | (TeacherDemo.audio_id.is_not(None)))
        .order_by(Segment.id).limit(1)
    )
    assert student and seg_id, "库里有学生/绑定教师轨的分段才能跑"
    student_id = student.id
    # 只清理「本次新增」的记录：按 id 水位线取，不碰历史练习
    max_id = s.scalar(select(func.max(PracticeRecord.id))) or 0

app = create_app({"TESTING": True, "CELERY": {"task_always_eager": True}})
c = app.test_client()
r = c.post("/api/auth/login", json={"username": "stu001", "password": "xiyun@2026"})
assert r.status_code == 200, r.get_data(as_text=True)
with AUDIO.open("rb") as f:
    r = c.post("/api/audio/upload", data={"audio": (f, "d1.wav")}, content_type="multipart/form-data")
assert r.status_code == 200, r.get_data(as_text=True)
file_id = r.get_json()["data"]["file_id"]
r = c.post("/api/practice/submit", data={"segment_id": seg_id, "audio_id": file_id})
assert r.status_code == 200, r.get_data(as_text=True)
task_id = r.get_json()["data"]["task_id"]
r = c.get(f"/api/analyze/status/{task_id}")
assert r.get_json()["data"]["status"] == "done", r.get_data(as_text=True)

with session_scope() as s:
    recs = list(s.scalars(
        select(PracticeRecord).where(
            PracticeRecord.id > max_id,
            PracticeRecord.student_id == student_id,
            PracticeRecord.segment_id == seg_id,
        )
    ).all())
    assert len(recs) == 1, f"本次应只新增 1 条练习记录，实际 {len(recs)}"
    rec = recs[0]
    assert rec.ai_score is not None
    bkt = s.query(BktHistory).filter(
        BktHistory.source_type == "practice", BktHistory.source_id == rec.id
    ).count()
    assert bkt == 5, bkt
    rec_id = rec.id
    audio = s.get(AudioFile, file_id)
    path = audio.file_path if audio else None
    s.query(BktHistory).filter(
        BktHistory.source_type == "practice", BktHistory.source_id == rec_id
    ).delete(synchronize_session=False)
    s.delete(rec)
    if audio is not None:
        s.delete(audio)

if path:
    from app.common import storage
    storage.remove(path)
print("D1 regression ok")
PY
.venv/bin/python "$TD/check_d1.py"
rm -rf "$TD"
```

预期最后一行：`D1 regression ok`。

- [ ] **Step 9: 提交**

```bash
git add app/services/practice_service.py app/services/analyze_service.py
git commit -m "refactor: 抽出 BKT 共享函数并让分析管线按 kind 分派落库

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: 学生作业仓储查询

**Files:**
- Modify: `app/repositories/homeworks_repo.py:1, 11-30, 59-75, 98-112`

**Interfaces:**
- Consumes: Task 1 的 `Submission.segment_id`。
- Produces:
  - `get_homeworks_with_submission(db, student_id) -> list[tuple[Homework, TeacherDemo | None, Submission | None]]`
  - `get_homework_with_submission(db, homework_id, student_id) -> tuple[Homework, TeacherDemo | None, Submission | None] | None`
  - `get_submission_for_student(db, homework_id, student_id) -> Submission | None`
  - `add_submission(db, submission) -> Submission`（只 flush）

- [ ] **Step 1: 补 `and_` import**

第 1 行改成：

```python
from sqlalchemy import Date, and_, cast, distinct, func, select, tuple_
```

- [ ] **Step 2: 更新两处「没有唯一约束」的注释**

`get_progress_rows` 的 docstring 里：

```text
    提交数**按学生去重**（`count(distinct student_id)`）：2026-10-21 起
    `(homework_id, student_id)` 有唯一索引；去重保留为防御，历史数据或
    别的环境仍可能有重复行。
```

`get_submission_stats` 的 docstring 里：

```text
    组合 = (homework_id, student_id)，**去重**（2026-10-21 起有唯一索引；
    去重保留为防御，历史数据可能重复）。
```

- [ ] **Step 3: 在 `add_homework` 之后加四个函数**

```python
def get_homeworks_with_submission(
    db: Session, student_id: int
) -> list[tuple[Homework, TeacherDemo | None, Submission | None]]:
    """学生端「我的作业」原始行：[(作业, 曲目, 本人提交)]。

    不做班级/名单过滤——`homeworks` 表没有班级字段，与 F1 一致。
    提交用 LEFT JOIN 且必须带 `student_id`：只连本人，别的同学的提交不会把
    作业复制成多行；没有提交时第三列是 None。

    排序在 service 里做：无提交与有提交两组的排序方向不同（一个按截止日
    升序、一个按提交时间降序），SQL 里用 CASE 混着写不如 Python 直观。
    """
    stmt = (
        select(Homework, TeacherDemo, Submission)
        .outerjoin(TeacherDemo, TeacherDemo.id == Homework.demo_id)
        .outerjoin(
            Submission,
            and_(
                Submission.homework_id == Homework.id,
                Submission.student_id == student_id,
            ),
        )
        .order_by(Homework.id.desc())
    )
    return [tuple(row) for row in db.execute(stmt).all()]


def get_homework_with_submission(
    db: Session, homework_id: int, student_id: int
) -> tuple[Homework, TeacherDemo | None, Submission | None] | None:
    """学生端作业详情原始行；作业不存在返回 None。口径同上条。"""
    stmt = (
        select(Homework, TeacherDemo, Submission)
        .outerjoin(TeacherDemo, TeacherDemo.id == Homework.demo_id)
        .outerjoin(
            Submission,
            and_(
                Submission.homework_id == Homework.id,
                Submission.student_id == student_id,
            ),
        )
        .where(Homework.id == homework_id)
    )
    row = db.execute(stmt).first()
    return tuple(row) if row is not None else None


def get_submission_for_student(
    db: Session, homework_id: int, student_id: int
) -> Submission | None:
    """该学生该作业的提交；没有返回 None。F3 的重复提交判断用它。"""
    return db.scalar(
        select(Submission).where(
            Submission.homework_id == homework_id,
            Submission.student_id == student_id,
        )
    )


def add_submission(db: Session, submission: Submission) -> Submission:
    """插入一条提交。只 flush（要拿自增 id 随 Celery 任务传下去），
    commit 交给 service 层。唯一索引冲突时 flush 会抛 IntegrityError，
    由 service 回 422。
    """
    db.add(submission)
    db.flush()
    return submission
```

- [ ] **Step 4: 直连库验证查询**

```bash
.venv/bin/python - <<'PY'
from sqlalchemy import select
from app.db import session_scope
from app.models import Student, User
from app.repositories import homeworks_repo

with session_scope() as s:
    stu = s.scalar(
        select(Student).join(User, User.id == Student.user_id).where(User.username == "stu001")
    )
    rows = homeworks_repo.get_homeworks_with_submission(s, stu.id)
    print("rows:", len(rows))
    print("sample:", [(hw.id, sub.id if sub else None) for hw, _demo, sub in rows[:3]])
    if rows:
        one = homeworks_repo.get_homework_with_submission(s, rows[0][0].id, stu.id)
        print("detail row:", one[0].id if one else None)
PY
```

预期：`rows` 等于库里作业总数；`detail row` 是有效 id。

- [ ] **Step 5: 提交**

```bash
git add app/repositories/homeworks_repo.py
git commit -m "feat: 新增学生作业查询与提交仓储

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: 学生作业 Schema

**Files:**
- Modify: `app/schemas/homework.py`（在文件末尾追加）

**Interfaces:**
- Consumes: `LyricWord`（第 244 行）、`CdmTag`（第 192 行）。
- Produces:
  - `StudentSubmissionBrief`
  - `StudentHomeworkItem`
  - `StudentHomeworkListResponse`
  - `StudentSubmissionDetail`
  - `StudentHomeworkDetail`

- [ ] **Step 1: 在 `app/schemas/homework.py` 末尾追加**

```python
class StudentSubmissionBrief(BaseModel):
    """「我的作业」列表里的提交摘要（4.1）。

    只出列表卡片要用的五个字段：逐字与 CDM 归因只在详情接口返回，
    列表里带上会让一次请求多出最多上千个时间轴点。
    """

    model_config = ConfigDict(from_attributes=True)
    submission_id: int
    status: str                         # submitted / ai_scored / reviewed；NULL 已归一
    ai_score: float | None
    teacher_score: float | None
    submitted_at: datetime | None


class StudentHomeworkItem(BaseModel):
    """学生端作业列表的一行（4.1）。

    `status` 只有四档：无提交是 `todo`，有提交时取 `submission.status`
    （列值 NULL 按 `submitted` 处理）。教师端的 grading/ongoing/closed
    三档不适用于学生——学生只关心「我要不要做」。
    """

    model_config = ConfigDict(from_attributes=True)
    homework_id: int
    title: str
    demo_id: int | None
    demo_title: str | None
    segment_count: int                  # len(segment_ids)；0 = 按整曲布置
    focus_skills: list[str]
    deadline: date | None
    status: str                         # todo / submitted / ai_scored / reviewed
    overdue: bool
    submission: StudentSubmissionBrief | None


class StudentHomeworkListResponse(BaseModel):
    """学生作业列表（4.1）。没有作业时 `homeworks` 是 `[]`，不是 404。"""

    model_config = ConfigDict(from_attributes=True)
    homeworks: list[StudentHomeworkItem]


class StudentSubmissionDetail(BaseModel):
    """学生端作业详情里的提交详情（4.2）。

    与 F5 的 `SubmissionDetailResponse` **刻意不共用**：F5 出教师批改所需的
    校准、BKT 前后对比、语音点评等字段，学生端只需要分数、评语、逐字与 CDM。
    共用一个模型会让两端字段面互相绑架。

    `words` / `cdm_tags` 复用 F5 的 `LyricWord` / `CdmTag`，保证同一个字、
    同一条归因在教师页与学生页形状一致。
    """

    model_config = ConfigDict(from_attributes=True)
    submission_id: int
    status: str
    ai_score: float | None
    teacher_score: float | None
    teacher_comment: str | None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    segment_id: int | None
    words: list[LyricWord]
    cdm_tags: list[CdmTag]


class StudentHomeworkDetail(StudentHomeworkItem):
    """学生作业详情（4.2）：在列表行上追加可选唱段与提交详情。

    `can_submit` 由服务端算死（`submission is None and allowed_segment_ids 非空`），
    前端不要自己从 `submission` 与 `segment_ids` 推——两者组合的边界条件
    （曲目没分段、分段被重解析、已有提交）都在服务端判过了。
    """

    model_config = ConfigDict(from_attributes=True)
    segment_ids: list[int]
    allowed_segment_ids: list[int]
    can_submit: bool
    submission: StudentSubmissionDetail | None
```

- [ ] **Step 2: 导入并实例化验证**

```bash
.venv/bin/python - <<'PY'
from datetime import date
from app.schemas.homework import (
    StudentHomeworkDetail, StudentHomeworkItem, StudentSubmissionBrief,
    StudentSubmissionDetail, StudentHomeworkListResponse,
)
item = StudentHomeworkItem(
    homework_id=1, title="测试", demo_id=2, demo_title="曲目",
    segment_count=1, focus_skills=["音准控制"], deadline=date(2026, 10, 28),
    status="todo", overdue=False, submission=None,
)
# item.model_dump() 已含 submission=None，不能再显式传一次
detail = StudentHomeworkDetail(
    **item.model_dump(), segment_ids=[3], allowed_segment_ids=[3],
    can_submit=True,
)
print(item.model_dump(mode="json"))
print(detail.model_dump(mode="json"))
print(StudentHomeworkListResponse(homeworks=[item]).model_dump(mode="json"))
PY
```

预期：打印三行 JSON，无 `ValidationError`。

- [ ] **Step 3: 提交**

```bash
git add app/schemas/homework.py
git commit -m "feat: 新增学生作业列表与详情 schema

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: 学生作业 Service 与 worker 落库

**Files:**
- Modify: `app/services/homework_service.py`

**Interfaces:**
- Consumes:
  - Task 3 的四个仓储函数；
  - Task 4 的五个 schema；
  - Task 2 的 `practice_service.apply_bkt` 与 `analyze_service.submit(..., persist=...)`。
- Produces:
  - `list_my_homeworks(db, *, user_id) -> StudentHomeworkListResponse`
  - `my_homework_detail(db, *, user_id, homework_id) -> StudentHomeworkDetail`
  - `submit_homework(db, *, user_id, homework_id, segment_id, audio_id) -> str`
  - `save_result(metadata, result) -> None`
  - `discard_pending(metadata) -> None`

- [ ] **Step 1: 补 import**

文件顶部加：

```python
from sqlalchemy.exc import IntegrityError

from app.schemas.audio import AnalyzeSubmitIn
from app.services import analyze_service, practice_service
```

并把 Task 4 的五个模型加进 `from app.schemas.homework import (...)` 的列表：

```python
    StudentHomeworkDetail,
    StudentHomeworkItem,
    StudentHomeworkListResponse,
    StudentSubmissionBrief,
    StudentSubmissionDetail,
```

- [ ] **Step 2: 在 `create_homework` 之后插入学生接口**

先插入一组私有 helper：

```python
def _student_id_or_403(db: Session, user_id: int) -> int:
    """登录用户 → students.id；没有学生档案回 403。

    与 practice_service._own_student_id 同口径，但不跨模块 import 私有函数：
    两个 service 各自守住自己接口的权限边界，改一个不会意外影响另一个。
    """
    student_id = user_repo.get_student_id_by_user_id(db, user_id)
    if student_id is None:
        raise BusinessError(403, "当前账号没有学生档案")
    return student_id


def _submission_status(sub: Submission | None) -> str:
    """学生端四档：无提交 todo，有提交取列值，NULL 脏数据按 submitted。"""
    if sub is None:
        return "todo"
    return sub.status or "submitted"


def _is_overdue(hw: Homework, sub: Submission | None, today: date) -> bool:
    """与教师端 `get_submission_stats` 的逾期口径逐字同源。

    未提交：deadline 非空且早于北京时间今天；
    已提交：`submitted_at` 的日期晚于 deadline（`submitted_at` 是 UTC，
    与 SQL 侧 `cast(submitted_at, Date) > deadline` 一致）。
    deadline 为空一律 false——判不了就当没逾期，不猜。
    """
    if hw.deadline is None:
        return False
    if sub is None:
        return hw.deadline < today
    return sub.submitted_at is not None and sub.submitted_at.date() > hw.deadline


def _allowed_segment_ids(db: Session, hw: Homework) -> list[int]:
    """作业当前实际可选的唱段，按 segments.seq 升序。

    - `homeworks.segment_ids` 非空：只保留仍存在的那些；
    - 为空（按整曲布置）：该曲目当前全部分段；
    - `demo_id` 为空：空数组。

    分段被重新解析后旧的 id 可能已不存在，所以必须与当前 segments 表求交，
    不能直接把 JSONB 原样给前端。
    """
    if hw.demo_id is None:
        return []
    segments = library_repo.list_segments(db, hw.demo_id)
    if not hw.segment_ids:
        return [s.id for s in segments]
    wanted = set(hw.segment_ids)
    return [s.id for s in segments if s.id in wanted]


def _to_brief(sub: Submission) -> StudentSubmissionBrief:
    return StudentSubmissionBrief(
        submission_id=sub.id,
        status=sub.status or "submitted",
        ai_score=sub.ai_score,
        teacher_score=sub.teacher_score,
        submitted_at=sub.submitted_at,
    )


def _to_detail_submission(sub: Submission) -> StudentSubmissionDetail:
    """详情里的提交块。words / cdm_tags 复用 F5 的解析函数。"""
    return StudentSubmissionDetail(
        submission_id=sub.id,
        status=sub.status or "submitted",
        ai_score=sub.ai_score,
        teacher_score=sub.teacher_score,
        teacher_comment=sub.teacher_comment,
        submitted_at=sub.submitted_at,
        reviewed_at=sub.reviewed_at,
        segment_id=sub.segment_id,
        words=_lyrics(sub.ai_detail),
        cdm_tags=_cdm_tags(sub.ai_detail),
    )


def _build_student_item(
    hw: Homework, demo, sub: Submission | None, today: date
) -> StudentHomeworkItem:
    return StudentHomeworkItem(
        homework_id=hw.id,
        title=hw.title,
        demo_id=hw.demo_id,
        demo_title=demo.title if demo else None,
        segment_count=len(hw.segment_ids or []),
        focus_skills=list(hw.focus_skills or []),
        deadline=hw.deadline,
        status=_submission_status(sub),
        overdue=_is_overdue(hw, sub, today),
        submission=_to_brief(sub) if sub else None,
    )


def _student_sort_key(item: StudentHomeworkItem) -> tuple:
    """4.1 的排序：无提交在前（deadline 升序、NULL 沉底、id 降序），
    有提交在后（submitted_at 降序、NULL 沉底、id 降序）。
    """
    sub = item.submission
    if sub is None:
        return (
            0,
            item.deadline is None,
            item.deadline.toordinal() if item.deadline else 0,
            -item.homework_id,
        )
    ts = sub.submitted_at.timestamp() if sub.submitted_at else 0.0
    return (1, sub.submitted_at is None, -ts, -item.homework_id)
```

再插入三个公开函数：

```python
def list_my_homeworks(
    db: Session, *, user_id: int
) -> StudentHomeworkListResponse:
    """学生端作业列表（4.1）。权限在路由层，这里只按 user_id 做身份映射。"""
    student_id = _student_id_or_403(db, user_id)
    today = _beijing_now().date()
    items = [
        _build_student_item(hw, demo, sub, today)
        for hw, demo, sub in homeworks_repo.get_homeworks_with_submission(db, student_id)
    ]
    items.sort(key=_student_sort_key)
    return StudentHomeworkListResponse(homeworks=items)


def my_homework_detail(
    db: Session, *, user_id: int, homework_id: int
) -> StudentHomeworkDetail:
    """学生端作业详情（4.2）。作业不存在回 404；不校验归属（同 F1）。"""
    student_id = _student_id_or_403(db, user_id)
    row = homeworks_repo.get_homework_with_submission(db, homework_id, student_id)
    if row is None:
        raise BusinessError(404, "作业不存在")

    hw, demo, sub = row
    today = _beijing_now().date()
    base = _build_student_item(hw, demo, sub, today)
    allowed = _allowed_segment_ids(db, hw)
    # 不能把 base 里的轻量 submission 直接透传：它的类型是
    # StudentSubmissionBrief，而详情字段要求 StudentSubmissionDetail；
    # 且 StudentHomeworkDetail(**base.model_dump(), submission=...) 会因
    # 关键字重复直接 TypeError。先转 dict 再覆盖。
    payload = base.model_dump()
    payload["submission"] = _to_detail_submission(sub) if sub else None
    return StudentHomeworkDetail(
        **payload,
        segment_ids=list(hw.segment_ids or []),
        allowed_segment_ids=allowed,
        can_submit=sub is None and bool(allowed),
    )


def submit_homework(
    db: Session,
    *,
    user_id: int,
    homework_id: int,
    segment_id: int,
    audio_id: int,
) -> str:
    """F3：校验后建占位提交，投 B2 管线，返回 task_id。

    顺序是「先 flush 拿 id、再派发、最后 commit」：派发失败时占位行还没提交，
    可以干净删除；派发成功但 commit 失败时，worker 末尾找不到提交行会把任务
    置为 failed，不会写出错误数据。
    """
    student_id = _student_id_or_403(db, user_id)

    hw = homeworks_repo.get_homework(db, homework_id)
    if hw is None:
        raise BusinessError(404, "作业不存在")

    audio = audio_repo.get_by_id(db, audio_id)
    if audio is None:
        raise BusinessError(404, "音频不存在")
    if audio.uploader_id != user_id:
        raise BusinessError(403, "只能提交本人录音")

    allowed = _allowed_segment_ids(db, hw)
    if not allowed:
        raise BusinessError(422, "该作业没有可提交的唱段")
    if segment_id not in allowed:
        raise BusinessError(422, "唱段不在本次作业范围内")

    if homeworks_repo.get_submission_for_student(db, homework_id, student_id) is not None:
        raise BusinessError(422, "该作业已提交，不能重复提交")

    sub = Submission(
        homework_id=homework_id,
        student_id=student_id,
        segment_id=segment_id,
        audio_id=audio_id,
        status="submitted",
    )
    try:
        homeworks_repo.add_submission(db, sub)
    except IntegrityError:
        # 并发两个请求同时通过了上面的查询，唯一索引在这里挡住第二个。
        # 必须先 rollback，否则会话处于失败状态，后续任何查询都会报错。
        db.rollback()
        raise BusinessError(422, "该作业已提交，不能重复提交") from None

    try:
        task_id = analyze_service.submit(
            db,
            AnalyzeSubmitIn(segment_id=segment_id, student_audio_id=audio_id),
            persist={"kind": "homework", "submission_id": sub.id},
        )
    except Exception:
        # 分段没绑教师轨、broker 不可达等：占位行还没提交，删掉再原样抛出。
        # 清理本身失败也不能掩盖原始异常。
        try:
            db.delete(sub)
            db.commit()
        except Exception:
            db.rollback()
        raise

    db.commit()
    return task_id
```

- [ ] **Step 3: 在文件末尾加 worker 落库与失败清理**

```python
def save_result(metadata: dict, result: dict) -> None:
    """F3 worker：把占位提交回填成 ai_scored，并更新 BKT。

    在请求之外执行，所以用 `session_scope()` 而不是 `get_db()`。提交行与
    BKT 必须在同一个事务里：只写分数不写 BKT 会让掌握度停在旧值，只写 BKT
    不写提交则 source_id 指向一个不存在的行。任何一步失败都抛出去，由
    run_analysis 把任务置为 failed 并调用 discard_pending 删掉占位行。
    """
    from app.db import session_scope

    with session_scope() as db:
        submission_id = metadata.get("submission_id")
        sub = db.get(Submission, submission_id) if submission_id is not None else None
        if sub is None:
            raise BusinessError(500, "作业提交记录不存在")
        if sub.status != "submitted":
            # 重复任务或行已被处理；discard_pending 的 status 守卫保证不会删已评分行。
            raise BusinessError(
                500, f"作业提交状态不是 submitted（当前 {sub.status!r}）"
            )

        before, after = practice_service.apply_bkt(
            db,
            student_id=sub.student_id,
            dimensions=result.get("dimensions"),
            source_type="homework",
            source_id=sub.id,
        )

        cdm = result.get("cdm") or {}
        sub.ai_score = result.get("overall")
        # 与既有 5 条种子提交同形（defects / overallConfidence），并补上 F5
        # 已经在读的 words。不写 featureMatrix（B4 没有这个数据源），
        # 不写 dimensions（五维只在当次 B4/redis 里，TTL 1 小时）。
        sub.ai_detail = {
            "words": result.get("words"),
            "defects": cdm.get("defects") if cdm else None,
            "overallConfidence": cdm.get("overallConfidence") if cdm else None,
        }
        sub.bkt_before = before
        sub.bkt_after = after
        sub.status = "ai_scored"


def discard_pending(metadata: dict) -> None:
    """F3 分析失败时删除仍处于 submitted 且未评分的占位行，让学生能重交。

    守卫两个条件缺一不可：`status == 'submitted'` 与 `ai_score is None`。
    若 save_result 已经成功、只是 redis 的 done 写失败，行已是 ai_scored，
    这里不会删——代价是学生看到「分析失败」但作业已算分，重交会 422。
    这是极窄的窗口，按「不丢已算出的成绩」处理。
    """
    from app.db import session_scope

    submission_id = metadata.get("submission_id")
    if submission_id is None:
        return
    with session_scope() as db:
        sub = db.get(Submission, submission_id)
        if sub is not None and sub.status == "submitted" and sub.ai_score is None:
            db.delete(sub)
```

- [ ] **Step 4: 用合成结果验证 `save_result` / `discard_pending`**

不跑 librosa，直接造一行占位提交，验证回填与清理：

```bash
.venv/bin/python - <<'PY'
from sqlalchemy import select
from app.db import session_scope
from app.models import BktHistory, Homework, Student, Submission, User
from app.services import homework_service

with session_scope() as s:
    stu = s.scalar(
        select(Student).join(User, User.id == Student.user_id).where(User.username == "stu001")
    )
    teacher_id = s.scalar(select(User.id).where(User.role == "teacher").limit(1))
    student_id = stu.id
    hw = Homework(teacher_id=teacher_id, title="__save_result_tmp__", status="open")
    s.add(hw)
    s.flush()
    sub = Submission(homework_id=hw.id, student_id=student_id, status="submitted")
    s.add(sub)
    s.flush()
    sub_id, hw_id = sub.id, hw.id

result = {
    "overall": 80.0,
    "dimensions": {"音准": 80, "节奏": 80, "气息": 80, "咬字": 80, "拖腔": 80},
    "words": [{"index": 0, "word": "辕", "start": 0.0, "end": 0.4,
               "deviation_cents": 12.5, "warning": False}],
    "cdm": {"defects": [{"id": "d1", "label": "气息支撑不足", "status": "low",
                         "confidence": 0.8}], "overallConfidence": 0.9},
}
homework_service.save_result({"kind": "homework", "submission_id": sub_id}, result)

with session_scope() as s:
    sub = s.get(Submission, sub_id)
    print("status:", sub.status)
    print("score:", sub.ai_score)
    print("detail keys:", sorted(sub.ai_detail.keys()))
    print("bkt after keys:", sorted((sub.bkt_after or {}).keys()))
    print("bkt rows:", s.query(BktHistory).filter(
        BktHistory.source_type == "homework",
        BktHistory.source_id == sub_id,
    ).count())
    s.query(BktHistory).filter(
        BktHistory.source_type == "homework",
        BktHistory.source_id == sub_id,
    ).delete(synchronize_session=False)
    s.delete(sub)
    s.delete(s.get(Homework, hw_id))

# 再验一次 discard_pending
with session_scope() as s:
    hw = Homework(teacher_id=teacher_id, title="__discard_tmp__", status="open")
    s.add(hw)
    s.flush()
    sub = Submission(homework_id=hw.id, student_id=student_id, status="submitted")
    s.add(sub)
    s.flush()
    sub_id, hw_id = sub.id, hw.id
homework_service.discard_pending({"kind": "homework", "submission_id": sub_id})
with session_scope() as s:
    print("discarded:", s.get(Submission, sub_id) is None)
    s.delete(s.get(Homework, hw_id))
PY
```

预期：

```
status: ai_scored
score: 80.0
detail keys: ['defects', 'overallConfidence', 'words']
bkt after keys: ['气息支撑', '咬字', '拖腔', '节奏感知', '音准控制']
bkt rows: 5
discarded: True
```

- [ ] **Step 5: 提交**

```bash
git add app/services/homework_service.py
git commit -m "feat: 实现学生作业列表、详情与 F3 提交服务

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: 接通 API 路由

**Files:**
- Modify: `app/api/homeworks.py:1-49`

**Interfaces:**
- Consumes: Task 5 的 `list_my_homeworks` / `my_homework_detail` / `submit_homework`。
- Produces:
  - `GET /api/homeworks/mine`
  - `GET /api/homeworks/mine/<int:homework_id>`
  - `POST /api/homeworks/<int:homework_id>/submit`

- [ ] **Step 1: 补 import**

```python
from app.common.errors import BusinessError
```

- [ ] **Step 2: 在 F2 路由之后插入两条 GET 与 `_form_int`**

```python
def _form_int(name: str) -> int:
    """取 multipart 整数表单字段，缺字段/非整数回 400（同 D1 的 _form_int）。"""
    raw = request.form.get(name)
    if raw is None or raw == "":
        raise BusinessError(400, f"缺少 {name}")
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise BusinessError(400, f"{name} 必须是整数") from None


@api_bp.route("/homeworks/mine", methods=["GET"])
@login_required
@student_required
def homeworks_mine():
    # 同 dashboard_students：mode="json" 才有 ISO-8601（deadline/submitted_at）
    return ok(homework_service.list_my_homeworks(
        get_db(), user_id=current_user_id()).model_dump(mode="json"))


@api_bp.route("/homeworks/mine/<int:homework_id>", methods=["GET"])
@login_required
@student_required
def homeworks_mine_detail(homework_id):
    return ok(homework_service.my_homework_detail(
        get_db(),
        user_id=current_user_id(),
        homework_id=homework_id,
    ).model_dump(mode="json"))
```

- [ ] **Step 3: 把 F3 桩替换成真实实现**

```python
@api_bp.route("/homeworks/<int:homework_id>/submit", methods=["POST"])
@login_required
@student_required
def homeworks_submit(homework_id):
    # 路径参数用 <int:...> 而不是 <id>：<id> 是字符串转换器，会把
    # /homeworks/abc/submit 也匹配进来再进视图；<int:...> 让 Werkzeug 在路由层
    # 挡掉，走 errors.py 的统一 404「接口不存在」。同 F4/F5/F6。
    task_id = homework_service.submit_homework(
        get_db(),
        user_id=current_user_id(),
        homework_id=homework_id,
        segment_id=_form_int("segment_id"),
        audio_id=_form_int("audio_id"),
    )
    return ok({"task_id": task_id})
```

- [ ] **Step 4: 起后端并验证权限与只读接口**

```bash
# 已在跑就复用，避免端口 8877 被占导致第二个进程直接退出
curl -s -o /dev/null http://127.0.0.1:8877/api/auth/me \
  || (.venv/bin/python app-d.py > /tmp/operaai-backend.log 2>&1 &)
```

另开一次命令：

```bash
TD=$(mktemp -d)
BASE=http://127.0.0.1:8877
# 匿名
curl -s -o /dev/null -w 'anon mine: %{http_code}\n' "$BASE/api/homeworks/mine"
# 教师
curl -s -c "$TD/t.jar" -H 'Content-Type: application/json' \
  -d '{"username":"teacher01","password":"xiyun@2026"}' "$BASE/api/auth/login" > /dev/null
curl -s -b "$TD/t.jar" -o /dev/null -w 'teacher mine: %{http_code}\n' "$BASE/api/homeworks/mine"
# 学生
curl -s -c "$TD/s.jar" -H 'Content-Type: application/json' \
  -d '{"username":"stu001","password":"xiyun@2026"}' "$BASE/api/auth/login" > /dev/null
curl -s -b "$TD/s.jar" "$BASE/api/homeworks/mine" | .venv/bin/python -c 'import json,sys; d=json.load(sys.stdin); print("mine:", d["code"], len(d["data"]["homeworks"]))'
rm -rf "$TD"
```

预期：

```
anon mine: 401
teacher mine: 403
mine: 0 <作业总数>
```

- [ ] **Step 5: 提交**

```bash
git add app/api/homeworks.py
git commit -m "feat: 接通学生作业列表、详情与 F3 路由

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: 端到端冒烟脚本

**Files:**
- Create: `scripts/smoke_homework_submit.sh`

**Interfaces:**
- Consumes: Task 1–6 的全部接口与表结构。
- Produces: 一条可重复执行的验收命令；返回码 0 = 全绿，1 = 有断言失败。

- [ ] **Step 1: 写脚本**

```bash
#!/usr/bin/env bash
# 戏韵AI — 学生提交作业冒烟测试（F3 `POST /api/homeworks/<id>/submit`）
#
# 用法（在项目根目录执行）：
#     scripts/smoke_homework_submit.sh
#     BASE=http://127.0.0.1:80 scripts/smoke_homework_submit.sh
#
# 前置（缺一不可）：
#     1. 后端已启动：.venv/bin/python app-d.py &
#     2. Celery default worker 已启动：
#        .venv/bin/celery -A app.worker:celery_app worker -n default@%h --loglevel=info --concurrency=2
#     3. 数据库已灌 seed.sql；库里有一个绑了教师轨的分段
#     4. 真实测试音频：默认 $HOME/Desktop/test_audio/01_xipi_1931.wav
#
# ⚠️ 单轮约 2 分钟，链路真的跑 librosa，不是桩。
# ⚠️ 会真实写入 homeworks / submissions / bkt_history / audio_files。
#    脚本退出时（含中断）由 EXIT trap 清理本次创建的全部数据与磁盘文件。
set -u

BASE="${BASE:-http://127.0.0.1:8877}"
PY="${PY:-python3}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PY="${VENV_PY:-$ROOT/.venv/bin/python}"
[ -x "$VENV_PY" ] || VENV_PY="$PY"
AUDIO_DIR="${AUDIO_DIR:-$HOME/Desktop/test_audio}"
AUDIO_FILE="${AUDIO_FILE:-01_xipi_1931.wav}"
POLL_INTERVAL="${POLL_INTERVAL:-2}"
POLL_MAX="${POLL_MAX:-200}"

TD="$(mktemp -d)"
CREATED_HW=""
AUDIO_IDS=""

cleanup() {
  local rc=$?
  if [ -n "$CREATED_HW" ] || [ -n "$AUDIO_IDS" ]; then
    ( cd "$ROOT" && "$VENV_PY" - "$CREATED_HW" "$AUDIO_IDS" <<'PY'
import sys
from app.common import storage
from app.db import session_scope
from app.models import AudioFile, BktHistory, Homework, Submission

hw_ids = [int(x) for x in sys.argv[1].split()] if sys.argv[1].strip() else []
audio_ids = [int(x) for x in sys.argv[2].split()] if sys.argv[2].strip() else []
with session_scope() as s:
    subs = list(s.query(Submission).filter(Submission.homework_id.in_(hw_ids)).all()) if hw_ids else []
    sub_ids = [x.id for x in subs]
    if sub_ids:
        s.query(BktHistory).filter(
            BktHistory.source_type == "homework",
            BktHistory.source_id.in_(sub_ids),
        ).delete(synchronize_session=False)
    for sub in subs:
        s.delete(sub)
    for hid in hw_ids:
        row = s.get(Homework, hid)
        if row is not None:
            s.delete(row)
    paths = []
    for aid in audio_ids:
        row = s.get(AudioFile, aid)
        if row is not None:
            paths.append(row.file_path)
            s.delete(row)
for path in paths:
    storage.remove(path)
print("已清理测试数据：homeworks", hw_ids, "audio_files", audio_ids)
PY
    ) || echo "⚠️ 清理失败，请手动删除 homeworks id=$CREATED_HW、audio_files id=$AUDIO_IDS" >&2
  fi
  rm -rf "$TD"
  exit "$rc"
}
trap cleanup EXIT

JAR_T="$TD/teacher.jar"
JAR_S1="$TD/stu001.jar"
JAR_S2="$TD/stu002.jar"
JAR_A="$TD/anon.jar"
JAR="$JAR_A"
HDR="$TD/last.headers"
BODY_FILE="$TD/last.body"

PASS=0
FAIL=0
STATUS=""
BODY=""
BODY_N=""

red()   { printf '\033[31m%s\033[0m' "$1"; }
green() { printf '\033[32m%s\033[0m' "$1"; }
ok()    { PASS=$((PASS + 1)); printf '  %s %s\n' "$(green ✓)" "$1"; }
bad()   { FAIL=$((FAIL + 1)); printf '  %s %s —— %s\n' "$(red ✗)" "$1" "$2"; }

req() {
  STATUS=$(curl -s -D "$HDR" -o "$BODY_FILE" -c "$JAR" -b "$JAR" -w '%{http_code}' "$@")
  BODY=$(cat "$BODY_FILE")
  BODY_N=$(printf '%s' "$BODY" | tr -d ' \n\t')
  if [ "$STATUS" = "000" ]; then
    echo "$(red "无法连接 $BASE") —— 后端没起？先执行：.venv/bin/python app-d.py" >&2
    exit 1
  fi
}

jget() {
  printf '%s' "$BODY" | "$PY" -c '
import json, sys
try:
    cur = json.load(sys.stdin)
    for k in sys.argv[1].split("."):
        cur = cur[int(k)] if isinstance(cur, list) else cur[k]
except Exception:
    cur = ""
print("" if cur is None else cur)
' "$1"
}

expect_status() {
  if [ "$STATUS" = "$2" ]; then ok "$1"; else bad "$1" "期望 HTTP ${2}，实际 ${STATUS}；body=$BODY"; fi
}

expect_code() {
  local got
  got=$(jget code)
  if [ "$got" = "$2" ]; then ok "$1"; else bad "$1" "期望 code=${2}，实际 code=${got}；body=$BODY"; fi
}

expect_eq() {
  if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "期望「$3」，实际「$2」；body=$BODY"; fi
}

expect_in() {
  local needle
  needle=$(printf '%s' "$2" | tr -d ' \n\t')
  case "$BODY_N" in
    *"$needle"*) ok "$1" ;;
    *) bad "$1" "找不到「$2」；body=$BODY" ;;
  esac
}

post_json() {
  req -X POST -H 'Content-Type: application/json' -d "$2" "$BASE$1"
}

if [ ! -f "$AUDIO_DIR/$AUDIO_FILE" ]; then
  echo "$(red "找不到测试音频：$AUDIO_DIR/$AUDIO_FILE")" >&2
  echo "  该目录不在仓库里（.gitignore 排除），需另行获取；也可用 AUDIO_DIR=<路径> 指定" >&2
  exit 1
fi

FUTURE=$("$PY" -c 'from datetime import datetime, timedelta; from zoneinfo import ZoneInfo
print(datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=7))')

echo "冒烟目标：$BASE"
echo "测试音频：$AUDIO_DIR/$AUDIO_FILE"
echo "（本轮约 2 分钟，瓶颈是 librosa 提音高）"
echo

echo "── 1. 准备：找一条绑了教师轨的分段 ─────────────"
read -r DEMO_ID SEG_ID SEG_OTHER <<EOF
$( cd "$ROOT" && "$VENV_PY" - <<'PY'
from sqlalchemy import select
from app.db import session_scope
from app.models import Segment, TeacherDemo

with session_scope() as s:
    rows = s.execute(
        select(Segment, TeacherDemo)
        .join(TeacherDemo, TeacherDemo.id == Segment.demo_id)
        .order_by(Segment.demo_id, Segment.seq)
    ).all()
    usable = [(seg, demo) for seg, demo in rows
              if seg.audio_id is not None or demo.audio_id is not None]
    if not usable:
        print("", "", "")
    else:
        seg, demo = usable[0]
        others = [r[0].id for r in rows if r[0].demo_id == demo.id and r[0].id != seg.id]
        print(demo.id, seg.id, others[0] if others else 999999999)
PY
)
EOF
if [ -z "$DEMO_ID" ]; then
  echo "$(red "库里没有绑定教师轨的分段") —— 先上传/解析一份示范，或灌 seed.sql" >&2
  exit 1
fi
echo "  · 曲目 id=$DEMO_ID，作业唱段 id=$SEG_ID，越界唱段 id=$SEG_OTHER"

echo
echo "── 2. 教师布置作业 ────────────────────────────"
JAR="$JAR_T"
post_json "/api/auth/login" '{"username":"teacher01","password":"xiyun@2026"}'
expect_status "teacher01 登录 → 200" 200
post_json "/api/homeworks" "{\"title\":\"冒烟-学生提交作业\",\"demo_id\":$DEMO_ID,\"segment_ids\":[$SEG_ID],\"focus_skills\":[\"音准控制\",\"气息支撑\"],\"deadline\":\"$FUTURE\"}"
expect_status "F2 布置作业 → 200" 200
HW_ID=$(jget data.homework_id)
if [ -n "$HW_ID" ]; then CREATED_HW="$HW_ID"; fi
if [ -z "$HW_ID" ]; then
  echo "$(red "没拿到 homework_id，后续无法继续")" >&2
  exit 1
fi
ok "作业 id=$HW_ID"

echo
echo "── 3. 权限 ────────────────────────────────────"
JAR="$JAR_A"
req "$BASE/api/homeworks/mine"
expect_status "匿名 GET /mine → 401" 401
expect_code   "匿名 code=401" 401

JAR="$JAR_T"
req "$BASE/api/homeworks/mine"
expect_status "教师 GET /mine → 403" 403
expect_code   "教师 code=403" 403

JAR="$JAR_S1"
post_json "/api/auth/login" '{"username":"stu001","password":"xiyun@2026"}'
expect_status "stu001 登录 → 200" 200

echo
echo "── 4. 学生列表与详情 ──────────────────────────"
req "$BASE/api/homeworks/mine"
expect_status "GET /mine → 200" 200
expect_code   "列表 code=0" 0
expect_in     "新作业出现在列表" "\"homework_id\":$HW_ID,"

req "$BASE/api/homeworks/mine/$HW_ID"
expect_status "GET /mine/<id> → 200" 200
expect_eq "详情 homework_id" "$(jget data.homework_id)" "$HW_ID"
expect_eq "详情 status=todo" "$(jget data.status)" "todo"
expect_eq "详情 can_submit=true" "$(jget data.can_submit)" "True"
expect_eq "详情 overdue=false" "$(jget data.overdue)" "False"
expect_eq "可选唱段=作业指定唱段" "$(jget data.allowed_segment_ids.0)" "$SEG_ID"

req "$BASE/api/homeworks/mine/999999999"
expect_status "详情不存在 → 404" 404
expect_in     "作业不存在文案" "作业不存在"

echo
echo "── 5. F3 入参校验 ─────────────────────────────"
# 5a. 缺字段
req -X POST "$BASE/api/homeworks/$HW_ID/submit"
expect_status "缺表单字段 → 400" 400
expect_in     "报错点名 segment_id" "segment_id"

# 5b. 音频不存在
req -X POST -F "segment_id=$SEG_ID" -F "audio_id=999999999" "$BASE/api/homeworks/$HW_ID/submit"
expect_status "音频不存在 → 404" 404
expect_in     "音频不存在文案" "音频不存在"

# 5c. 用另一个学生的录音
JAR="$JAR_S2"
post_json "/api/auth/login" '{"username":"stu002","password":"xiyun@2026"}'
expect_status "stu002 登录 → 200" 200
req -X POST -F "audio=@$AUDIO_DIR/$AUDIO_FILE" "$BASE/api/audio/upload"
expect_status "stu002 B1 上传 → 200" 200
OTHER_FILE_ID=$(jget data.file_id)
if [ -n "$OTHER_FILE_ID" ]; then AUDIO_IDS="$AUDIO_IDS $OTHER_FILE_ID"; fi

JAR="$JAR_S1"
req -X POST -F "segment_id=$SEG_ID" -F "audio_id=$OTHER_FILE_ID" "$BASE/api/homeworks/$HW_ID/submit"
expect_status "用别人的录音 → 403" 403
expect_in     "越权录音文案" "只能提交本人录音"

# 5d. 越界唱段（需要先有本人录音）
req -X POST -F "audio=@$AUDIO_DIR/$AUDIO_FILE" "$BASE/api/audio/upload"
expect_status "stu001 B1 上传 → 200" 200
FILE_ID=$(jget data.file_id)
if [ -n "$FILE_ID" ]; then AUDIO_IDS="$AUDIO_IDS $FILE_ID"; fi
req -X POST -F "segment_id=$SEG_OTHER" -F "audio_id=$FILE_ID" "$BASE/api/homeworks/$HW_ID/submit"
expect_status "唱段不在作业范围 → 422" 422
expect_in     "越界唱段文案" "唱段不在本次作业范围内"
if [ -z "$FILE_ID" ]; then
  echo "$(red "没拿到 B1 file_id，无法跑成功路径")" >&2
  exit 1
fi

echo
echo "── 6. 成功提交与重复提交 ──────────────────────"
req -X POST -F "segment_id=$SEG_ID" -F "audio_id=$FILE_ID" "$BASE/api/homeworks/$HW_ID/submit"
expect_status "F3 提交 → 200" 200
expect_code   "F3 code=0" 0
TASK_ID=$(jget data.task_id)
if printf '%s' "$TASK_ID" | grep -qE '^[0-9a-fA-F]{8,}$'; then
  ok "F3 返回 task_id（=$TASK_ID）"
else
  bad "F3 应返回 task_id" "实际='$TASK_ID'；body=$BODY"
  exit 1
fi

req -X POST -F "segment_id=$SEG_ID" -F "audio_id=$FILE_ID" "$BASE/api/homeworks/$HW_ID/submit"
expect_status "立即重复提交 → 422" 422
expect_code   "重复提交 code=422" 422
expect_in     "重复提交文案" "该作业已提交，不能重复提交"

echo
echo "── 7. B3 轮询（最多 $((POLL_MAX * POLL_INTERVAL)) 秒）─────"
FINAL=""
n=0
while [ "$n" -lt "$POLL_MAX" ]; do
  n=$((n + 1))
  req "$BASE/api/analyze/status/$TASK_ID"
  ST=$(jget data.status)
  if [ "$ST" = "done" ] || [ "$ST" = "failed" ]; then
    FINAL="$ST"
    printf '  · 第 %d 轮到达终态：status=%s message=%s\n' "$n" "$ST" "$(jget data.message)"
    break
  fi
  sleep "$POLL_INTERVAL"
done
expect_eq "B3 终态为 done" "$FINAL" "done"
if [ "$FINAL" != "done" ]; then
  echo "$(red "分析未完成，跳过落库与回显断言")" >&2
  exit 1
fi

req "$BASE/api/analyze/result/$TASK_ID"
expect_status "B4 → 200" 200
printf '%s' "$BODY" > "$TD/b4.json"

echo
echo "── 8. 落库校验 ────────────────────────────────"
STUDENT_ID=$( cd "$ROOT" && "$VENV_PY" - <<'PY'
from sqlalchemy import select
from app.db import session_scope
from app.models import Student, User
with session_scope() as s:
    print(s.scalar(select(Student.id).join(User, User.id == Student.user_id)
                   .where(User.username == "stu001")))
PY
)
DB_CHECK=$( cd "$ROOT" && "$VENV_PY" - "$HW_ID" "$STUDENT_ID" "$SEG_ID" "$FILE_ID" <<'PY'
import json, sys
from app.db import session_scope
from app.models import BktHistory, Submission

hw_id, student_id, seg_id, audio_id = (int(x) for x in sys.argv[1:5])
with session_scope() as s:
    sub = s.query(Submission).filter(
        Submission.homework_id == hw_id,
        Submission.student_id == student_id,
    ).one_or_none()
    rows = []
    if sub is not None:
        rows = s.query(BktHistory).filter(
            BktHistory.source_type == "homework",
            BktHistory.source_id == sub.id,
        ).all()
    print(json.dumps({
        "submission_id": sub.id if sub else None,
        "found": sub is not None,
        "status": sub.status if sub else None,
        "ai_score": sub.ai_score if sub else None,
        "detail_keys": "|".join(sorted((sub.ai_detail or {}).keys())) if sub else "",
        "segment_id_ok": bool(sub and sub.segment_id == seg_id),
        "audio_id_ok": bool(sub and sub.audio_id == audio_id),
        "submitted_at_ok": bool(sub and sub.submitted_at is not None),
        "bkt_before_ok": bool(sub and isinstance(sub.bkt_before, dict) and sub.bkt_before),
        "bkt_after_ok": bool(sub and isinstance(sub.bkt_after, dict) and sub.bkt_after),
        "bkt_rows": len(rows),
        "bkt_source_ok": all(r.source_type == "homework" and r.source_id == sub.id for r in rows),
    }))
PY
)
BODY="$DB_CHECK"
BODY_N=$(printf '%s' "$BODY" | tr -d ' \n\t')
expect_eq "提交行已落库" "$(jget found)" "True"
SUB_ID=$(jget submission_id)
expect_eq "status=ai_scored" "$(jget status)" "ai_scored"
expect_eq "ai_score 非空" "$([ -n "$(jget ai_score)" ] && echo yes)" "yes"
expect_eq "ai_detail 三个键" "$(jget detail_keys)" "defects|overallConfidence|words"
expect_eq "segment_id 正确" "$(jget segment_id_ok)" "True"
expect_eq "audio_id 正确" "$(jget audio_id_ok)" "True"
expect_eq "submitted_at 非空" "$(jget submitted_at_ok)" "True"
expect_eq "bkt_before 非空" "$(jget bkt_before_ok)" "True"
expect_eq "bkt_after 非空" "$(jget bkt_after_ok)" "True"
expect_eq "bkt_history 5 行" "$(jget bkt_rows)" "5"
expect_eq "bkt_history source 正确" "$(jget bkt_source_ok)" "True"
if [ -z "$SUB_ID" ]; then
  echo "$(red "没拿到 submission_id，跳过教师端回显")" >&2
  exit 1
fi

echo
echo "── 9. 教师端 F4/F5 回显 ───────────────────────"
JAR="$JAR_T"
req "$BASE/api/homeworks/$HW_ID/submissions"
expect_status "F4 待批列表 → 200" 200
expect_in     "F4 能看到该提交" "\"submission_id\":$SUB_ID,"

req "$BASE/api/submissions/$SUB_ID/detail"
expect_status "F5 批改详情 → 200" 200
printf '%s' "$BODY" > "$TD/f5.json"
LYRICS_MATCH=$("$PY" - "$TD/b4.json" "$TD/f5.json" <<'PY'
import json, sys
b4 = json.load(open(sys.argv[1], encoding="utf-8"))["data"]
f5 = json.load(open(sys.argv[2], encoding="utf-8"))["data"]
keys = ("index", "word", "start", "end", "deviation_cents", "warning")
expected = [{k: w.get(k) for k in keys} for w in (b4.get("words") or [])]
print("match" if expected == (f5.get("lyrics") or []) else "mismatch")
PY
)
expect_eq "F5 的 lyrics 与 B4 words 同形" "$LYRICS_MATCH" "match"

echo
if [ "$FAIL" -eq 0 ]; then
  echo "$(green "全部通过")：$PASS 项"
  exit 0
fi
echo "$(red "失败 $FAIL 项")，通过 $PASS 项"
exit 1
```

- [ ] **Step 2: 加执行权限并做语法检查**

```bash
chmod +x scripts/smoke_homework_submit.sh
bash -n scripts/smoke_homework_submit.sh
```

预期无输出。

- [ ] **Step 3: 确认前置进程**

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8877/api/auth/me
```

预期 `401`（进程在跑）。Celery worker 必须已在运行，否则任务停在 queued，脚本会在第 7 节失败。

- [ ] **Step 4: 跑冒烟**

```bash
scripts/smoke_homework_submit.sh
```

预期最后一行：

```
全部通过：<N> 项
```

若在 B3 超时，先看 worker 是否消费 default 队列（`celery -A app.worker:celery_app worker -n default@%h ...`），不要改脚本的 `POLL_MAX` 掩盖问题。

- [ ] **Step 5: 再跑一遍，确认可重复执行**

```bash
scripts/smoke_homework_submit.sh
```

预期同样全绿；EXIT trap 会把上一轮的 homework / submission / BKT / audio 全部清掉。

- [ ] **Step 6: 提交**

```bash
git add scripts/smoke_homework_submit.sh
git commit -m "test: 新增学生提交作业冒烟脚本

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: `my_homework.html`、页面注册与学生导航

**Files:**
- Create: `my_homework.html`
- Modify: `app/pages.py:2, 35-49, 65-67`
- Modify: `dashboard.html:361`、`tracking.html:339`、`recommendation.html:395`、`homework.html:551`、`demo_library.html:1267`、`annotation.html:460`、`cdm_report.html:1012`、`knowledge_graph.html:630`、`sing_along.html:496`、`AI_teacher.html:564`、`cat_test.html:569`

**Interfaces:**
- Consumes: Task 6 的两条 GET；Task 9 的 `sing_along.html?homework_id=`。
- Produces: 学生侧入口页；`/my_homework.html` 受登录保护。

- [ ] **Step 1: 创建 `my_homework.html` 的共享样式**

新建文件，先复制 `sing_along.html` 的以下片段到 `<style>`（行号按当前文件）：

- `:root`：12-67
- `*` / `body`：69-77
- `.navbar` … `.nav-user .avatar`：79-115
- `.layout` … `.nav-item .icon`：117-143
- `.page-header`：154-157
- `.card` … `.btn-primary:disabled`：159-201
- 角色显示规则：460-463

然后追加页面专属样式：

```css
/* ===== 我的作业 ===== */
.homework-layout{display:grid;grid-template-columns:360px minmax(0,1fr);gap:16px;align-items:start}
@media (max-width:1100px){.homework-layout{grid-template-columns:1fr}}
.list-card,.detail-card{padding:0;overflow:hidden}
.list-card .card-header{padding:14px 16px 0;margin-bottom:8px}
.homework-list{max-height:calc(100vh - 210px);overflow-y:auto}
.homework-item{padding:12px 16px;border-bottom:1px solid var(--border-light);cursor:pointer;border-left:4px solid transparent}
.homework-item:hover{background:var(--bg-hover)}
.homework-item.active{background:var(--primary-soft);border-left-color:var(--primary)}
.hw-title{font-weight:700;color:var(--text-primary);margin-bottom:2px}
.hw-meta{font-size:13px;color:var(--text-muted)}
.hw-row{display:flex;align-items:center;gap:6px;margin-top:6px}
.hw-score{margin-left:auto;font-weight:700;color:var(--primary)}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:600;background:var(--bg-tertiary);color:var(--text-secondary)}
.badge.warn{background:var(--warning-soft);color:var(--warning)}
.badge.info{background:var(--primary-soft);color:var(--primary)}
.badge.primary{background:var(--primary-soft);color:var(--primary)}
.badge.success{background:var(--success-soft);color:var(--success)}
.badge.danger{background:var(--danger-soft);color:var(--danger)}
.detail-empty{padding:40px 20px;text-align:center;color:var(--text-muted)}
#detailBody{padding:18px}
.detail-header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap}
.detail-header h3{font-size:18px;margin-bottom:4px}
.detail-action{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.hint-danger{font-size:13px;color:var(--danger);font-weight:600}
.detail-section{border-top:1px solid var(--border-light);margin-top:14px;padding-top:12px}
.detail-section h4{font-size:14px;margin-bottom:8px;color:var(--text-primary)}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{background:var(--primary-soft);color:var(--primary);border:1px solid var(--primary-border);border-radius:12px;padding:1px 10px;font-size:12px}
.muted{color:var(--text-muted);font-size:13px}
.submission-box{background:var(--bg-primary);border:1px solid var(--border-light);border-radius:10px;padding:12px}
.submission-head{display:flex;align-items:center;gap:12px;flex-wrap:wrap;font-size:13px;margin-bottom:10px}
.comment{background:var(--bg-secondary);border-left:3px solid var(--success);padding:8px 10px;margin-bottom:10px;font-size:14px}
.word-table{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:10px}
.word-table th,.word-table td{padding:4px 6px;border-bottom:1px solid var(--border-light);text-align:left}
.word-table .green{color:var(--success);font-weight:600}
.word-table .yellow{color:var(--warning);font-weight:600}
.word-table .red{color:var(--danger);font-weight:600}
.cdm-tags{display:flex;gap:6px;flex-wrap:wrap}
.cdm-tag{background:var(--bg-secondary);border:1px solid var(--border-medium);border-radius:10px;padding:2px 8px;font-size:12px}
.cdm-tag.high{border-color:var(--danger);color:var(--danger)}
.cdm-tag.medium{border-color:var(--warning);color:var(--warning)}
.cdm-tag.low{border-color:var(--border-medium);color:var(--text-secondary)}
.notice{background:var(--warning-soft);border:1px solid var(--warning);color:var(--text-primary);border-radius:10px;padding:10px 14px;margin-bottom:14px;font-size:14px}
```

- [ ] **Step 2: 写 `<body>`**

```html
<body>

<nav class="navbar">
  <div class="nav-brand">
    <div class="logo">戏</div>
    <h1>戏韵AI · 我的作业</h1>
    <span class="badge">学生练习</span>
  </div>
  <div class="nav-user">
    <div class="avatar">🎭</div>
    <span>李小燕</span>
    <span style="color:var(--text-muted);font-size:13px">|</span>
    <span style="color:var(--text-secondary);font-size:13px">初级班</span>
  </div>
</nav>

<div class="layout">
  <aside class="sidebar">
    <div class="nav-group" data-role="teacher">
      <div class="nav-group-title">核心功能</div>
      <a href="dashboard.html" class="nav-item"><span class="icon">📊</span>班级看板</a>
    </div>
    <div class="nav-group" data-role="teacher">
      <div class="nav-group-title">教学工作台</div>
      <a href="demo_library.html" class="nav-item"><span class="icon">🎵</span>示范库管理</a>
      <a href="annotation.html" class="nav-item"><span class="icon">🏷️</span>歌词级标注</a>
      <a href="homework.html" class="nav-item"><span class="icon">📝</span>作业批改</a>
    </div>
    <div class="nav-group" data-role="student">
      <div class="nav-group-title">学生练习</div>
      <a href="my_homework.html" class="nav-item active"><span class="icon">📝</span>我的作业</a>
      <a href="sing_along.html" class="nav-item"><span class="icon">🎙️</span>实时跟唱</a>
      <a href="AI_teacher.html" class="nav-item"><span class="icon">🤖</span>AI教练对话</a>
      <a href="cat_test.html" class="nav-item"><span class="icon">🎯</span>摸底测试</a>
    </div>
    <div class="nav-group" data-role="teacher">
      <div class="nav-group-title">数据分析</div>
      <a href="tracking.html" class="nav-item"><span class="icon">📈</span>能力追踪</a>
      <a href="recommendation.html" class="nav-item"><span class="icon">🎯</span>渐进式推荐</a>
      <a href="knowledge_graph.html" class="nav-item"><span class="icon">🧠</span>知识图谱</a>
    </div>
  </aside>

  <main class="main-content">
    <div class="page-header">
      <h2>📝 我的作业</h2>
      <p id="pageSubtitle">正在加载…</p>
    </div>

    <div class="notice" id="notice" style="display:none"></div>

    <div class="homework-layout">
      <section class="card list-card">
        <div class="card-header">
          <div class="card-title"><div class="icon">📋</div>作业列表</div>
        </div>
        <div id="homeworkList" class="homework-list">
          <div class="empty" style="padding:20px;color:var(--text-muted)">正在加载…</div>
        </div>
      </section>

      <section class="card detail-card">
        <div class="detail-empty" id="detailEmpty">选择左侧一份作业查看详情</div>
        <div id="detailBody" style="display:none"></div>
      </section>
    </div>
  </main>
</div>
```

- [ ] **Step 3: 写主 `<script>`**

```html
<script>
// ============================================================
// 我的作业：列表 + 详情 + 去完成
// 全部走真接口，没有 mock 数据。所有库内文本经 escapeHtml 后进模板。
// ============================================================
const state = { items: [], selectedId: null, detailToken: 0 };
const STATUS_TEXT = {
  todo: "待完成",
  submitted: "分析中",
  ai_scored: "待批改",
  reviewed: "已批改",
};

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

async function apiGet(path) {
  const r = await fetch(path, { credentials: "same-origin" });
  let body = null;
  try { body = await r.json(); } catch (e) { /* 非 JSON（如 nginx 的 502 页） */ }
  if (!r.ok) {
    const err = new Error((body && body.message) || ("HTTP " + r.status));
    err.status = r.status;
    throw err;
  }
  if (!body || body.code !== 0) {
    throw new Error((body && body.message) || "响应格式错误");
  }
  return body.data;
}

function showNotice(msg) {
  const el = document.getElementById("notice");
  el.textContent = msg;
  el.style.display = "block";
}

function fmtDateTime(s) {
  return s ? String(s).replace("T", " ").slice(0, 16) : "—";
}

function fmtScore(v) {
  return (typeof v === "number" && Number.isFinite(v)) ? String(v) : "—";
}

function fmtCents(v) {
  return (typeof v === "number" && Number.isFinite(v)) ? v.toFixed(1) : "—";
}

function badgeClass(status) {
  if (status === "todo") return "warn";
  if (status === "submitted") return "info";
  if (status === "ai_scored") return "primary";
  return "success";
}

function wordClass(cents) {
  // Number(null) 是 0，不先挡掉会把「没有偏差数据」染成绿色
  if (cents == null) return "";
  const v = Math.abs(Number(cents));
  if (!Number.isFinite(v)) return "";
  if (v < 20) return "green";
  if (v <= 50) return "yellow";
  return "red";
}

function renderList() {
  const box = document.getElementById("homeworkList");
  if (!state.items.length) {
    box.innerHTML = `<div style="padding:20px;color:var(--text-muted)">还没有布置给你的作业。</div>`;
    return;
  }
  box.innerHTML = state.items.map(it => {
    const sub = it.submission;
    const score = sub ? (sub.teacher_score ?? sub.ai_score) : null;
    const overdue = it.overdue ? `<span class="badge danger">已逾期</span>` : "";
    return `
      <div class="homework-item ${it.homework_id === state.selectedId ? "active" : ""}"
           onclick="selectHomework(${it.homework_id})">
        <div class="hw-title">${escapeHtml(it.title)}</div>
        <div class="hw-meta">${escapeHtml(it.demo_title || "未挂曲目")} · ${it.deadline ? "截止 " + escapeHtml(it.deadline) : "未设截止"}</div>
        <div class="hw-row">
          <span class="badge ${badgeClass(it.status)}">${STATUS_TEXT[it.status] || escapeHtml(it.status)}</span>
          ${overdue}
          <span class="hw-score">${fmtScore(score)}</span>
        </div>
      </div>`;
  }).join("");
}

function renderDetail(d) {
  document.getElementById("detailEmpty").style.display = "none";
  const body = document.getElementById("detailBody");
  body.style.display = "block";

  const skills = (d.focus_skills && d.focus_skills.length)
    ? d.focus_skills.map(s => `<span class="chip">${escapeHtml(s)}</span>`).join("")
    : `<span class="muted">未指定</span>`;

  let action;
  if (d.can_submit) {
    action = `<button class="btn-primary" onclick="goPractice(${d.homework_id})">去完成</button>`;
    if (d.overdue) action += `<span class="hint-danger">已逾期，仍可提交</span>`;
  } else if (d.submission) {
    action = `<button class="btn-primary" disabled>已提交</button>`;
  } else {
    action = `<button class="btn-primary" disabled>暂无可提交唱段</button>`;
  }

  let submissionHtml = `<div class="muted">还没有提交。</div>`;
  if (d.submission) {
    const s = d.submission;
    const words = (s.words || []).map(w => `
      <tr>
        <td>${w.index + 1}</td>
        <td>${escapeHtml(w.word || "—")}</td>
        <td class="${wordClass(w.deviation_cents)}">${fmtCents(w.deviation_cents)}</td>
        <td>${w.warning ? "⚠" : ""}</td>
      </tr>`).join("");
    const tags = (s.cdm_tags || []).map(t => `
      <span class="cdm-tag ${escapeHtml(t.severity || "unknown")}"
            title="${escapeHtml(t.evidence || "")}">
        ${escapeHtml(t.label)}${t.confidence == null ? "" : ` · ${Math.round(t.confidence * 100)}%`}
      </span>`).join("");
    submissionHtml = `
      <div class="submission-box">
        <div class="submission-head">
          <span class="badge ${badgeClass(s.status)}">${STATUS_TEXT[s.status] || escapeHtml(s.status)}</span>
          <span>提交于 ${fmtDateTime(s.submitted_at)}</span>
          <span>AI 分 <b>${fmtScore(s.ai_score)}</b></span>
          <span>教师分 <b>${fmtScore(s.teacher_score)}</b></span>
        </div>
        ${s.teacher_comment ? `<div class="comment">教师评语：${escapeHtml(s.teacher_comment)}</div>` : ""}
        <h4>逐字偏差</h4>
        ${words
          ? `<table class="word-table"><thead><tr><th>#</th><th>字</th><th>偏差（音分）</th><th>提醒</th></tr></thead><tbody>${words}</tbody></table>`
          : `<div class="muted">本次提交没有逐字数据（该唱段没有歌词时间轴）。</div>`}
        <h4>CDM 归因标签</h4>
        ${tags ? `<div class="cdm-tags">${tags}</div>` : `<div class="muted">本次没有归因标签。</div>`}
      </div>`;
  }

  body.innerHTML = `
    <div class="detail-header">
      <div>
        <h3>${escapeHtml(d.title)}</h3>
        <div class="hw-meta">${escapeHtml(d.demo_title || "未挂曲目")} · ${d.deadline ? "截止 " + escapeHtml(d.deadline) : "未设截止"}
          ${d.overdue ? `<span class="badge danger">已逾期</span>` : ""}</div>
      </div>
      <div class="detail-action">${action}</div>
    </div>
    <div class="detail-section">
      <h4>重点技法</h4>
      <div class="chips">${skills}</div>
    </div>
    <div class="detail-section">
      <h4>唱段</h4>
      <div>${d.segment_count ? `作业指定 ${d.segment_count} 段` : "按整曲布置"}，本次可选 ${(d.allowed_segment_ids || []).length} 段。</div>
    </div>
    <div class="detail-section">
      <h4>提交结果</h4>
      ${submissionHtml}
    </div>`;
}

async function selectHomework(id) {
  state.selectedId = id;
  renderList();
  const token = ++state.detailToken;
  document.getElementById("detailEmpty").style.display = "none";
  document.getElementById("detailBody").style.display = "none";
  try {
    const d = await apiGet(`/api/homeworks/mine/${id}`);
    if (token !== state.detailToken) return;   // 切得太快，丢弃旧响应
    renderDetail(d);
  } catch (e) {
    if (token !== state.detailToken) return;
    if (e.status === 401) return location.replace("/login.html");
    showNotice(`加载作业详情失败：${e.message}`);
  }
}

function goPractice(id) {
  location.href = `sing_along.html?homework_id=${id}`;
}

async function loadList() {
  try {
    const data = await apiGet("/api/homeworks/mine");
    state.items = data.homeworks || [];
    const todo = state.items.filter(it => it.status === "todo").length;
    document.getElementById("pageSubtitle").textContent = `待完成 ${todo} 份`;
    renderList();
    if (state.items.length) selectHomework(state.items[0].homework_id);
  } catch (e) {
    if (e.status === 401) return location.replace("/login.html");
    if (e.status === 403) {
      document.getElementById("pageSubtitle").textContent = "";
      document.getElementById("homeworkList").innerHTML =
        `<div style="padding:20px;color:var(--text-muted)">该页面只对学生开放。</div>`;
      showNotice("我的作业仅学生可见");
      return;
    }
    showNotice(`加载作业列表失败：${e.message}`);
  }
}

loadList();
</script>
```

- [ ] **Step 4: 追加登录用户条脚本**

把 `sing_along.html:2107-2178`（从 `<!-- ==== 登录用户条 ...` 到 `</script>`）整段复制到 `my_homework.html` 的 `</body>` 之前。它会把 `.nav-user` 换成真实登录用户，并按 `role-teacher` / `role-student` 显示对应导航分组。

- [ ] **Step 5: 注册页面**

`app/pages.py`：

- 第 2 行 docstring 的「14 个 HTML」改成「15 个 HTML」。
- `PROTECTED_PAGES` 在 `"homework",` 之后加 `"my_homework",`。
- 第 65-67 行注释「循环注册而非写 13 个视图函数」改成「14 个」。

- [ ] **Step 6: 给 11 页学生导航加「我的作业」**

每页在 `实时跟唱` 之前插入一行（缩进与相邻行一致）：

`dashboard.html:361`、`tracking.html:339`、`recommendation.html:395`、`annotation.html:460`、`AI_teacher.html:564`、`cat_test.html:569`（4 空格缩进）：

```html
    <a href="my_homework.html" class="nav-item"><span class="icon">📝</span>我的作业</a>
```

`homework.html:551`、`sing_along.html:496`（6 空格缩进）：

```html
      <a href="my_homework.html" class="nav-item"><span class="icon">📝</span>我的作业</a>
```

`cdm_report.html:1012`、`knowledge_graph.html:630`、`demo_library.html:1267`（16 空格缩进）：

```html
                <a href="my_homework.html" class="nav-item"><span class="icon">📝</span>我的作业</a>
```

`sing_along.html` 插入后，原来的「实时跟唱」仍保持 `active`；`my_homework.html` 自己那行已在上面的 body 里标了 `active`。

- [ ] **Step 7: 语法检查与页面可达性**

```bash
.venv/bin/python - <<'PY'
import pathlib, re, subprocess, tempfile
for name in ("my_homework.html",):
    html = pathlib.Path(name).read_text(encoding="utf-8")
    for i, code in enumerate(re.findall(r"<script>(.*?)</script>", html, re.S)):
        p = pathlib.Path(tempfile.mkdtemp()) / f"{i}.js"
        p.write_text(code, encoding="utf-8")
        subprocess.run(["node", "--check", str(p)], check=True)
    print(name, "scripts ok")
PY
grep -l 'href="my_homework.html"' dashboard.html tracking.html recommendation.html homework.html demo_library.html annotation.html cdm_report.html knowledge_graph.html sing_along.html AI_teacher.html cat_test.html | wc -l
```

预期：`my_homework.html scripts ok`，然后 `11`。

- [ ] **Step 8: 验证登录保护**

```bash
curl -s -o /dev/null -w 'anon: %{http_code}\n' http://127.0.0.1/my_homework.html
```

预期 `anon: 302`（未登录跳 `/login.html`）。

- [ ] **Step 9: 提交**

```bash
git add my_homework.html app/pages.py dashboard.html tracking.html recommendation.html homework.html demo_library.html annotation.html cdm_report.html knowledge_graph.html sing_along.html AI_teacher.html cat_test.html
git commit -m "feat: 新增我的作业页并接入学生导航

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 9: `sing_along.html` 作业模式

**Files:**
- Modify: `sing_along.html`（样式、横幅、全局状态、数据加载、录音、初始化）

**Interfaces:**
- Consumes: Task 6 的 `GET /api/homeworks/mine/<id>` 与 `POST /api/homeworks/<id>/submit`。
- Produces: `sing_along.html?homework_id=<id>` 的作业模式；不改变普通跟唱模式。

- [ ] **Step 1: 加作业横幅样式**

在 `sing_along.html` 的 `</style>` 之前（角色显示规则之后）加：

```css
        /* ===== 作业模式横幅 ===== */
        .homework-banner{display:flex;align-items:center;gap:12px;flex-wrap:wrap;
          background:var(--primary-soft);border:1px solid var(--primary-border);
          border-radius:10px;padding:10px 14px;margin-bottom:14px}
        .homework-banner .hb-title{font-weight:700;color:var(--text-primary)}
        .homework-banner .hb-meta{font-size:13px;color:var(--text-secondary)}
        .homework-banner .hb-status{margin-left:auto;font-size:13px;font-weight:700;color:var(--primary)}
```

- [ ] **Step 2: 加横幅标记**

在 `page-header` 的 `</div>`（第 513 行）之后、第一个 `.card` 之前插入：

```html
    <!-- 作业模式横幅：无 homework_id 时保持 display:none，普通跟唱不受影响 -->
    <div class="homework-banner" id="homeworkBanner" style="display:none">
      <span class="hb-title" id="hbTitle"></span>
      <span class="hb-meta" id="hbMeta"></span>
      <span class="hb-status" id="hbStatus"></span>
    </div>
```

- [ ] **Step 3: 加全局状态**

在 `lastPracticeToken` 之后：

```js
// ===== 作业模式（URL 带 homework_id 时启用）=====
// homeworkSubmitted 覆盖两种情形：本次刚提交成功，以及页面加载时服务端已有提交。
let homeworkId = (() => {
  const raw = new URLSearchParams(location.search).get("homework_id");
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 ? n : null;
})();
let homework = null;           // 作业详情；加载失败时退回普通跟唱模式
let homeworkSubmitted = false; // 已提交（含加载时已有提交），录音按钮锁定
```

- [ ] **Step 4: 改 `loadDemos` 锁定作业曲目**

把：

```js
  sel.value = String(demos[0].id);
  // 程序化赋值不触发 onchange，而 currentDemoId 只在 changePiece 里赋值；
  // 库里只有一个曲目时用户也点不出 change 事件，分段列表会永远停在空态。
  await changePiece();
```

改成：

```js
  // 作业模式锁定到作业指定的曲目；该曲目不在 C1 列表里时退回第一条，
  // 录音按钮仍会被 updateHomeworkLock 锁住（作业没有可提交的唱段）。
  const lockedDemo = homeworkId && homework && homework.demo_id != null
    ? demos.find(d => d.id === homework.demo_id)
    : null;
  sel.value = String(lockedDemo ? lockedDemo.id : demos[0].id);
  // 程序化赋值不触发 onchange，而 currentDemoId 只在 changePiece 里赋值；
  // 库里只有一个曲目时用户也点不出 change 事件，分段列表会永远停在空态。
  await changePiece();
```

- [ ] **Step 5: 改 `loadSegments` 过滤作业唱段**

在 `segments = await apiGet(...)` 之后加：

```js
  // 作业模式只保留作业范围内的唱段（后端按当前 segments 表求过交，
  // 这里再按 id 过滤一次，防止 C2 的段集合与详情不是同一时刻的快照）。
  if (homeworkId && homework) {
    const allowed = new Set(homework.allowed_segment_ids || []);
    segments = segments.filter(s => allowed.has(s.id));
  }
```

- [ ] **Step 6: 改 `renderSegments` 的空态文案**

把：

```js
  if (segments.length === 0) {
    container.innerHTML = `<span style="color:var(--text-muted);font-size:14px;">该曲目还没解析出唱段。</span>`;
    return;
  }
```

改成：

```js
  if (segments.length === 0) {
    const msg = homeworkId && homework
      ? "该作业没有可提交的唱段。"
      : "该曲目还没解析出唱段。";
    container.innerHTML = `<span style="color:var(--text-muted);font-size:14px;">${msg}</span>`;
    return;
  }
```

- [ ] **Step 7: `selectSegment` 跳过 D3**

把：

```js
  lastEl.textContent = "";
  loadLastPractice(seg.id);
```

改成：

```js
  lastEl.textContent = "";
  // 作业模式不读 D3：练习记录不是作业成绩，贴上来会被误认成本次作业结果。
  if (!homeworkId) loadLastPractice(seg.id);
```

- [ ] **Step 8: `toggleRecord` 加作业守卫**

在 `if (isAnalyzing)` 之后、`if (currentSegmentIdx < 0)` 之前插入：

```js
  if (homeworkId) {
    if (!homework) { alert("作业信息还没加载完成"); return; }
    if (homeworkSubmitted) { alert("该作业已提交，不能重复录制"); return; }
    if (!homework.can_submit) { alert("该作业没有可提交的唱段"); return; }
    if (homework.demo_id != null && currentDemoId !== homework.demo_id) {
      alert("作业模式只能练习作业指定的曲目"); return;
    }
  }
```

- [ ] **Step 9: `stopRecordingAndAnalyze` 重新套锁**

在 `document.getElementById("btnStop").style.display = "none";` 之后加：

```js
  updateHomeworkLock();
```

- [ ] **Step 10: `analyzeRecording` 分叉到 F3**

把第 1864-1884 行的整段（从 `const subForm = new FormData();` 到 `finally` 结束）替换为：

```js
    const subForm = new FormData();
    subForm.append("segment_id", String(seg.id));
    subForm.append("audio_id", String(up.file_id));
    let sub;
    if (homeworkId) {
      // F3：作业提交。成功即锁定录音（一份作业只收一次），随后照常轮询
      // B3/B4 拿本次分析的五维与逐字结果。
      sub = await apiPostForm(`/api/homeworks/${homeworkId}/submit`, subForm);
      homeworkSubmitted = true;
      renderHomeworkBanner();
      updateHomeworkLock();
      addLog("作业已提交，AI 分析中…", "success");
      await refreshHomework();
    } else {
      subForm.append("duration_sec", wav.duration.toFixed(2));
      sub = await apiPostForm("/api/practice/submit", subForm);
    }

    const result = await pollAnalysis(sub.task_id);
    const cur = segments[currentSegmentIdx];
    // 分析期间切了段：结果属于上一段，不往新段的面板上贴
    if (cur && cur.id === seg.id) {
      renderAnalysisResult(result);
      const overall = Number.isFinite(result.overall) ? Math.round(result.overall) : "—";
      addLog(`✅ 分析完成！综合评分: ${overall} 分`, "success");
      if (!homeworkId) loadLastPractice(seg.id);
    }
    // 提交已经落库，与「当前有没有停在原分段」无关，作业状态都要刷新
    if (homeworkId) await refreshHomework();
  } catch (e) {
    addLog(`分析失败：${e.message}`, "error");
    // 作业模式下以服务端为准：F3 若回 422「已提交」或上方已提交但分析失败，
    // 刷新详情能把「占位行已被 worker 删除、可以重交」与「确实已提交」分开。
    if (homeworkId) {
      await refreshHomework();
      if (homeworkSubmitted) {
        // worker 的失败分支先写 failed 状态、再删占位行，两步之间有一个
        // 很窄的窗口。刷新正好落在窗口里时会看到「已提交」，稍等再刷一次。
        await new Promise(r => setTimeout(r, 1200));
        await refreshHomework();
      }
      // 服务端仍认为「已提交」时不覆盖状态（F3 的 422 竞态就是这种情形）；
      // 占位行已被 worker 删掉时，把失败原因写在横幅上（spec 7.3）。
      if (!homeworkSubmitted) {
        document.getElementById("hbStatus").textContent = `分析失败：${e.message}`;
      }
    }
  } finally {
    isAnalyzing = false;
    btnRecord.disabled = false;
    updateHomeworkLock();
  }
```

- [ ] **Step 11: 加作业模式函数**

在 `changePiece` 之后、窗口自适应之前插入：

```js
// ============================================================
// 作业模式
// ============================================================
async function enterHomeworkMode() {
  try {
    homework = await apiGet(`/api/homeworks/mine/${homeworkId}`);
  } catch (e) {
    // 教师打开带参 URL 会 403；作业被删是 404。两种情况都退回普通跟唱，
    // 不把整个页面卡死在一个进不去的模式里。
    addLog(`作业信息加载失败（${e.message}），已退回普通跟唱模式`, "warn");
    homeworkId = null;
    homework = null;
    return;
  }
  homeworkSubmitted = !!homework.submission;
  document.getElementById("pieceSelect").disabled = homework.demo_id != null;
  renderHomeworkBanner();
  updateHomeworkLock();
}

async function refreshHomework() {
  if (!homeworkId) return;
  try {
    homework = await apiGet(`/api/homeworks/mine/${homeworkId}`);
    homeworkSubmitted = !!homework.submission;
  } catch (e) {
    addLog(`刷新作业状态失败：${e.message}`, "warn");
  }
  renderHomeworkBanner();
  updateHomeworkLock();
}

function renderHomeworkBanner() {
  const box = document.getElementById("homeworkBanner");
  if (!homeworkId) { box.style.display = "none"; return; }
  box.style.display = "flex";
  document.getElementById("hbTitle").textContent = homework ? homework.title : "作业";

  const bits = [];
  if (homework) {
    bits.push("🎵 " + (homework.demo_title || "未挂曲目"));
    bits.push(homework.deadline ? "截止 " + homework.deadline : "未设截止");
    if (homework.overdue) bits.push("已逾期");
    const skills = Array.isArray(homework.focus_skills) && homework.focus_skills.length
      ? homework.focus_skills.join("、") : "未指定";
    bits.push("重点 " + skills);
  }
  document.getElementById("hbMeta").textContent = bits.join(" · ");

  let status = "加载中…";
  if (homework) {
    const sub = homework.submission;
    if (sub) {
      if (sub.status === "submitted") {
        status = "已提交，AI 分析中…";
      } else if (sub.status === "reviewed") {
        status = "已批改" + (sub.teacher_score != null ? `（教师分 ${sub.teacher_score}）` : "");
      } else {
        status = "已提交" + (sub.ai_score != null ? `（AI 分 ${sub.ai_score}）` : "");
      }
    } else if (!homework.can_submit) {
      status = "该作业没有可提交的唱段";
    } else {
      status = homework.overdue ? "已逾期，仍可提交" : "可提交";
    }
  }
  document.getElementById("hbStatus").textContent = status;
}

function updateHomeworkLock() {
  if (!homeworkId) return;
  const btn = document.getElementById("btnRecord");
  const locked = !homework || homeworkSubmitted || !homework.can_submit;
  btn.disabled = locked;
  btn.style.opacity = locked ? "0.55" : "";
  btn.style.cursor = locked ? "not-allowed" : "";
}
```

- [ ] **Step 12: 改 `init`**

把 `init()` 替换为：

```js
async function init() {
  initCanvas();
  drawEmptyState();
  renderSegments();
  renderTeacherTips();
  if (homeworkId) await enterHomeworkMode();
  try {
    await loadDemos();
    // loadDemos → changePiece → stopAll() 会把 btnRecord.disabled 重置成 false，
    // 必须在它之后再套一次锁，否则「已提交 / 无可提交唱段」的作业按钮看着可点。
    updateHomeworkLock();
    addLog(homeworkId
      ? "📝 作业模式已加载，选择作业要求的分段开始录制"
      : "🚀 智能陪练已加载，选择曲目和段落开始练习", "info");
  } catch (e) {
    addLog(`加载曲目列表失败：${e.message}`, "error");
  }
}
```

- [ ] **Step 13: 语法检查**

```bash
.venv/bin/python - <<'PY'
import pathlib, re, subprocess, tempfile
html = pathlib.Path("sing_along.html").read_text(encoding="utf-8")
for i, code in enumerate(re.findall(r"<script>(.*?)</script>", html, re.S)):
    p = pathlib.Path(tempfile.mkdtemp()) / f"{i}.js"
    p.write_text(code, encoding="utf-8")
    subprocess.run(["node", "--check", str(p)], check=True)
print("sing_along scripts ok")
PY
```

预期：`sing_along scripts ok`。

- [ ] **Step 14: 提交**

```bash
git add sing_along.html
git commit -m "feat: 跟唱页支持作业模式

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 10: 前后端联调、回归与文档

**Files:**
- Modify: `CLAUDE.md`
- Verify: `DOC_ISSUES.md` 第 46 条
- Verify: 全部冒烟脚本

**Interfaces:**
- Consumes: Task 1–9 的全部产物。
- Produces: 可复现的验收记录与项目说明。

- [ ] **Step 1: 确认后端与两个 worker 都在跑**

```bash
# 终端 1
.venv/bin/python app-d.py

# 终端 2（B 组分析 / D1 / F3 都靠它）
.venv/bin/celery -A app.worker:celery_app worker -n default@%h --loglevel=info --concurrency=2

# 终端 3（示范库解析；本任务不需要，但保持与 CLAUDE.md 一致）
.venv/bin/celery -A app.worker:celery_app worker -Q demucs -n demucs@%h --concurrency=1 --loglevel=info
```

- [ ] **Step 2: `/browse` 学生端验收**

调用 `/browse` 技能，执行：

1. 打开 `http://127.0.0.1/login.html`，用 `stu001 / xiyun@2026` 登录。
2. 打开 `http://127.0.0.1/my_homework.html`：
   - 左侧有作业卡片；状态徽标与「待批改 / 已批改 / 已逾期」正确；
   - 点第一张卡片，右侧显示重点技法、可选段数、提交结果；
   - 无提交的作业显示「去完成」，已逾期的另显示「已逾期，仍可提交」。
3. 点「去完成」：
   - URL 变为 `sing_along.html?homework_id=<id>`；
   - 曲目下拉被锁定且是作业曲目；分段列表只剩作业范围；
   - 页面顶部横幅显示作业标题、截止日、重点技法与「可提交」。
4. 返回 `my_homework.html`，打开一份已有提交的作业，点「去完成」：
   - 跟唱页横幅显示分数或「分析中」；
   - 录音按钮 `disabled`。
5. 登出，用 `teacher01` 登录，打开 `my_homework.html`：
   - 显示「我的作业仅学生可见」，列表不渲染。

若浏览器没有麦克风权限，不强行跑录音；录音提交链路由 Task 7 的后端冒烟覆盖，页面侧只验「点击后按钮禁用、请求发出」。

- [ ] **Step 3: 回归三条既有冒烟**

```bash
scripts/smoke_auth.sh
scripts/smoke_homework_create.sh
scripts/smoke_analyze.sh
```

预期三条都以 `全部通过` 结束。若 `smoke_homework_create.sh` 因为本次新增的唯一索引失败，先检查是否遗留了上一轮的同名作业（脚本自己会清理），不要放宽索引。

- [ ] **Step 4: 再跑一次新冒烟与 `check_db`**

```bash
scripts/smoke_homework_submit.sh
.venv/bin/python scripts/check_db.py
```

预期：

- 冒烟 `全部通过：<N> 项`；
- `check_db` 的差异只剩 `demo_versions` 与 `teacher_demos` 两处历史漂移，`submissions` 不出现在差异里，计数为 `107 列 / 3 索引`。

- [ ] **Step 5: 更新 `CLAUDE.md`**

在「运行方式」的例外列表里追加一条（放在例外 3 之后）：

```markdown
- **例外 4 — `my_homework.html` 与 `sing_along.html` 的作业模式（2026-10-21 起）**：学生端作业列表/详情走 `GET /api/homeworks/mine` 与 `GET /api/homeworks/mine/<id>`（均挂 `@student_required`），「去完成」跳到 `sing_along.html?homework_id=<id>`。跟唱页在该模式下锁定作业曲目、只保留 `allowed_segment_ids`、不自动选段，停录后走 F3 `POST /api/homeworks/<id>/submit`（multipart：`segment_id` + `audio_id`）→ B3 轮询 → B4 展示。**F3 必须起 Celery default worker**，否则提交行停在 `submitted`（页面显示「分析中」）。一份作业每个学生只收一次提交（唯一索引 `uq_submissions_homework_student`），逾期仍可交；`submissions.segment_id` 是普通 INT、无外键，重解析后可能悬空。设计见 `docs/superpowers/specs/2026-10-21-student-homework-submission-design.md`，口径见 `DOC_ISSUES.md` 第 46 条。
```

在「架构」一节补 `my_homework.html` 的数据源：

```markdown
- `my_homework.html` 没有 mock 数据：列表、详情、状态全部来自 `GET /api/homeworks/mine` 与 `GET /api/homeworks/mine/<id>`，教师访问显示「我的作业仅学生可见」。「去完成」只跳转 `sing_along.html?homework_id=<id>`，不在本页录音。
```

数据库一节把 `check_db.py` 的计数改成实测值：

```text
（当前 15 表 / 107 列 / 23 外键 / 3 索引；真库另有两处历史漂移：多了 demo_versions 表、teacher_demos 多 parse_time_sec/parse_status/techniques_json 三列，见 DOC_ISSUES 第 46 条之外的既有记录）
```

- [ ] **Step 6: 核对 `DOC_ISSUES.md` 第 46 条**

打开第 46 条，确认以下口径与实际实现一致；不一致就改这一条（**不要改需求文档**）：

- 两条 GET 的路径与字段名；
- F3 请求字段 `segment_id` / `audio_id`；
- `status='submitted'` → worker 回填 `ai_scored`；
- 唯一索引名 `uq_submissions_homework_student`；
- `segment_id` 无外键；
- 逾期口径；
- `ai_detail` 三键；
- BKT `source_type='homework'`。

- [ ] **Step 7: 提交文档**

```bash
git add CLAUDE.md DOC_ISSUES.md
git commit -m "docs: 同步学生提交作业链路说明

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## 自检记录（写完计划后核对）

- **Spec 覆盖**：4.1/4.2 → Task 3-6；4.3 → Task 5-6；4.4 → Task 6；5.1-5.3 → Task 2、5；6 → Task 8；7 → Task 9；8 → Task 8；9 → Task 10；10 → Task 2、5、7、10；11 → `DOC_ISSUES.md` 第 46 条已覆盖；12 → 任务顺序一致。
- **占位扫描**：没有 TBD/TODO；页面共享 CSS 用「复制 `sing_along.html` 的精确行号」而不是「类似上一页」；每个代码步骤都给了可执行代码或精确改动位置。
- **类型一致**：`StudentHomeworkDetail` 覆写 `submission` 为 `StudentSubmissionDetail`（Pydantic v2 已验证可行）；`apply_bkt` 的 `before/after` 与 `_bkt_changes` 的扁平字典形状一致；`persist` 在 `submit` / `_dispatch` / `run_analysis` / `_analyze` 四处同名。
- **已知偏差**：`check_db.py` 基线本来就是红的，验收标准改为「submissions 差异消失 + 计数 107/3」，已在 Global Constraints 与 Task 1 写明。
- **Review 修正**：Task 4 的验证片段不再重复传 `submission`（`model_dump()` 已含该键）；Task 9 的 `init()` 在 `loadDemos()` 之后补调 `updateHomeworkLock()`（`changePiece → stopAll` 会重置 `btnRecord.disabled`）；B3 失败后隔 1.2 秒二次刷新，避开 worker「先写 failed、再删占位行」的窄窗口；`wordClass` 先挡 `null`（`Number(null) === 0` 会被误判成绿色）；导航缩进按实测修正（`sing_along.html:496` 是 6 空格，不是 4）。
