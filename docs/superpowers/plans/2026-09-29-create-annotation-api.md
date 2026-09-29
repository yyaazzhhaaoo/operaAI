# 新增标注接口（C5 `POST /api/annotations`）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 C5——把标注页的「添加标注」按钮接上真写入链路，让老师标的东西真落 `annotations` 表。

**Architecture:** 自下而上四层各一个小改动（repo 两个查询 → service 的业务判定与事务 → schema 入参模型 → HTTP 路由），再把 `annotation.html` 的 `saveAnnotation` 从「弹未实现」换成真 POST，成功后用返回值本地插入。C6 / C7 两个占位路由原样保留。

**Tech Stack:** Python 3.11 / Flask / SQLAlchemy 2.x / PostgreSQL / pydantic v2 / 原生 JS 单页

**依据 spec:** `docs/superpowers/specs/2026-09-29-create-annotation-api-design.md`

## Global Constraints

- **不新增测试框架。** 本仓库没有 `tests/`、`requirements.txt` 里也没有 pytest。验证一律用**对真接口跑的 curl**、`.venv/bin/python` 脚本与 `/browse` 实测。不要 `pip install pytest`。
- **Python 解释器用 `.venv/bin/python`**，先 `cd /Users/meiyazhao/Documents/lianshu/operaAI`。
- **`/api` 前缀只在 `app/api/__init__.py` 的 `url_prefix` 里写一次**，路由写相对路径。
- **响应一律用 `app/response.py` 的 `ok()`**。它固定回 200，**不要为 C5 单独引入 201**。
- **权限是教师**：`@login_required` **加** `@teacher_required`，叠放顺序固定、`login_required` 在外层（同 C4/C6/C7）。
- **不改 `schema.sql` / `app/models/*` / `app-d.py`**，不引 Alembic，不加依赖。
- **只做 C5。** `app/api/demos_segments_annotations.py` 里的 C6（`DELETE /api/annotations/<id>`）与 C7（`GET /api/annotations/rules`）两个占位路由**原样保留，一个字都不要动**；`annotation.html` 的 `deleteAnnotation`、「技法依赖图谱」面板（`TECHNIQUE_DEPS` / `RULE_IMPACT` / `renderDeps`）同样不动。
- **当前真库基线**（2026-09-29 实测）：
  - `annotations` 表 **0 行**——本轮所有验证数据都是**自己写进去的**，每个任务结束时必须删干净、回到 0 行
  - `teacher01` 的 `users.id` 是 **2**（不是 1——id 1 已被删除，序列从 2 起）；`stu001` 是 3
  - `segments` 共 **16 个**：`1, 79, 80, 106, 107, 108, 110–119`，**每个都有歌词**（没有一个 `lyrics_json` 为 NULL）
  - **seg 119**（demo 16 第 10 段「谁料想我五十三岁又管三军」）：12 字，下标 0–11，首字「谁」、末字「军」
  - **seg 110**（同在 demo 16）：10 字，下标 0–9，首字「辕」、末字「震」
  - `_normalize_lyrics` 在这两个唱段上**不丢弃任何条目**（raw 长度 == 归一后长度），所以「归一后长度」就是 12 / 10
  - 两个外键都在：`segment_id → segments(id)`、`teacher_id → users(id)`。**写入必须用真实存在的 id，编一个会当场撞外键**
- **`annotations` 当前 0 行 ⇒「无歌词的唱段」这个分支没法用真数据验**（16 个唱段全都有歌词）。不必为此造数据：那个分支与 `word_index >= n` 是**同一个表达式**（n 为 0 时任何下标都被拒），代码路径已被 seg 110/119 的越界用例覆盖。这一点在 Task 2 的脚本里以注释说明。
- 种子账号 `teacher01` / `stu001`，密码 `xiyun@2026`。
- 注释、commit message 一律中文；标识符英文。

### 验证数据的清理纪律

C5 的验证数据**就是接口自己写出来的行**，所以清理方式与 C4 那轮不同：**不预插、只删自造**。

- 每个任务结束前，用 `RETURNING id` 或响应里的 `data.id` 抓住自己造出来的 id，**按 id 删**
- **绝不** `DELETE FROM annotations WHERE segment_id = ...`：那会连真数据一起删掉
- 每个任务的最后一步都是 `SELECT count(*) FROM annotations;` 回 **0**。**不是 0 就停下来查，不要继续下一个任务**

确认命令：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
docker exec docker_postgres psql -U xiyun -d xiyun -At -c "SELECT count(*) FROM annotations;"
```

---

## 文件结构

| 文件 | 职责 | 本次改动 |
|---|---|---|
| `app/repositories/annotations_repo.py` | 数据访问 | +`get_one` / `add`（保留 `get_annotations_list` / `list_by_segment`） |
| `app/schemas/demo.py` | 入参与出参模型 | +`ANNOTATION_TAGS` / `AnnotationIn`；`AnnotationOut` 补一句 docstring；补 2 个 pydantic import |
| `app/services/library_service.py` | 业务判定与事务边界 | +`create_annotation`；补 1 个 import |
| `app/api/demos_segments_annotations.py` | HTTP 层 | C5 填实现；+`_payload()` 助手；补 2 个 import |
| `annotation.html` | 歌词级标注页 | `saveAnnotation` 改真 POST；+`annLoaded` / `clearTagSelection` / `TOAST_ICON`；`showToast` / `selectChar` / `switchSegment` / `fetchAnnotations` 小改 |
| `DOC_ISSUES.md` | 需求文档问题登记 | +第 30 条 |

---

## Task 1: 数据层——写入仓储 + 入参模型

**Files:**
- Modify: `app/repositories/annotations_repo.py`（末尾追加两个函数）
- Modify: `app/schemas/demo.py`（补 import、末尾追加、改一处 docstring）

**Interfaces:**
- Consumes: 无
- Produces:
  - `annotations_repo.get_one(db: Session, segment_id: int, word_index: int, tag: str) -> Annotation | None`
  - `annotations_repo.add(db: Session, *, segment_id: int, word_index: int, tag: str, tolerance: int | None, teacher_id: int | None) -> Annotation`
  - `app.schemas.demo.ANNOTATION_TAGS: tuple[str, ...]`（六个值）
  - `app.schemas.demo.AnnotationIn`（字段 `segment_id: int` / `word_index: int` / `tag: str` / `tolerance: int | None`）

- [ ] **Step 1: 写验证脚本并确认它失败**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python - <<'PY'
from app.db import SessionLocal
from app.repositories import annotations_repo
from app.schemas.demo import AnnotationIn, AnnotationOut

db = SessionLocal()
try:
    # get_one：不存在的组合回 None
    assert annotations_repo.get_one(db, 119, 0, "拖腔") is None

    # add 只 flush，但 id 与 created_at 必须已经被 RETURNING 填好——
    # 接口层要靠它们直接组装响应，不能等到 commit 之后再回查
    ann = annotations_repo.add(db, segment_id=119, word_index=0, tag="拖腔",
                               tolerance=30, teacher_id=2)
    assert ann.id is not None, "flush 后 id 没填上"
    assert ann.created_at is not None, "flush 后 created_at 没填上"

    # get_one 认得出刚写进去的那条，且唯一键是三列
    got = annotations_repo.get_one(db, 119, 0, "拖腔")
    assert got is not None and got.id == ann.id
    assert annotations_repo.get_one(db, 119, 1, "拖腔") is None, "word_index 没参与判定"
    assert annotations_repo.get_one(db, 119, 0, "滑音") is None, "tag 没参与判定"
    assert annotations_repo.get_one(db, 110, 0, "拖腔") is None, "segment_id 没参与判定"

    # 出参模型
    out = AnnotationOut.model_validate({
        "id": ann.id, "word_index": ann.word_index, "tag": ann.tag,
        "tolerance": ann.tolerance, "created_at": ann.created_at,
    }).model_dump()
    assert set(out) == {"id", "word_index", "tag", "tolerance", "created_at"}, set(out)

    # 入参模型：六个合法 tag 全收
    for tag in ("滑音", "归韵", "换气", "强音", "拖腔", "擞音"):
        assert AnnotationIn.model_validate(
            {"segment_id": 119, "word_index": 0, "tag": tag}).tag == tag

    # 缺 tolerance → None（不是 0）
    assert AnnotationIn.model_validate(
        {"segment_id": 119, "word_index": 0, "tag": "拖腔"}).tolerance is None
    # 边界值收
    for t in (0, 100):
        assert AnnotationIn.model_validate(
            {"segment_id": 119, "word_index": 0, "tag": "拖腔", "tolerance": t}).tolerance == t

    # 该拒的要拒，且 tag 的报错是**中文**
    bad = [{"tag": "乱写"}, {"tag": ""}, {"tolerance": 101}, {"tolerance": -1},
           {"word_index": -1}]
    for over in bad:
        payload = {"segment_id": 119, "word_index": 0, "tag": "拖腔"} | over
        try:
            AnnotationIn.model_validate(payload)
        except Exception as e:
            msg = e.errors()[0]["msg"]
            if "tag" in over and over["tag"] != "拖腔":
                assert "Input should be" not in msg, f"tag 报错透出了英文: {msg}"
            print("  拒绝", over, "->", msg)
        else:
            raise AssertionError(f"该拒绝却没拒绝: {over}")
finally:
    # 全程不 commit：SQLAlchemy 丢弃未提交事务，表保持 0 行
    db.rollback()
    db.close()
print("OK")
PY
```

预期：**ImportError**，`cannot import name 'AnnotationIn'`（`annotations_repo` 是模块导入、函数名要等到调用时才暴露，所以先炸的是这一行）。

- [ ] **Step 2: 实现 repo 的两个函数**

在 `app/repositories/annotations_repo.py` **末尾追加**（`get_annotations_list` / `list_by_segment` 一个字都不动；`select` 已经在文件顶部导入过）：

```python
def get_one(db: Session, segment_id: int, word_index: int, tag: str) -> Annotation | None:
    """按唯一键取一条标注（C5 的重复判定）。

    三列全用上，**不含 teacher_id**：这张表的设计前提是「一个唱段一套全局
    唯一的规则集」（C4 spec 3.4），换个教师再标同字同 tag 一样是重复。

    返回 None 表示「没有」——调用方据此放行写入，不拿它当 404 信号。
    """
    return db.scalar(
        select(Annotation).where(
            Annotation.segment_id == segment_id,
            Annotation.word_index == word_index,
            Annotation.tag == tag,
        )
    )


def add(db: Session, *, segment_id: int, word_index: int, tag: str,
        tolerance: int | None, teacher_id: int | None) -> Annotation:
    """新增一条标注。只 flush 拿自增 id，提交交给 service 层。

    关键字参数：五个字段里有两个是 int、一个可空 int，位置调用时
    `add(db, 119, 0, "拖腔", 30, 2)` 里 `0` 和 `30` 极易写反。

    flush 之后 id 与 created_at 都已被 RETURNING 填好，调用方可以直接组装
    响应，不必 commit 之后再回查一次。
    """
    ann = Annotation(
        segment_id=segment_id,
        word_index=word_index,
        tag=tag,
        tolerance=tolerance,
        teacher_id=teacher_id,
    )
    db.add(ann)
    db.flush()          # 只为拿到自增 id 与 created_at，提交由 service 层负责
    return ann
```

- [ ] **Step 3: 补 `app/schemas/demo.py` 的 import**

当前第 1 行往后是 `from datetime import datetime` / `from pydantic import BaseModel, ConfigDict`。把 pydantic 那行改成：

```python
from pydantic import BaseModel, ConfigDict, Field, field_validator
```

- [ ] **Step 4: 加词表与 `AnnotationIn`**

在 `app/schemas/demo.py` **文件末尾追加**：

```python
# 标注技法词表（C5 入参 tag 的合法取值域）。
# 三处同源：本元组、annotation.html 六个类型按钮的 data-tag（第 492–497 行）、
# app/models/annotation.py 的类注释。将来按 tag 派发评测规则时，词表外的值
# 无法处理，所以在写入端就挡住。
ANNOTATION_TAGS = ("滑音", "归韵", "换气", "强音", "拖腔", "擞音")


class AnnotationIn(BaseModel):
    """C5 入参（`POST /api/annotations`）。

    **`teacher_id` 不在入参里**：从会话取（api 层传 `current_user_id()`）。
    让客户端指定归属等于开一个「以别人的名义标注」的越权入口。

    `tolerance` 可选：列在 DDL 上可空，C4 出参 `AnnotationOut` 也已允许 null。
    前端滑块总有值，但接口不必替调用方决定这个值一定存在。

    `word_index` 这里**只判非负**，上界在 service 判——上界要查 segments 与
    lyrics_json 才能算出来，是业务规则，不是入参格式。
    """

    segment_id: int
    word_index: int = Field(ge=0)
    tag: str
    tolerance: int | None = Field(default=None, ge=0, le=100)

    @field_validator("tag")
    @classmethod
    def _known_tag(cls, v: str) -> str:
        # 不用 Literal[...]：pydantic 对它的报错 type 是 literal_error，
        # app/common/errors.py 的 _MSG_CN 里没有这个映射，会回退成英文原文
        # "Input should be '滑音', '归韵', ..." 直接透给中文 UI。
        # 自定义 validator 抛的 ValueError 走的是 _MSG_CN 注释里的第 ②条路径，
        # 去掉 "Value error, " 前缀后原样展示。
        if v not in ANNOTATION_TAGS:
            raise ValueError("取值必须是 " + "/".join(ANNOTATION_TAGS) + " 之一")
        return v
```

- [ ] **Step 5: 改 `AnnotationOut` 的 docstring**

首行现在是：

```python
    """标注列表行（C4 `GET /api/segments/<id>/annotations`）。
```

改成：

```python
    """标注行。C4 `GET /api/segments/<id>/annotations` 的列表元素，
    **也是 C5 `POST /api/annotations` 的响应体**——同一个资源的同一形状，
    分成两个类只会在字段漂移时多一处要改。
```

其余段落一个字不动。

- [ ] **Step 6: 重跑验证脚本，确认通过**

重跑 Step 1 的同一条命令。

预期：五行 `拒绝 {...} -> ...` 加最后一行 `OK`。`拒绝 {'tag': '乱写'}` 那行的消息形如 `Value error, 取值必须是 滑音/归韵/换气/强音/拖腔/擞音 之一`（`Value error, ` 前缀是 pydantic 加的，接口层会去掉它）。

- [ ] **Step 7: 确认表仍是 0 行**

跑「验证数据的清理纪律」一节的**确认命令**。预期输出 `0`——Step 1 的脚本全程没 commit，事务被 `rollback()` 丢弃。

- [ ] **Step 8: Commit**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add app/repositories/annotations_repo.py app/schemas/demo.py
git commit -m "feat: 新增标注写入仓储与入参模型（C5 数据层）"
```

---

## Task 2: 业务层——`create_annotation`

**Files:**
- Modify: `app/services/library_service.py`（补 1 个 import，末尾追加）

**Interfaces:**
- Consumes: Task 1 的 `annotations_repo.get_one` / `annotations_repo.add`
- Produces: `library_service.create_annotation(db: Session, *, segment_id: int, word_index: int, tag: str, tolerance: int | None, teacher_id: int | None) -> dict`
  - 返回 dict 恰好 5 个键：`id` / `word_index` / `tag` / `tolerance` / `created_at`
  - 失败时抛 `BusinessError`：`404` 唱段不存在 / `422` 下标越界 / `409` 重复

- [ ] **Step 1: 写验证脚本并确认它失败**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python - <<'PY'
from sqlalchemy import delete, func, select

from app.common.errors import BusinessError
from app.db import SessionLocal
from app.models import Annotation
from app.services import library_service

db = SessionLocal()
made = []
try:
    base = dict(segment_id=119, word_index=0, tag="拖腔", tolerance=30)

    def call(**over):
        return library_service.create_annotation(db, teacher_id=2, **(base | over))

    def expect(code, **over):
        try:
            call(**over)
        except BusinessError as e:
            assert e.code == code, f"预期 {code}，实际 {e.code}（{e.message}）"
            return e.message
        raise AssertionError(f"预期 {code}，却成功了: {over}")

    # —— 失败路径（都不该写库）——
    print("404 唱段不存在:", expect(404, segment_id=99999))
    print("422 下标越界  :", expect(422, word_index=12))                  # seg 119 只有 0–11
    print("422 下标越界  :", expect(422, segment_id=110, word_index=10))  # seg 110 只有 0–9

    # —— 成功路径 ——
    row = call()
    made.append(row["id"])
    assert set(row) == {"id", "word_index", "tag", "tolerance", "created_at"}, set(row)
    assert (row["word_index"], row["tag"], row["tolerance"]) == (0, "拖腔", 30), row
    assert row["created_at"] is not None, "created_at 没填上"
    print("200 新建      :", row)

    # 上界是**按唱段**算的，不是一个全局常量：同一个字 9 在 110 合法
    row2 = call(segment_id=110, word_index=9, tag="擞音", tolerance=None)
    made.append(row2["id"])
    assert row2["tolerance"] is None, f"tolerance 没传时该是 None，实际 {row2['tolerance']!r}"
    print("200 tol=None  :", row2)

    # 重复 → 409；同字换 tag 合法（UNIQUE 是三列）
    print("409 重复      :", expect(409))
    row3 = call(tag="滑音")
    made.append(row3["id"])
    print("200 同字换tag :", row3)

    # 失败路径确实没写库：成功 3 条，库里就该只有 3 条
    n = db.scalar(select(func.count()).select_from(Annotation))
    assert n == 3, f"预期库里 3 行，实际 {n}"
    print("库内行数      :", n)

    # teacher_id 是调用方传进来的那个
    a = db.scalar(select(Annotation).where(Annotation.id == row["id"]))
    assert a.teacher_id == 2, f"teacher_id 没落库: {a.teacher_id}"
    print("teacher_id    :", a.teacher_id)
finally:
    # 清理：只删自己造的那几行，按 id 删
    db.rollback()
    if made:
        db.execute(delete(Annotation).where(Annotation.id.in_(made)))
        db.commit()
    db.close()
    print("已清理 id:", made)
print("OK")
PY
```

预期：**AttributeError**，`module 'app.services.library_service' has no attribute 'create_annotation'`。

> **「无歌词的唱段」这个分支没有单独用例**：`annotations` 表 0 行、16 个唱段又全都有歌词，造不出这种数据。不必为此硬造——那个分支走的是 `word_index >= n` 这**同一个表达式**（n 为 0 时任何下标都被拒），已被上面 seg 110 / 119 的越界用例覆盖。

- [ ] **Step 2: 补 `library_service.py` 的 import**

当前：

```python
from sqlalchemy.orm import Session
```

改成：

```python
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
```

- [ ] **Step 3: 实现 `create_annotation`**

在 `app/services/library_service.py` **末尾追加**（`_normalize_lyrics` 定义在本文件前面，直接用）：

```python
def create_annotation(db: Session, *, segment_id: int, word_index: int, tag: str,
                      tolerance: int | None, teacher_id: int | None) -> dict:
    """C5 新增标注。返回新建的行，形状与 C4 列表行相同。

    关键字参数：两个 int 加一个可空 int，位置调用时极易写反。

    判定顺序 —— **segment 存在性 → 下标范围 → 重复**：

    - 唱段不存在抛 404（同 C3/C4，必须显式查 segments）
    - 下标越界抛 422。上界按 **C3 归一后**的歌词长度算，与 C3 出参、前端歌词
      网格**同一个函数**——三者必须同源，否则会出现「接口说越界、页面上却
      有这个字」。C4 spec 5.5 对出参采取「越界保留、首列显示 ?」是为了让**已有
      的**脏数据可见；这里挡住是为了**不再生产**脏数据，两者不冲突
    - 同字同 tag 已存在抛 409（`UNIQUE(segment_id, word_index, tag)`）

    tag 的取值域与 tolerance 的 0–100 在 `AnnotationIn` 已经挡下，本层不重复判。

    返回 dict 而不是 ORM 对象：同 segment_annotations / demo_list 的风格，
    api 层直接喂给 pydantic。**字典在 commit 之前就组装好**——commit 会让
    ORM 实例的属性过期，之后再读会多发一次 SELECT。
    """
    seg = library_repo.get_segment(db, segment_id)
    if seg is None:
        raise BusinessError(404, "唱段不存在")

    n = len(_normalize_lyrics(seg.lyrics_json))
    if word_index >= n:
        # BusinessError 的消息不会被加字段名前缀（那是 pydantic 的 loc 拼的），
        # 所以这里要把上下文写全，前端 toast 直接展示这一句
        raise BusinessError(422, f"该唱段共 {n} 个字，word_index 必须在 0 到 {n - 1} 之间")

    if annotations_repo.get_one(db, segment_id, word_index, tag) is not None:
        raise BusinessError(409, "该字已标注此技法")

    try:
        ann = annotations_repo.add(
            db, segment_id=segment_id, word_index=word_index, tag=tag,
            tolerance=tolerance, teacher_id=teacher_id,
        )
    except IntegrityError:
        # 这里只会是唯一约束冲突：其余约束都已被前面的判定与 AnnotationIn 挡下
        # （segment_id 的外键由 404 判定、teacher_id 来自有效会话、tolerance 的
        # CHECK 由入参模型保证、word_index / tag 的 NOT NULL 由必填保证）。
        # **将来给 annotations 加新约束时，要回头重看这个假设。**
        # rollback 是必需的：flush 失败后会话处于不可用状态，不回滚就不能再
        # 执行任何语句（get_db() 只在 teardown 时 close()，不替这里回滚）。
        db.rollback()
        raise BusinessError(409, "该字已标注此技法") from None

    row = {
        "id": ann.id,
        "word_index": ann.word_index,
        "tag": ann.tag,
        "tolerance": ann.tolerance,
        "created_at": ann.created_at,
    }
    db.commit()
    return row
```

**前提检查**：`library_repo` 与 `annotations_repo` 都已在文件顶部导入（C4 那轮加过），`BusinessError` 也已导入。**若报 NameError，先看这两行 import 在不在，不要新增重复导入。**

- [ ] **Step 4: 重跑验证脚本，确认通过**

重跑 Step 1 的同一条命令。

预期：

```
404 唱段不存在: 唱段不存在
422 下标越界  : 该唱段共 12 个字，word_index 必须在 0 到 11 之间
422 下标越界  : 该唱段共 10 个字，word_index 必须在 0 到 9 之间
200 新建      : {'id': ..., 'word_index': 0, 'tag': '拖腔', 'tolerance': 30, 'created_at': datetime...}
200 tol=None  : {... 'tolerance': None ...}
409 重复      : 该字已标注此技法
200 同字换tag : {... 'tag': '滑音' ...}
库内行数      : 3
teacher_id    : 2
已清理 id: [...]
OK
```

第 3 行的 `10 个字`（不是 12）是**关键**：它证明上界按唱段算，不是抄了一个全局常量。

- [ ] **Step 5: 确认表回到 0 行**

跑「验证数据的清理纪律」一节的**确认命令**。预期输出 `0`。

- [ ] **Step 6: Commit**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add app/services/library_service.py
git commit -m "feat: 新增标注写入业务逻辑与事务边界（C5 service）"
```

---

## Task 3: 接口层——路由 + curl 全边界验证

**Files:**
- Modify: `app/api/demos_segments_annotations.py`（补 2 个 import，加 `_payload()`，填掉 C5 占位）

**Interfaces:**
- Consumes: Task 2 的 `library_service.create_annotation`、Task 1 的 `AnnotationIn`
- Produces: `POST /api/annotations` —— 教师可见

- [ ] **Step 1: 补 import**

当前第 4 行：

```python
from app.common.decorators import login_required, teacher_required
```

改成：

```python
from app.common.decorators import current_user_id, login_required, teacher_required
```

当前第 7 行：

```python
from app.schemas.demo import AnnotationOut, DemoListOut, DemoSegmentOut, SegmentDetailOut
```

改成：

```python
from app.schemas.demo import AnnotationIn, AnnotationOut, DemoListOut, DemoSegmentOut, SegmentDetailOut
```

- [ ] **Step 2: 加 `_payload()` 助手**

在 import 段之后、`@api_bp.route("/demos", ...)` 之前插入（与 `auth.py:27` / `audio_analyze.py:28` 是同一个实现——API 层只做「校验入参 → 调 service → 组装响应」，不写业务规则）：

```python
def _payload() -> dict:
    """取 JSON 请求体。

    客户端没带 Content-Type: application/json 时 get_json() 会抛 415；
    silent=True 把它压成 None，这里再兜成 {}，让 pydantic 报「字段必填」
    而不是让 Flask 抛一个前端看不懂的 415。
    """
    return request.get_json(silent=True) or {}
```

- [ ] **Step 3: 填掉 C5 占位路由**

当前（第 72-76 行）：

```python
@api_bp.route("/annotations",methods=["POST"])
@login_required
@teacher_required
def annotations():
    return ok()
```

改成：

```python
@api_bp.route("/annotations", methods=["POST"])
@login_required
@teacher_required
def annotations():
    """C5 新增标注。返回新建的那一行。

    **权限是教师**（文档 C5 的权限列就是「教师」），与同组的 C4/C6/C7 一致。

    `teacher_id` **从会话取**，不进请求体：让客户端指定归属等于开一个
    「以别人的名义标注」的越权入口，而接口没有任何理由需要它。

    成功回 200 不是 201：ok() 固定 200，auth/login 等既有 POST 也全走 200，
    为一个接口单独引入 201 会让「code 与 HTTP 状态码一致」多一个例外。

    校验顺序：pydantic 在本层先跑，service 的 404 判定在后。所以
    「segment_id 不存在 **且** tag 非法」回的是 422 而不是 404——参数合法性
    优先于资源存在性。调用方若按「先 404 后 422」写分支会踩到。
    """
    data = AnnotationIn.model_validate(_payload())
    row = library_service.create_annotation(
        get_db(),
        segment_id=data.segment_id,
        word_index=data.word_index,
        tag=data.tag,
        tolerance=data.tolerance,
        teacher_id=current_user_id(),
    )
    return ok(AnnotationOut.model_validate(row).model_dump(mode="json"))
```

**不要顺手改下面 C6 / C7 那两个占位路由**：`DELETE /api/annotations/<id>` 与 `GET /api/annotations/rules` 本轮不做，原样保留。

- [ ] **Step 4: 重启后端并登录**

`app-d.py` 没有 debug 自动重载，改了代码**必须重启**：

```bash
pkill -f 'app-d.py'; sleep 1
cd /Users/meiyazhao/Documents/lianshu/operaAI && (.venv/bin/python app-d.py > /tmp/xiyun-api.log 2>&1 &)
for i in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:8877/login.html && break; sleep 0.5; done
curl -s -o /dev/null -w 'login.html=%{http_code}\n' http://127.0.0.1:8877/login.html
curl -s -c /tmp/t.jar -X POST -H 'Content-Type: application/json' -d '{"username":"teacher01","password":"xiyun@2026"}' http://127.0.0.1:8877/api/auth/login > /dev/null
curl -s -c /tmp/s.jar -X POST -H 'Content-Type: application/json' -d '{"username":"stu001","password":"xiyun@2026"}' http://127.0.0.1:8877/api/auth/login > /dev/null
echo 登录完成
```

预期 `login.html=200` 加 `登录完成`。

> **重启会把已登录的浏览会话踢掉**：`/browse` 的 daemon 在 Task 4 里要重新登一次。

- [ ] **Step 5: 验证——权限与入参校验（都不该写库）**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
U=http://127.0.0.1:8877/api/annotations
J='Content-Type: application/json'
GOOD='{"segment_id":119,"word_index":0,"tag":"拖腔","tolerance":30}'

echo "1  未登录        :"; curl -s        -H "$J" -X POST -d "$GOOD" -w ' [%{http_code}]\n' $U
echo "2  学生          :"; curl -s -b /tmp/s.jar -H "$J" -X POST -d "$GOOD" -w ' [%{http_code}]\n' $U
echo "3  唱段不存在    :"; curl -s -b /tmp/t.jar -H "$J" -X POST -d '{"segment_id":99999,"word_index":0,"tag":"拖腔"}' -w ' [%{http_code}]\n' $U
echo "4  下标越界 119  :"; curl -s -b /tmp/t.jar -H "$J" -X POST -d '{"segment_id":119,"word_index":12,"tag":"拖腔"}' -w ' [%{http_code}]\n' $U
echo "5  下标越界 110  :"; curl -s -b /tmp/t.jar -H "$J" -X POST -d '{"segment_id":110,"word_index":10,"tag":"拖腔"}' -w ' [%{http_code}]\n' $U
echo "6  下标为负      :"; curl -s -b /tmp/t.jar -H "$J" -X POST -d '{"segment_id":119,"word_index":-1,"tag":"拖腔"}' -w ' [%{http_code}]\n' $U
echo "7  tag 不在词表  :"; curl -s -b /tmp/t.jar -H "$J" -X POST -d '{"segment_id":119,"word_index":0,"tag":"乱写"}' -w ' [%{http_code}]\n' $U
echo "8  tolerance 101 :"; curl -s -b /tmp/t.jar -H "$J" -X POST -d '{"segment_id":119,"word_index":0,"tag":"拖腔","tolerance":101}' -w ' [%{http_code}]\n' $U
echo "9  tolerance -1  :"; curl -s -b /tmp/t.jar -H "$J" -X POST -d '{"segment_id":119,"word_index":0,"tag":"拖腔","tolerance":-1}' -w ' [%{http_code}]\n' $U
echo "10 缺 tag        :"; curl -s -b /tmp/t.jar -H "$J" -X POST -d '{"segment_id":119,"word_index":0}' -w ' [%{http_code}]\n' $U
echo "11 空 body       :"; curl -s -b /tmp/t.jar -H "$J" -X POST -d '{}' -w ' [%{http_code}]\n' $U
echo "12 无 Content-Type:"; curl -s -b /tmp/t.jar -X POST -d "$GOOD" -w ' [%{http_code}]\n' $U
echo "13 非法body+404段:"; curl -s -b /tmp/t.jar -H "$J" -X POST -d '{"segment_id":99999,"tag":"乱写"}' -w ' [%{http_code}]\n' $U
```

预期（逐行核对）：

```
1  未登录        : {"code":401,"message":"未登录","data":null} [401]
2  学生          : {"code":403,"message":"需要教师权限","data":null} [403]
3  唱段不存在    : {"code":404,"message":"唱段不存在","data":null} [404]
4  下标越界 119  : {"code":422,"message":"该唱段共 12 个字，word_index 必须在 0 到 11 之间","data":null} [422]
5  下标越界 110  : {"code":422,"message":"该唱段共 10 个字，word_index 必须在 0 到 9 之间","data":null} [422]
6  下标为负      : {"code":422,"message":"word_index: Input should be greater than or equal to 0",...} [422]
7  tag 不在词表  : {"code":422,"message":"tag: 取值必须是 滑音/归韵/换气/强音/拖腔/擞音 之一","data":null} [422]
8  tolerance 101 : {"code":422,"message":"tolerance: Input should be less than or equal to 100",...} [422]
9  tolerance -1  : {"code":422,"message":"tolerance: Input should be greater than or equal to 0",...} [422]
10 缺 tag        : {"code":422,"message":"tag: 必填","data":null} [422]
11 空 body       : {"code":422,"message":"segment_id: 必填; word_index: 必填; tag: 必填",...} [422]
12 无 Content-Type: {"code":422,"message":"segment_id: 必填; word_index: 必填; tag: 必填",...} [422]
13 非法body+404段: {"code":422,"message":"word_index: 必填; tag: 取值必须是 滑音/归韵/换气/强音/拖腔/擞音 之一","data":null} [422]
```

三个必须盯住的点：

- **第 2 行是 403 不是 200**——`@teacher_required` 漏了或顺序错了就会当场暴露
- **第 5 行是 `10 个字` 不是 `12 个字`**——上界按唱段算
- **第 12 行是 422 不是 415**；**第 13 行是 422 不是 404**（参数校验先于资源存在性）

第 6/8/9 行是 pydantic 内置约束的中文映射表里没有的 type，**回的是英文**（`_MSG_CN` 只映射 `missing` / `string_too_short` / `string_too_long` / `int_parsing`）。这是既有行为，不是本轮引入的——**不要去改 `_MSG_CN`**，那是另一个话题。

- [ ] **Step 6: 确认上面 13 条一条都没写库**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
docker exec docker_postgres psql -U xiyun -d xiyun -At -c "SELECT count(*) FROM annotations;"
```

预期输出 `0`。

- [ ] **Step 7: 验证——成功路径、重复 409、边界值**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
U=http://127.0.0.1:8877/api/annotations
J='Content-Type: application/json'
C() { curl -s -b /tmp/t.jar -H "$J" -X POST -d "$1" -w ' [%{http_code}]\n' $U; }

echo "A 首次成功      :"; C '{"segment_id":119,"word_index":0,"tag":"拖腔","tolerance":30}'
echo "B 原样重发      :"; C '{"segment_id":119,"word_index":0,"tag":"拖腔","tolerance":30}'
echo "C 缺 tolerance  :"; C '{"segment_id":119,"word_index":5,"tag":"滑音"}'
echo "D tolerance=0   :"; C '{"segment_id":119,"word_index":2,"tag":"换气","tolerance":0}'
echo "E tolerance=100 :"; C '{"segment_id":119,"word_index":2,"tag":"强音","tolerance":100}'
echo "F 同字换 tag    :"; C '{"segment_id":119,"word_index":0,"tag":"滑音","tolerance":40}'
echo "G 另一唱段      :"; C '{"segment_id":110,"word_index":9,"tag":"擞音","tolerance":60}'
```

预期：

- **A**：`[200]`，`data` **恰好 5 个键** `id / word_index / tag / tolerance / created_at`，**没有** `teacher_id` / `segment_id` / `char` / `category` / `note`
- **B**：`[409]` +「该字已标注此技法」
- **C**：`[200]`，`"tolerance":null`（**不是 0**）
- **D / E**：`[200]`（DDL 的 CHECK 是闭区间，两端都收）
- **F**：`[200]`——同一个字挂不同 tag 合法，唯一约束是三列的
- **G**：`[200]`——下标 9 在 seg 110（10 个字）合法

- [ ] **Step 8: 核对库里这 6 行的实际内容**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
docker exec docker_postgres psql -U xiyun -d xiyun -c "
SELECT id, segment_id, word_index, tag, tolerance, teacher_id, created_at
FROM annotations ORDER BY segment_id, word_index, id;"
docker exec docker_postgres psql -U xiyun -d xiyun -At -c "SELECT count(*) FROM annotations;"
```

预期：**6 行**（A/C/D/E/F 在 seg 119，G 在 seg 110；B 被 409 拒了没进库）。

逐项核对：

- **`teacher_id` 全部是 `2`**——从会话取的那个值真落库了
- **`created_at` 全部非空**，且是**北京时间**（`2026-09-29 1x:xx:xx` 这种当前时刻，**不是** UTC 减 8 小时）
- seg 119 的行按 `word_index` 排：`0(拖腔) 0(滑音) 2(换气) 2(强音) 5(滑音)`；两条 `word_index=0` 的按 id 升序
- C 那条的 `tolerance` 是**空**（NULL），不是 0

- [ ] **Step 9: 清理并确认表回到 0 行**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
docker exec docker_postgres psql -U xiyun -d xiyun -c "DELETE FROM annotations WHERE segment_id IN (110, 119);"
docker exec docker_postgres psql -U xiyun -d xiyun -At -c "SELECT count(*) FROM annotations;"
```

预期最后一行 `0`。

> 这里**可以**按 `segment_id` 一把删：表和脚本都已知 0 行起步，这 6 行全是本轮造的。**将来库里一旦有真数据，这条就必须改成按 id 删。**

- [ ] **Step 10: Commit**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add app/api/demos_segments_annotations.py
git commit -m "feat: 实现新增标注接口 C5 POST /api/annotations"
```

---

## Task 4: 前端——「添加标注」接真写入

**Files:**
- Modify: `annotation.html`（第 554、619-636、691-696、745-759、893-915、956-998 行附近）

**Interfaces:**
- Consumes: Task 3 的 `POST /api/annotations`
- Produces:
  - `saveAnnotation()` 改为 async 真写入
  - 模块级 `annLoaded` / `TOAST_ICON`
  - `clearTagSelection()`

- [ ] **Step 1: 改第 554 行的注释**

当前：

```js
// 当前唱段的标注（C4 出参，已映射成内部形状：word_index→index，见 fetchAnnotations）
let annotations = [];
```

改成：

```js
// 当前唱段的标注。两个来源：C4 列表（fetchAnnotations）与 C5 写入的返回值
// （saveAnnotation）——两处都映射成同一套内部形状：word_index→index
let annotations = [];
let annLoaded = false;   // 本地 annotations 是否是一份完整列表，见 saveAnnotation
```

- [ ] **Step 2: 抽 `clearTagSelection()` 并让 `selectChar` 用它**

`selectChar`（第 619-636 行）结尾当前是：

```js
  const ctrl = document.getElementById("annotateControls");
  ctrl.style.opacity = "1"; ctrl.style.pointerEvents = "all";
  selectedTag = null;
  document.querySelectorAll(".type-btn").forEach(b => b.classList.remove("active"));
  document.getElementById("depsPanel").classList.remove("show");
}
```

改成：

```js
  const ctrl = document.getElementById("annotateControls");
  ctrl.style.opacity = "1"; ctrl.style.pointerEvents = "all";
  clearTagSelection();
}

function clearTagSelection() {
  // selectChar() 与 saveAnnotation() 成功后共用这三行。deps 面板是跟着 tag 走的，
  // tag 清空了面板还开着就是自相矛盾
  selectedTag = null;
  document.querySelectorAll(".type-btn").forEach(b => b.classList.remove("active"));
  document.getElementById("depsPanel").classList.remove("show");
}
```

- [ ] **Step 3: 加 `TOAST_ICON` 并改 `showToast` 取图标**

在 `showToast`（第 745 行）**上方**插入：

```js
// toast 图标按类型查表。原来是「只判 success、其余一律 ℹ️」，新增的 error
// 会配上表示「提示」的图标——那是在说反话。表里没有的（如 info）仍回退 ℹ️
const TOAST_ICON = { success: "✅", error: "⚠️" };
```

`showToast` 里那一行：

```js
    <div class="toast-icon">${type === "success" ? "✅" : "ℹ️"}</div>
```

改成：

```js
    <div class="toast-icon">${TOAST_ICON[type] || "ℹ️"}</div>
```

`.toast.error` 没有专用配色规则，会落到 `.toast` 基础外观——与 C4 对 `.toast.info` 的处置一致，**不新增 CSS**。

- [ ] **Step 4: 改 `saveAnnotation`**

当前（第 691-696 行）整段替换成：

```js
async function saveAnnotation() {
  if (selectedIndex < 0 || !selectedTag) { alert("请先选择一个字和标注类型"); return; }
  const seg = segments[currentSegIdx];
  if (!seg) return;
  const btn = document.getElementById("saveAnnotate");
  // 防连点：第二次请求必然撞 409，而那个报错是用户自己点出来的
  if (btn.disabled) return;
  btn.disabled = true;
  btn.textContent = "添加中…";

  let row;
  try {
    const r = await fetch('/api/annotations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // 同源相对路径 + same-origin：写成跨源地址时 fetch 默认不带 Cookie，
      // 后端 login_required 只会看到空 session 并回 401（同 C1–C4 的坑）
      credentials: 'same-origin',
      body: JSON.stringify({
        segment_id: seg.id,
        word_index: selectedIndex,
        tag: selectedTag.tag,
        tolerance: Number(document.getElementById("toleranceSlider").value),
      }),
    });
    const body = await r.json();
    if (!r.ok || body.code !== 0) throw new Error(body.message || String(r.status));
    row = body.data;
  } catch (e) {
    // 只弹 toast、不改本地状态：annotations 只装服务端确认过的行
    showToast("error", "添加失败", e.message);
    return;
  } finally {
    btn.disabled = false;
    btn.textContent = "添加标注";
  }

  // 写已经成功，toast 照发。文案用返回值拼，不去列表里找——下面的降级分支
  // 可能没把它插进列表（annNote 内部会读 ann.index，传 undefined 会当场抛）
  showToast("success", "已添加标注", annNote({ index: row.word_index, tag: row.tag }));
  clearTagSelection();

  // 期间切走了唱段的话，这一行属于旧唱段，不能插进新唱段的列表；也不该再为
  // 旧唱段发一次 GET——fetchAnnotations 会领新号，把当前唱段的结果顶掉
  if (segments[currentSegIdx] !== seg) return;

  if (!annLoaded) {
    // 本地列表本来就不完整（上一次 GET 失败过），插进去会让页面显得「这个
    // 唱段只有刚写的这一条」——让服务端给权威结果
    await fetchAnnotations(seg.id);
    return;
  }

  // 本地插入而不是重新拉列表：写完已经成功了，若紧接着的 GET 失败，页面会显示
  // 「标注加载失败」——那是在说一件没发生的事。
  // 排序按 (index, id)，与 C4 的 ORDER BY word_index, id 一致，否则新条目会跳到最后
  annotations.push({
    id: row.id, index: row.word_index, tag: row.tag,
    tolerance: row.tolerance, createdAt: row.created_at,
  });
  annotations.sort((a, b) => (a.index - b.index) || (a.id - b.id));
  annEmptyMsg = "暂无标注规则";
  annEmptyIcon = "📝";
  renderAnnotations();
  renderLyrics();          // 歌词格子上的 ✓ 由 renderLyrics 画，必须重画
}
```

**`selectedIndex` 不清空**：`UNIQUE(segment_id, word_index, tag)` 是三列的，同一个字挂多个 tag 合法，保留选中字就能接着标下一个技法。清掉的只有 tag（见 `clearTagSelection()`）。

`annEmptyMsg` / `annEmptyIcon` 是 `let`（第 961-962 行），在 `saveAnnotation` 里赋值没问题——`saveAnnotation` 只在用户点击时执行，远晚于顶层 `let` 的初始化。

- [ ] **Step 5: `annLoaded` 的三个赋值点**

1. `switchSegment`（第 893-915 行），在 `annotations = [];` 那一组上方加：

```js
  annLoaded = false;       // 切走的瞬间本地列表就不再是当前唱段的完整列表
```

2. `fetchAnnotations` 的**失败分支**（`renderAnnotations(); return;` 之前）加 `annLoaded = false;`：

```js
    annotations = [];
    annLoaded = false;
    annEmptyMsg = "标注加载失败";
    annEmptyIcon = "⚠️";
    renderAnnotations();
    return;
```

3. `fetchAnnotations` 的**成功分支**（`annEmptyMsg = "暂无标注规则";` 之前）加 `annLoaded = true;`：

```js
  annLoaded = true;
  annEmptyMsg = "暂无标注规则";
  annEmptyIcon = "📝";
```

- [ ] **Step 6: 静态检查**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
grep -n "annLoaded\|clearTagSelection\|TOAST_ICON\|function saveAnnotation\|deleteAnnotation" annotation.html
```

预期看到：

- `let annLoaded = false;`（第 556 行附近）+ 4 处赋值（`switchSegment` 1 处、`fetchAnnotations` 2 处、`saveAnnotation` 1 处）
- `clearTagSelection` 的定义 + 2 处调用（`selectChar`、`saveAnnotation`）
- `TOAST_ICON` 的定义 + 1 处使用
- `async function saveAnnotation()`
- `deleteAnnotation` 只剩定义与渲染处那一个调用——**本轮不动它**

再用 node 过一遍语法（页面脚本不参与构建，这是唯一能静态发现括号错的办法）：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
.venv/bin/python - <<'PY'
import re
html = open("annotation.html", encoding="utf-8").read()
blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
open("/tmp/c5-ann.js", "w", encoding="utf-8").write("\n".join(blocks))
print("抽出", len(blocks), "个 script 块")
PY
node --check /tmp/c5-ann.js && echo "语法 OK"
```

`node --check` 只做语法检查、不执行，所以顶层 `document` 未定义不影响它。**若机器上没有 node**，跳过这一步，靠 Step 7 的浏览器实测兜底（语法错会让整个页面白屏，一眼可见）。

- [ ] **Step 7: 用 `/browse` 验证**

**先用 `/browse` 技能登录 `teacher01`**（`http://127.0.0.1:8877/annotation.html`，密码 `xiyun@2026`）——Task 3 Step 4 重启过后端，旧会话已失效。

切到 **demo 16**（《穆桂英挂帅》· 辕门外三声炮，**10 段**）→ 第 10 段（seg 119）。

1. **首次写入**：点第 1 个字（「谁」）→ 选「拖腔」→ 点「添加标注」→
   - 列表**立刻多一条**，「已添加标注规则」变成 `(1条)`
   - 该字格子出现 ✓，hover 的 title 是「谁字拖腔标注」（**不是 `undefined`**）
   - 类型按钮**全部取消高亮**、deps 面板收起，**字仍然选中**（格子的 selected 高亮还在）
   - 弹 ✅「已添加标注」toast
2. **真落库**：**刷新页面** → 那条**仍在**。这是「真写入」的唯一证明
3. **重复 409**：同一个字（「谁」）、**同一个类型**（「拖腔」）再点一次 →
   - 列表**条数不变**（仍 `(1条)`）
   - 弹 ⚠️「添加失败 / 该字已标注此技法」
   - 类型按钮**仍保持高亮**、字仍选中——`clearTagSelection()` 在 `catch` 的 `return` 之后，失败路径根本走不到它
4. **同字换 tag**：同一个字、**换一个类型**（「滑音」）→ 成功，列表 `(2条)`，同一个字两行
5. **连点**：选另一个字 + 一个类型，**快速连点「添加标注」5 次** → 打开 Network 面板确认只发出**一次** `POST /api/annotations`；按钮期间文案是「添加中…」、灰掉
6. **边界值**：把容忍度滑块拉到 `0` 再添加 → 成功，列表那行显示 `±0c`（**不是空白**）
7. **失败不改本地状态**：临时把 `fetch('/api/annotations'` 改成 `fetch('/api/annotations-x'` → 选字 + 选类型 → 添加 → 弹 ⚠️「添加失败 / 接口不存在」、**列表条数不变** → **验证完改回，并确认文件里无残留**
8. **降级后写入（验 `annLoaded` 分支）**：上一步那个坏 URL 会让列表停在「标注加载失败」；**改回后不刷新页面**，直接添加一条 → 列表显示的是**服务端返回的完整列表**（含此前已有的全部标注），不是只有新写的那一条
9. **切唱段不串**：写成功之后立刻快速连点第 9 段和第 10 段 → 最终列表属于**后点**的那个唱段，没有混进另一段的条目

- [ ] **Step 8: 清理本次浏览产生的行并确认表回到 0 行**

浏览验证会真的写库。按 **segment_id 一把删是安全的**（表和脚本都已知 0 行起步），但仍推荐按 id 核对一遍再删：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
docker exec docker_postgres psql -U xiyun -d xiyun -c "SELECT id, segment_id, word_index, tag FROM annotations ORDER BY id;"
docker exec docker_postgres psql -U xiyun -d xiyun -c "DELETE FROM annotations;"
docker exec docker_postgres psql -U xiyun -d xiyun -At -c "SELECT count(*) FROM annotations;"
```

预期最后一行 `0`。

> 上面的 `DELETE FROM annotations;` **只在确认第一条 SELECT 出来的行全部是本次浏览造的前提下执行**。看到不认识的 `segment_id`，就停下来按 id 删。

- [ ] **Step 9: Commit**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add annotation.html
git commit -m "feat: 标注页「添加标注」接上 POST /api/annotations"
```

---

## Task 5: 文档登记与收尾

**Files:**
- Modify: `DOC_ISSUES.md`（在 `## 待核实` 之前插入第 30 条）

**Interfaces:**
- Consumes: Task 1–4 的全部结论
- Produces: 无代码接口

- [ ] **Step 1: 写 `DOC_ISSUES.md` 第 30 条**

在 `## 待核实` 之前插入：

````markdown
## 30. 新增标注（C5）只有一句话描述，请求与响应契约全未定义

**涉及**：《5-接口清单》2.3 节 C5 / `app/api/demos_segments_annotations.py` / `app/services/library_service.py` / `app/schemas/demo.py` / `annotation.html`

### 30.1 C5 的请求与响应契约全未定义

C5 在文档里的**全部**内容是「`POST /api/annotations` ｜ 教师 ｜ 新增标注（`segment_id`, `word_index`, `tag`, `tolerance`）」一行。与第 26（C1）、27（C2/C3）、28（C4）条同源。括号里那四个字段名是**唯一的入参依据**——请求体形态（JSON body？form？）、字段类型、必填性、取值范围、响应体、错误码一概没有。本次采用的口径：

| 未定义项 | 本次采用的口径 |
|---|---|
| 请求体形态 | JSON body，`Content-Type: application/json` |
| `segment_id` | int，必填；不存在回 `404`（显式查 `segments`） |
| `word_index` | int，必填，`>= 0` 且 `<` 该唱段**归一后**的歌词长度；越界回 `422` |
| `tag` | str，必填，限定六个值：滑音 / 归韵 / 换气 / 强音 / 拖腔 / 擞音；词表外回 `422` |
| `tolerance` | int 或 `null`，**可选**（缺省 `null`）；`0–100` 闭区间，越界回 `422` |
| `teacher_id` | **不进参**，从会话取。让客户端指定归属等于开一个「以别人的名义标注」的越权入口 |
| 响应体 | **新建的那一行**，形状与 C4 列表行完全相同（复用 `AnnotationOut`）：`id` / `word_index` / `tag` / `tolerance` / `created_at` |
| 成功状态码 | `200`，**不是 `201`**。`ok()` 固定回 200，既有 POST（`auth/login` 等）也全走 200；为一个接口单独引入 201 会让「code 与 HTTP 状态码一致」（第 9 条）多一个例外 |
| 重复标注 | `409` +「该字已标注此技法」。表上有 `UNIQUE(segment_id, word_index, tag)`，重复必然撞约束，不是一个理论分支 |
| 校验顺序 | pydantic（API 层）先于 service 的 404 判定。所以「`segment_id` 不存在 **且** `tag` 非法」回 `422` 而不是 `404`——参数合法性优先于资源存在性 |

**为什么 `tag` 限定词表、而 C4 出参不校验取值**：写入端把关、读取端宽容是标准做法，两者针对的方向不同。C4 出参不校验是为了让**历史脏数据**可读（第 28 条）；C5 入参限定是为了**不再生产**脏数据——将来按 tag 派发评测规则时，词表外的值无法处理。同理，`word_index` 越界在 C4 出参里保留显示（首列落成 `?`）是为了让已有脏数据可见，在 C5 里挡住是为了不再生产。

**「标错了撤不掉」**：C6（`DELETE /api/annotations/<id>`）未实现，标错 tag 只能等 C6。这是 C6 的事，但页面上已经把这条限制说明白了。

**数据现状**：`annotations` 表实测 0 行，`seed.sql` 里也没有标注的 INSERT。本轮全部验证都是接口自己写进去、验完删掉的。

**待文档方确认**：

1. 四个入参的类型与必填性是否与预期一致？`tolerance` 允许缺省是否可行，还是应当必填？
2. `tag` 的合法取值是否就是这六个？文档正文（功能 9.6 / 9.7）里有没有别的技法词？
3. 重复标注回 `409` 是否符合预期？还是希望「已存在就更新 `tolerance`」（幂等覆盖）？**后者需要文档方明确**——它会改变接口语义，且 tag 仍然改不了（换 tag 是新行）。
4. C5 是否需要一个「更新已有标注」的接口？当前设计下改 `tag` 必须靠 C6 删了重标，而 C6 尚未实现。
5. 响应体是否需要 `201 Created`？（本项目统一 200，改动会影响既有约定。）
````

- [ ] **Step 2: 跑建库一致性闸门**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python scripts/check_db.py
```

预期：**无新增差异**（本轮不改模型与 `schema.sql`）。脚本会报既有的 `demo_versions` + `teacher_demos` 三列漂移——那是本轮之前就有的。**若报出 `annotations` 相关的差异，停下来查。**

- [ ] **Step 3: 终检——表回到 0 行**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
docker exec docker_postgres psql -U xiyun -d xiyun -At -c "SELECT count(*) FROM annotations;"
```

预期输出 `0`。**不是 0 就说明前面某个任务没清理干净。**

- [ ] **Step 4: 终检——没有残留的「C5 未实现」**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
grep -n "C5（POST\|C5 未实现\|写入接口未实现" annotation.html
```

预期：**无输出**。有输出说明 Task 4 没把那段占位注释清干净。

再确认 C6 的提示**仍在**（本轮不该动它）：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
grep -n "删除接口未实现" annotation.html
```

预期：**1 行**，在 `deleteAnnotation` 里。

- [ ] **Step 5: 终检——C6 / C7 两个占位路由仍是原样**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
grep -n "def del_annotations" -A 4 app/api/demos_segments_annotations.py
grep -n "def annotations_rules" -A 5 app/api/demos_segments_annotations.py
```

预期：`del_annotations` 体内仍是 `return ok(id)`、`annotations_rules` 体内仍是 `return ok({"tag":tag,"word":word})` 的占位形态，**没有被本轮改动**。

- [ ] **Step 6: Commit**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add DOC_ISSUES.md
git commit -m "docs: 登记 C5 请求与响应契约未定义"
```

---

## 收尾

C5 落地后，`annotation.html` 的曲目 → 唱段 → 歌词 → 标注 → **写入**这条链是通的：老师标的东西真落库、刷新仍在。

**仍不做**：

- **C6（`DELETE /api/annotations/<id>`）与 C7（`GET /api/annotations/rules`）**——两个占位路由原样保留，页面上的 ✕ 仍然只弹「删除接口未实现」
- **改已有标注**——`tolerance` 改不了、`tag` 改不了，都得等 C6 删了重标
- **`TECHNIQUE_DEPS` / `RULE_IMPACT` / `renderDeps()`** 仍是 mock——「技法依赖图谱」面板与本轮无关

**两个值得记着的约束**：

1. **`create_annotation` 里 `except IntegrityError` 的假设**（`library_service.py`）：把 `IntegrityError` 一律解释为「唯一约束冲突」，是因为其余约束都已在前面挡下。**将来给 `annotations` 加新约束（或改列宽）时，必须回头重看这个 except**，否则新约束的报错会被错报成「该字已标注此技法」。
2. **`ANNOTATION_TAGS` 是三处同源**：`app/schemas/demo.py` 的元组、`annotation.html` 六个按钮的 `data-tag`、`app/models/annotation.py` 的类注释。加/改技法要**三处一起改**，漏了后端会 422 拒绝页面上真实存在的按钮。
