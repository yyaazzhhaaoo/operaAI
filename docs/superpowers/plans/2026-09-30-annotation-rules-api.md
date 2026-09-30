# 标注规则列表管理接口（C7 `GET /api/annotations/rules`）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 C7——跨唱段的全库标注列表，可按 `tag` 与 `word` 筛选，每行自带曲目/唱段归属与字，把 `app/api/demos_segments_annotations.py` 里只回显入参的占位换成真实现。

**Architecture:** 自下而上三层（repo 一条 outerjoin SQL → service 算 `char` 并筛 `word` → HTTP 路由），外加一个出参模型。**不碰任何 `.html`**——功能 9.6 在前端没有对应 UI，全项目也没有调用方。

**Tech Stack:** Python 3.11 / Flask / SQLAlchemy 2.x / PostgreSQL / pydantic v2

**依据 spec:** `docs/superpowers/specs/2026-09-30-annotation-rules-api-design.md`

## Global Constraints

- **不新增测试框架。** 本仓库没有 `tests/`、`requirements.txt` 里也没有 pytest。验证一律用**对真接口跑的 curl**、`.venv/bin/python` 脚本与 psql。不要 `pip install pytest`。
- **Python 解释器用 `.venv/bin/python`**，先 `cd /Users/meiyazhao/Documents/lianshu/operaAI`。
- **`/api` 前缀只在 `app/api/__init__.py` 的 `url_prefix` 里写一次**，路由写相对路径。
- **响应一律用 `app/response.py` 的 `ok()`**，回 `200`。
- **权限是教师**：`@login_required` **加** `@teacher_required`，叠放顺序固定、`login_required` 在外层（同 C4/C5/C6）。
- **`char` 必须经 `library_service._normalize_lyrics`**，**不许**直接 `lyrics_json[word_index]`（理由见 Task 1 Step 3 的注释）。
- **`tag` 筛选下推到 SQL**，**`word` 筛选在 service 的 Python 循环里**。不要为了「对称」把 `word` 也塞进 SQL——它依赖归一后的字，SQL 层拿不到。
- **`tag` 入参不校验词表**：`?tag=随便` 回 `200` + `[]`，**不是 422**。不要引入 `ANNOTATION_TAGS` 校验。
- **本接口没有 404、没有 422**：无路径参数、不读 body、不校验入参取值。不要给 `annotation_rules` 加 `BusinessError`。
- **`outerjoin` 而非 `join`**：`annotations.segment_id` 与 `segments.demo_id` 在 DDL 上均可空，内连接会把脏行整条丢掉。
- **不改 `schema.sql` / `app/models/*` / `app-d.py` / 任何 `.html`**，不引 Alembic，不加依赖。
- **只做 C7。** C1–C6 的代码与路由一个字都不要动，尤其是 `del_annotations` 那条 `DELETE /api/annotations/<int:annotation_id>`。
- **数据库时区是 `Asia/Shanghai`**（不是 UTC）。`created_at` **原样返回，不做 `AT TIME ZONE` 换算**。
- **后端是 `debug=True` 跑的，Werkzeug reloader 会自动重载**。改完 `.py` 不用手工重启，但**要 curl 一次确认改动真生效了**（reloader 在语法错时会留在旧代码上继续服务，症状是「改了没反应」）。

### 当前真库基线（2026-09-30 实测）

- **`annotations` 表有 3 行真数据**，全部挂在 **seg 110**、`teacher_id` 都是 **2**（`teacher01`）：

  | id | word_index | tag | tolerance |
  |---|---|---|---|
  | 109 | 3 | 归韵 | 30 |
  | 110 | 7 | 拖腔 | 30 |
  | 111 | 9 | 强音 | 37 |

- **seg 110** 属 **demo 16**、`seq = 1`、`title` = 「**辕门外三声炮如同雷震**」、歌词 **10 字**（下标 0–9）：
  `0辕 1门 2外 3三 4声 5炮 6如 7同 8雷 9震`
  → 三条标注对应的字就是 **3→三、7→同、9→震**
- `teacher_demos` 共 6 条：`1贵妃醉酒·选段 / 15 01_xipi_1931 / 16《穆桂英挂帅》· 辕门外三声炮 / 17《贵妃醉酒》· 海岛冰轮初转腾 / 18《霸王别姬》· 看大王在帐中 / 19《红娘》· 叫张生隐藏在棋盘之下`
  **`demo.title` 带书名号与分隔点**——断言要按真值写，不是「穆桂英挂帅」
- **seg 1** 属 **demo 1**（「贵妃醉酒·选段」）、`seq=1`、`title`=「第一段」
- `users.id`：`teacher01` = **2**，`stu001` = **3**
- 种子账号 `teacher01` / `stu001`，密码 `xiyun@2026`
- 登录：`POST /api/auth/login`，body `{"username":"...","password":"..."}`

### 验证数据的清理纪律（**与 C6 那轮相反，务必看清**）

C6 那轮 `annotations` 是 **0 行**，所以它的计划最后写了 `DELETE FROM annotations;`。**本轮绝对不行**——表里有 3 行真数据，一把清会全部删掉且无法恢复。

- 造临时行**只能用 `RETURNING id` 或 ORM `flush()` 抓住自增 id**
- 清理**只按 id 删**，**绝不** `DELETE FROM annotations WHERE segment_id = ...`，**绝不** `DELETE FROM annotations;`
- 每个任务的最后一步都是 `SELECT count(*) FROM annotations;` 回 **3**。**不是 3 就停下来查，不要继续下一个任务**
- 动手删任何一行之前，先 `SELECT id,segment_id,word_index,tag FROM annotations ORDER BY id;` 肉眼确认列出来的**每一行都是本次造的**（`teacher_id` 为 NULL 或 2、`created_at` 是今天的当前时间）

---

## Task 1: 仓储层与服务层——全库查询、字的下标解析与 `word` 筛选

**Files:**
- Modify: `app/repositories/annotations_repo.py`（顶部 import 加两个名字；末尾追加 1 个函数，现有 6 个函数不动）
- Modify: `app/services/library_service.py`（追加 2 个函数，现有函数不动）

**Interfaces:**
- Consumes: `app.models.Annotation`、`app.models.TeacherDemo`、`app.models.demo.Segment`、`library_service._normalize_lyrics`（已有，`:149`）
- Produces:
  - `annotations_repo.list_rules(db: Session, tag: str | None) -> list[tuple[Annotation, Segment | None, TeacherDemo | None]]`
  - `library_service.annotation_rules(db: Session, *, tag: str | None, word: str | None) -> list[dict]`

- [ ] **Step 1: 写验证脚本 `/tmp/c7-service.py`**

先写测试、后写实现。脚本全程用 `session_scope()`（脚本侧的会话，进出都管事务；与 Flask 请求内的 `get_db()` 契约不同，不可互换）。

```python
# C7 service 层验证：真数据 3 行打底 + 临时行验脏数据分支 + 按 id 清理。
import sys
sys.path.insert(0, "/Users/meiyazhao/Documents/lianshu/operaAI")

from sqlalchemy import delete as sa_delete, func, select

from app.db import session_scope
from app.models import Annotation
from app.services import library_service

SEG = 110          # 10 个字，真数据全挂在这里
REAL_IDS = {109, 110, 111}
tmp_ids = []


def rules(**kw):
    with session_scope() as s:
        return library_service.annotation_rules(s, **kw)


def count():
    with session_scope() as s:
        return s.scalar(select(func.count(Annotation.id)))


def real_ids():
    with session_scope() as s:
        return set(s.scalars(select(Annotation.id)).all())


# 基线：真数据必须是 3 行，且就是 109/110/111
n0 = count()
assert n0 == 3, f"基线不是 3 行，实际 {n0}——先核对真数据再跑"
assert real_ids() == REAL_IDS, f"真数据 id 不是 109/110/111，实际 {sorted(real_ids())}"
print(f"[基线] annotations {n0} 行 OK（109/110/111）")

# ① 不带筛选：3 条，按 word_index 升序 3/7/9
rows = rules(tag=None, word=None)
assert len(rows) == 3, f"应 3 条，实际 {len(rows)}"
assert [r["word_index"] for r in rows] == [3, 7, 9], [r["word_index"] for r in rows]
assert [r["id"] for r in rows] == [109, 110, 111], [r["id"] for r in rows]
print("[1] 不带筛选 3 条、按 word_index 升序 3/7/9 OK")

# ② char 由 _normalize_lyrics 算出：3→三 7→同 9→震
assert [r["char"] for r in rows] == ["三", "同", "震"], [r["char"] for r in rows]
print("[2] char = 三/同/震 OK")

# ③ 归属字段（注意 demo.title 带书名号与分隔点）
r = rows[0]
assert r["segment_id"] == SEG, r["segment_id"]
assert r["segment_title"] == "辕门外三声炮如同雷震", r["segment_title"]
assert r["demo_id"] == 16, r["demo_id"]
assert r["demo_title"] == "《穆桂英挂帅》· 辕门外三声炮", r["demo_title"]
print("[3] 归属字段（demo_id=16 / 唱段标题 / 曲目标题带书名号）OK")

# ④ 每行恰好 10 个键，且不含 teacher_id / seq / lyrics_json
assert len(r) == 10, sorted(r)
for banned in ("teacher_id", "seq", "lyrics_json", "segment"):
    assert banned not in r, f"不该出现 {banned}"
print("[4] 恰好 10 个键、无 teacher_id/seq/lyrics_json OK")

# ⑤ tag 筛选
assert len(rules(tag="拖腔", word=None)) == 1
assert rules(tag="拖腔", word=None)[0]["id"] == 110
assert rules(tag="滑音", word=None) == []
print("[5] tag=拖腔 -> 1 条；tag=滑音 -> [] OK")

# ⑥ word 筛选：筛的是**标注**不是歌词（「炮」在歌词里但没人标注）
assert [x["id"] for x in rules(tag=None, word="三")] == [109]
assert [x["id"] for x in rules(tag=None, word="同")] == [110]
assert rules(tag=None, word="炮") == [], "「炮」是歌词里的字但没标注，应为空"
# 注意这是**直调 service**：service 的契约是「word 为 None 才不筛」，
# 空串在这里是**字面匹配**（匹配不到任何字，因为 char 不会是空串）。
# api 层另有 `request.args.get("word") or None`，会把 ?word= 收敛成 None
# → 那一层 ?word= 是「不筛」（见 Task 2 的验证矩阵第 7 条）。两层行为不同是有意的
assert rules(tag=None, word="") == [], "service 层空串是字面匹配，应回空"
print("[6] word=三/同 命中；word=炮 空（筛标注不筛歌词）OK")

# ⑦ 两个条件是与关系
assert len(rules(tag="拖腔", word="同")) == 1
assert rules(tag="拖腔", word="三") == []
print("[7] tag 与 word 是与关系 OK")

# ⑧ 词表外的 tag 回空列表，不抛异常
assert rules(tag="随便", word=None) == []
print("[8] tag=随便（词表外）-> [] 不抛异常 OK")

# ⑨ 临时行：seg 1（属 demo 1）验跨唱段排序 —— demo 1 应排在最前
with session_scope() as s:
    a = Annotation(segment_id=1, word_index=0, tag="滑音", tolerance=20, teacher_id=2)
    s.add(a)
    s.flush()
    tmp_ids.append(a.id)
    id_seg1 = a.id
rows = rules(tag=None, word=None)
assert len(rows) == 4, f"应 4 条，实际 {len(rows)}"
assert rows[0]["id"] == id_seg1, "demo 1 的行没排在最前——排序第一关键字不是 demo_id"
assert rows[0]["demo_id"] == 1 and rows[1]["demo_id"] == 16
print(f"[9] 跨唱段排序：demo 1 的行（id={id_seg1}）在最前 OK")

# ⑩ 临时行：word_index 越界 -> char 为 None，**行保留**
with session_scope() as s:
    b = Annotation(segment_id=SEG, word_index=99, tag="换气", tolerance=10, teacher_id=2)
    s.add(b)
    s.flush()
    tmp_ids.append(b.id)
    id_oob = b.id
rows = rules(tag=None, word=None)
assert len(rows) == 5, f"越界行被丢掉了，应 5 条实际 {len(rows)}"
oob = [r for r in rows if r["id"] == id_oob]
assert len(oob) == 1, "越界行不在结果里"
assert oob[0]["char"] is None, f"越界行的 char 应为 None，实际 {oob[0]['char']!r}"
assert oob[0]["tag"] == "换气" and oob[0]["segment_id"] == SEG
print(f"[10] 越界行（id={id_oob}）保留且 char=None OK")

# ⑪ 临时行：segment_id 为 NULL -> char 与四个归属字段全 None，且排最后
# tag 特意用「擞音」：六个词表值里只有它没有被真数据或上面的临时行占用
# （真数据是 归韵/拖腔/强音，⑨ 用了 滑音，⑩ 用了 换气）。
# 若这里也用「强音」，下面 ⑫ 的 tag 筛选会同时命中真数据 id=111，断言当场误报
with session_scope() as s:
    c = Annotation(segment_id=None, word_index=0, tag="擞音", tolerance=50)
    s.add(c)
    s.flush()
    tmp_ids.append(c.id)
    id_orphan = c.id
rows = rules(tag=None, word=None)
assert len(rows) == 6, f"应 6 条，实际 {len(rows)}"
orphan = [r for r in rows if r["id"] == id_orphan]
assert len(orphan) == 1, "segment_id 为 NULL 的行被 outerjoin 丢掉了"
assert orphan[0]["char"] is None
for k in ("segment_id", "segment_title", "demo_id", "demo_title"):
    assert orphan[0][k] is None, f"{k} 应为 None，实际 {orphan[0][k]!r}"
assert rows[-1]["id"] == id_orphan, "demo_id 为 NULL 的行没排在最后"
print(f"[11] 孤儿行（id={id_orphan}）保留、归属全 None、排最后 OK")

# ⑫ 孤儿行也能被 tag 筛到（「擞音」全库只有这一条）
assert [x["id"] for x in rules(tag="擞音", word=None)] == [id_orphan]
# 反证：真数据里也有「强音」，筛它应当只回 id=111 那一条，不掺进孤儿行
assert [x["id"] for x in rules(tag="强音", word=None)] == [111], \
    [x["id"] for x in rules(tag="强音", word=None)]
print("[12] tag=擞音 只命中孤儿行；tag=强音 只命中真数据 111 OK")

# ⑬ word 筛选对 char 为 None 的行是「不匹配」：两条脏行都不该出现在结果里
got = {x["id"] for x in rules(tag=None, word="辕")}
assert id_oob not in got, "char=None 的越界行被 word 误判命中"
assert id_orphan not in got, "char=None 的孤儿行被 word 误判命中"
assert all(x["char"] is not None for x in rules(tag=None, word="辕"))
print("[13] word 筛选对 char=None 的行不误判 OK")

# 清理：只删本次造的（按 id，绝不按 segment_id、绝不 DELETE FROM annotations）
with session_scope() as s:
    s.execute(sa_delete(Annotation).where(Annotation.id.in_(tmp_ids)))
n1 = count()
assert n1 == 3, f"清理后不是 3 行，实际 {n1}——真数据可能被动过"
assert real_ids() == REAL_IDS, f"真数据被动过了！现在是 {sorted(real_ids())}"
print(f"[清理] annotations 回到 {n1} 行 OK（仍是 109/110/111）")
print("\n全部通过")
```

- [ ] **Step 2: 跑脚本，确认它失败**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
.venv/bin/python /tmp/c7-service.py
```

预期：**`AttributeError: module 'app.services.library_service' has no attribute 'annotation_rules'`**

**若报的是「基线不是 3 行」，先停下来核对真数据，不要继续。**

- [ ] **Step 3: 实现仓储层的 `list_rules`**

`app/repositories/annotations_repo.py` 顶部的 import 现在是：

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Annotation
```

改成（加 `TeacherDemo`，并按 `library_repo.py` 的既有写法取 `Segment`）：

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Annotation, TeacherDemo
from app.models.demo import Segment
```

然后在文件**末尾追加**：

```python
def list_rules(db: Session, tag: str | None) -> list[tuple[Annotation, Segment | None, TeacherDemo | None]]:
    """全库标注 + 各自所属的唱段与曲目，供 C7 `GET /api/annotations/rules`。

    **一条 SQL 查完，不做 N+1**（同 get_demo_list 的取舍）。曲目数是个位数、
    标注数是十位数，joinedload 不必上。

    **outerjoin 而非 join**：annotations.segment_id 与 segments.demo_id 在 DDL
    上都可空，内连接会把这两类行整条丢掉——集中展示少几行且毫无提示，与
    spec 3.4「char 取不到时保留行」的口径直接打架。

    tag 条件**下推到 SQL**（`tag is None` 时不加）：能少捞一批行就少捞一批。
    `word` 筛选不在这里——它依赖归一后的字，SQL 层拿不到，在 service 层做。

    排序 demo_id → segment_id → word_index → id 全升序：先按曲目分组，再按
    唱段、再按字序，末位 id 保证稳定（同一个字可挂多个 tag，UNIQUE 是三列）。
    demo_id 为 NULL 的行在 PG 的 `ORDER BY ... ASC` 下默认排最后（NULLS LAST），
    这是 PG 的既定行为，不必显式 nulls_last()。

    返回三元组而不是往模型上挂临时属性：同 get_demo_list 返回
    (TeacherDemo, 分段数) 的理由——「哪些来自库、哪些是算出来的」要看得出来。
    """
    stmt = (
        select(Annotation, Segment, TeacherDemo)
        .outerjoin(Segment, Annotation.segment_id == Segment.id)
        .outerjoin(TeacherDemo, Segment.demo_id == TeacherDemo.id)
        .order_by(
            Segment.demo_id,
            Annotation.segment_id,
            Annotation.word_index,
            Annotation.id,
        )
    )
    if tag is not None:
        stmt = stmt.where(Annotation.tag == tag)
    return list(db.execute(stmt).all())
```

- [ ] **Step 4: 实现服务层的 `_lyric_at` 与 `annotation_rules`**

在 `app/services/library_service.py` 的 **`segment_detail` 之前**插入 `_lyric_at`（紧挨着它的同类 `_normalize_lyrics`），并在**文件末尾追加** `annotation_rules`。

`_lyric_at`（插在 `_normalize_lyrics` 之后、`segment_detail` 之前）：

```python
def _lyric_at(seg, index: int) -> dict | None:
    """取某个唱段第 index 个字的**归一化**歌词，取不到回 None。供 C7 算 char。

    必须复用 _normalize_lyrics，**不许**直接 seg.lyrics_json[index]：归一函数会
    **丢弃**非法条目（非对象、word 非字符串），直接下标取会拿到错位的字。
    C3 出参、C5 写入校验、C7 的 char 三处必须同源，否则会出现
    「C5 说这个下标合法、C7 却取到别的字」。

    取不到有两种来源，都回 None（调用方据此把 char 置空，**行仍保留**）：
    seg 为 None（标注的 segment_id 为空）、index 越界（歌词在该标注写入后
    被重新解析过——replace_segments 会整批替换）。

    判 0 <= index 而不是只判上界：word_index 在 DDL 上只有 NOT NULL，
    负数下标会从列表尾部取字（Python 语义），那是静默取错值。
    """
    if seg is None:
        return None
    lyrics = _normalize_lyrics(seg.lyrics_json)
    if 0 <= index < len(lyrics):
        return lyrics[index]
    return None
```

`annotation_rules`（追加在 `delete_annotation` 之后）：

```python
def annotation_rules(db: Session, *, tag: str | None, word: str | None) -> list[dict]:
    """C7 全库标注规则列表，可按 tag 与 word 筛选。

    tag / word 为 None 表示不筛（api 层已把缺省与空串一起收敛成 None）。

    **tag 在 SQL 筛、word 在这里筛**：word 筛的是**字**，而字不存在于
    annotations 表里，得先经 _normalize_lyrics 归一 lyrics_json 才算得出来，
    SQL 层拿不到。这个不对称是本质的，不是随手分的。

    **char 取不到时回 None，行保留**（spec 3.4）：集中展示的价值就在于
    「全库有多少条规则」这个数字是对的，悄悄少几行等于谎报。同 C4 spec 5.5
    「越界保留、让脏数据可见」的口径。

    **不抛 BusinessError**：本接口没有路径参数、不读 body，没有 404 场景；
    tag 也不校验词表——筛一个词表外的值是合法查询，空结果是正确回答
    （词表只为写入端把关，见 C5）。

    关键字参数：两个都可空且都是 str，位置调用时极易把 tag 与 word 写反。

    返回 dict 而不是 ORM 对象：同 segment_annotations / demo_list 的风格，
    api 层直接喂 pydantic。

    不按 segment 缓存归一结果：同一唱段的多条标注会重复归一同一份
    lyrics_json，但量级是「一个唱段几条标注、歌词十几字」，重复归一的代价
    远小于多一张缓存表的复杂度。
    """
    rows = []
    for ann, seg, demo in annotations_repo.list_rules(db, tag):
        lyric = _lyric_at(seg, ann.word_index)
        char = lyric["char"] if lyric else None
        if word is not None and char != word:
            continue
        rows.append({
            "id": ann.id,
            "word_index": ann.word_index,
            "char": char,
            "tag": ann.tag,
            "tolerance": ann.tolerance,
            "created_at": ann.created_at,
            "segment_id": ann.segment_id,
            "segment_title": seg.title if seg else None,
            "demo_id": seg.demo_id if seg else None,
            "demo_title": demo.title if demo else None,
        })
    return rows
```

`annotations_repo` 已在文件顶部 import 过（`segment_annotations` 在用），**不需要新增 import**。`_normalize_lyrics` 与 `_lyric_at` 同文件，直接调。

- [ ] **Step 5: 跑脚本，确认通过**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
.venv/bin/python /tmp/c7-service.py
```

预期输出：

```
[基线] annotations 3 行 OK（109/110/111）
[1] 不带筛选 3 条、按 word_index 升序 3/7/9 OK
[2] char = 三/同/震 OK
[3] 归属字段（demo_id=16 / 唱段标题 / 曲目标题带书名号）OK
[4] 恰好 10 个键、无 teacher_id/seq/lyrics_json OK
[5] tag=拖腔 -> 1 条；tag=滑音 -> [] OK
[6] word=三/同 命中；word=炮 空（筛标注不筛歌词）OK
[7] tag 与 word 是与关系 OK
[8] tag=随便（词表外）-> [] 不抛异常 OK
[9] 跨唱段排序：demo 1 的行（id=<N>）在最前 OK
[10] 越界行（id=<N>）保留且 char=None OK
[11] 孤儿行（id=<N>）保留、归属全 None、排最后 OK
[12] tag=擞音 只命中孤儿行；tag=强音 只命中真数据 111 OK
[13] word 筛选对 char=None 的行不误判 OK
[清理] annotations 回到 3 行 OK（仍是 109/110/111）

全部通过
```

- [ ] **Step 6: 确认表回到 3 行**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
docker exec docker_postgres psql -U xiyun -d xiyun -At -c "SELECT count(*) FROM annotations;"
docker exec docker_postgres psql -U xiyun -d xiyun -At -c "SELECT id FROM annotations ORDER BY id;"
```

预期：先输出 `3`，再输出 `109`、`110`、`111` 三行。**不是这个就停下来查。**

- [ ] **Step 7: Commit**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add app/repositories/annotations_repo.py app/services/library_service.py
git commit -m "feat: 新增标注规则列表仓储与业务逻辑（C7 数据层 + service）"
```

---

## Task 2: 出参模型与接口层——`GET /api/annotations/rules`

**Files:**
- Modify: `app/schemas/demo.py`（在 `AnnotationOut` 之后插入 `AnnotationRuleOut`）
- Modify: `app/api/demos_segments_annotations.py:147-153`（替换 C7 占位路由）

**Interfaces:**
- Consumes: `library_service.annotation_rules(db, *, tag, word) -> list[dict]`（Task 1）
- Produces: HTTP `GET /api/annotations/rules?tag=&word=` → `200` + `{"code":0,"message":"ok","data":[AnnotationRuleOut, ...]}`

- [ ] **Step 1: 先确认占位路由现在是什么样（这就是「测试失败」的证据）**

后端已在 8877 跑着。先登录教师拿 cookie，再打现在的 C7：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
U=http://127.0.0.1:8877
J='Content-Type: application/json'
curl -s -c /tmp/c7-t.jar -H "$J" -X POST \
  -d '{"username":"teacher01","password":"xiyun@2026"}' $U/api/auth/login >/dev/null
echo -n "GET /api/annotations/rules → "
curl -s -b /tmp/c7-t.jar "$U/api/annotations/rules?tag=拖腔&word=同" -w ' [%{http_code}]\n'
```

预期：`{"code":0,"message":"ok","data":{"tag":"拖腔","word":"同"}} [200]`

**`data` 是入参的回显对象**，既没查库也不是数组。这就是未实现的证据。

- [ ] **Step 2: 新增出参模型 `AnnotationRuleOut`**

在 `app/schemas/demo.py` 的 **`AnnotationOut` 之后**（文件末尾，紧跟 `ANNOTATION_TAGS` 之前）插入：

```python
class AnnotationRuleOut(BaseModel):
    """全库标注行。C7 `GET /api/annotations/rules` 的列表元素。

    它是 `AnnotationOut` 的**超集**（多 `char` 与四个归属字段），**不是替换
    关系**——C4 / C5 仍用 `AnnotationOut`。两者的差别是场景：C4 面向**单个
    唱段**，调用方那一刻已经加载了该唱段的 lyrics，所以 char 由前端取，
    不必后端算，也不必给归属；C7 面向**全库**，前端没有别的唱段的 lyrics，
    char 只能后端算，而没有归属这张表就读不出「这条规则属于哪个曲目」。

    **char 可空**，三种来源：annotations.segment_id 为 NULL、
    segments.lyrics_json 为 NULL、word_index 越界（歌词被重新解析过）。
    三种情况下**行都保留**、char 回 null，不剔除——集中展示的价值就在于
    「全库有多少条规则」这个数字是对的（spec 3.4）。

    **四个归属字段全可空**：理由同 AnnotationOut 的 tolerance / created_at
    ——segments.demo_id 与 segments.title 在 DDL 上可空，库里只要有一行空值，
    写成非空就整片 500。

    **不出 teacher_id**：同 AnnotationOut，C7 也不按教师隔离，返回只会让人
    误以为有归属过滤。**不出 seq**：唱段标题的信息量大于「第 N 段」，
    且后加字段不是破坏性变更。**不出 lyrics_json**：那是 JSONB 列的内部
    表示，形状还有三种互不兼容的版本（DOC_ISSUES 第 27 条）。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    word_index: int
    char: str | None = None
    tag: str
    tolerance: int | None = None
    created_at: datetime | None = None
    segment_id: int | None = None
    segment_title: str | None = None
    demo_id: int | None = None
    demo_title: str | None = None
```

`BaseModel` / `ConfigDict` / `datetime` 都已在文件顶部 import 过，**不需要新增 import**。

- [ ] **Step 3: 替换 C7 路由**

`app/api/demos_segments_annotations.py` 顶部的 import 块：

```python
from app.schemas.demo import (
    AnnotationIn,
    AnnotationOut,
    DemoListOut,
    DemoSegmentOut,
    SegmentDetailOut,
)
```

加一个名字，变成：

```python
from app.schemas.demo import (
    AnnotationIn,
    AnnotationOut,
    AnnotationRuleOut,
    DemoListOut,
    DemoSegmentOut,
    SegmentDetailOut,
)
```

再把第 147–153 行：

```python
@api_bp.route("/annotations/rules",methods=["GET"])
@login_required
@teacher_required
def annotations_rules():
    tag = request.args.get("tag")
    word = request.args.get("word")
    return ok({"tag":tag,"word":word})
```

整段替换为：

```python
@api_bp.route("/annotations/rules", methods=["GET"])
@login_required
@teacher_required
def annotations_rules():
    """C7 规则列表管理（功能 9.6）。跨唱段的全库标注列表，可按 tag 与 word 筛。

    **权限是教师**（文档 C7 的权限列就是「教师」），与同组 C4/C5/C6 一致。

    契约未在文档中定义——文档只有「`GET /api/annotations/rules?tag=&word=` ｜
    教师 ｜ 规则列表管理（功能 9.6）」一行，响应体、两个参数的匹配语义、排序、
    分页一概没有。本轮口径见 `DOC_ISSUES.md` 第 32 条与本接口的 spec。

    `request.args.get(...) or None` 把**缺省与空串一起收敛成 None**
    （`?tag=` 与不带 tag 都是「不筛」）。不做 `strip()`：`?word=%20三` 这种
    畸形输入原样匹配、匹配不上回空列表，比替调用方猜意图更可预期。

    **tag 在 SQL 筛、word 在 service 的 Python 循环里筛**：word 筛的是字，
    而字不存在于 annotations 表里，得先归一 lyrics_json 才算得出来。
    这个不对称是本质的，理由见 service 层。

    **不校验 tag 取值**：筛一个词表外的值是**合法查询**，回 `200` + `[]`，
    不是 `422`。词表只为写入端把关（C5）——那是为了「不再生产脏数据」，
    读取端宽容同 C4 出参的不校验口径。

    **本接口没有 404，也没有 422**：没有路径参数、不读 body（`_payload()`
    不参与）、不校验入参取值。唯一的失败是权限（401/403）。

    与 C6 的 `/annotations/<int:annotation_id>` 不冲突，且不依赖注册顺序：
    `rules` 不是整数，永远匹配不上 IntegerConverter（正则 `\\d+`）。
    """
    tag = request.args.get("tag") or None
    word = request.args.get("word") or None
    rows = library_service.annotation_rules(get_db(), tag=tag, word=word)
    return ok([AnnotationRuleOut.model_validate(r).model_dump(mode="json") for r in rows])
```

- [ ] **Step 4: 确认 reloader 吃到了改动**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
sleep 2
echo -n "GET /api/annotations/rules → "
curl -s -b /tmp/c7-t.jar "http://127.0.0.1:8877/api/annotations/rules" -w ' [%{http_code}]\n'
```

预期：`data` 是**数组**（3 条真数据），不再是回显对象。

**若仍回 `{"tag":null,"word":null}`，说明 reloader 没重载**——去看跑 `app-d.py` 那个终端的报错，多半是语法错让 reloader 留在了旧代码上。

- [ ] **Step 5: 跑接口验证矩阵**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
U=http://127.0.0.1:8877
J='Content-Type: application/json'
G() { curl -s -b "$1" "$2" -w ' [%{http_code}]\n'; }

# 学生 cookie
curl -s -c /tmp/c7-s.jar -H "$J" -X POST \
  -d '{"username":"stu001","password":"xiyun@2026"}' $U/api/auth/login >/dev/null

# 下面 URL 里的百分号编码就是中文本身（%E6%8B%96%E8%85%94 = 拖腔），
# 编码只是为了让命令在任何 locale 下都跑得一样；直接写中文也能跑。
echo "1  不带参数            :"; G /tmp/c7-t.jar "$U/api/annotations/rules"
echo "2  tag=拖腔            :"; G /tmp/c7-t.jar "$U/api/annotations/rules?tag=%E6%8B%96%E8%85%94"
echo "3  tag=滑音            :"; G /tmp/c7-t.jar "$U/api/annotations/rules?tag=%E6%BB%91%E9%9F%B3"
echo "4  tag 空串            :"; G /tmp/c7-t.jar "$U/api/annotations/rules?tag="
echo "5  word=三             :"; G /tmp/c7-t.jar "$U/api/annotations/rules?word=%E4%B8%89"
echo "6  word=炮（歌词有）    :"; G /tmp/c7-t.jar "$U/api/annotations/rules?word=%E7%82%AE"
echo "7  word 空串           :"; G /tmp/c7-t.jar "$U/api/annotations/rules?word="
echo "8  tag+word 与关系     :"; G /tmp/c7-t.jar "$U/api/annotations/rules?tag=%E6%8B%96%E8%85%94&word=%E5%90%8C"
echo "9  tag+word 空交集     :"; G /tmp/c7-t.jar "$U/api/annotations/rules?tag=%E6%8B%96%E8%85%94&word=%E4%B8%89"
echo "10 tag 词表外          :"; G /tmp/c7-t.jar "$U/api/annotations/rules?tag=%E9%9A%8F%E4%BE%BF"
echo "11 未登录              :"; curl -s "$U/api/annotations/rules" -w ' [%{http_code}]\n'
echo "12 学生登录            :"; G /tmp/c7-s.jar "$U/api/annotations/rules"
```

预期逐条：

| # | 用例 | 期望 |
|---|---|---|
| 1 | 不带参数 | `200`，`data` 是**长度 3 的数组**，`word_index` 依次 3/7/9，`char` 依次 三/同/震，`id` 依次 109/110/111 |
| 2 | `?tag=拖腔` | `200`，1 条（id 110） |
| 3 | `?tag=滑音` | `200` + `"data":[]` |
| 4 | `?tag=`（空串） | `200`，**3 条**（等同不筛） |
| 5 | `?word=三` | `200`，1 条（id 109） |
| 6 | `?word=炮` | `200` + `[]`——**「炮」是歌词里的字但没人标注**，这一条证明 `word` 筛的是标注不是歌词 |
| 7 | `?word=`（空串） | `200`，**3 条** |
| 8 | `?tag=拖腔&word=同` | `200`，1 条 |
| 9 | `?tag=拖腔&word=三` | `200` + `[]`——**两个条件是与关系**，不是或 |
| 10 | `?tag=随便`（词表外） | `200` + `[]`，**不是 422** |
| 11 | 未登录 | `{"code":401,"message":"未登录",...}` `[401]` |
| 12 | 学生登录 | `{"code":403,"message":"需要教师权限",...}` `[403]` |

再单独确认出参字段集：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
curl -s -b /tmp/c7-t.jar "http://127.0.0.1:8877/api/annotations/rules" \
  | .venv/bin/python -c "
import json,sys
d = json.load(sys.stdin)['data']
assert len(d) == 3, len(d)
r = d[0]
print('键：', sorted(r))
assert len(r) == 10, sorted(r)
for banned in ('teacher_id','seq','lyrics_json'):
    assert banned not in r, banned
assert r['demo_title'] == '《穆桂英挂帅》· 辕门外三声炮', r['demo_title']
assert r['segment_title'] == '辕门外三声炮如同雷震', r['segment_title']
assert r['demo_id'] == 16 and r['segment_id'] == 110
print('字段集与归属 OK')
"
```

预期：打印 10 个键，然后 `字段集与归属 OK`。

- [ ] **Step 6: 清理，确认表回到 3 行**

本任务的验证矩阵**全是只读**，不造行。确认即可：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
docker exec docker_postgres psql -U xiyun -d xiyun -At -c "SELECT count(*) FROM annotations;"
docker exec docker_postgres psql -U xiyun -d xiyun -At -c "SELECT id FROM annotations ORDER BY id;"
```

预期：`3`，然后 `109` / `110` / `111`。**不是这个就停下来查——本任务不该改数据。**

- [ ] **Step 7: Commit**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add app/schemas/demo.py app/api/demos_segments_annotations.py
git commit -m "feat: 实现标注规则列表接口 C7 GET /api/annotations/rules"
```

---

## Task 3: 登记 DOC_ISSUES 第 32 条 + 终检

**Files:**
- Modify: `DOC_ISSUES.md`（在 `## 待核实` 之前插入第 32 条；并更新第 28 条「待确认」的第 1 问）

**Interfaces:**
- Consumes: Task 1–2 的全部结论
- Produces: 无代码接口

- [ ] **Step 1: 写 `DOC_ISSUES.md` 第 32 条**

在 `## 待核实` 之前插入：

````markdown
## 32. 规则列表管理（C7）只有一句话描述，响应契约全未定义；`word` 筛选被迫读 `lyrics_json`

**涉及**：《5-接口清单》2.3 节 C7 / 《3-功能清单》9.6 / `app/api/demos_segments_annotations.py` / `app/services/library_service.py` / `app/repositories/annotations_repo.py` / `app/schemas/demo.py`

### 32.1 C7 的契约全未定义

C7 在文档里的**全部**内容是「`GET /api/annotations/rules?tag=&word=` ｜ 教师 ｜ 规则列表管理（功能 9.6）」一行，《3-功能清单》9.6 的全文是「标注规则列表管理 / 集中展示+筛选」。与第 26（C1）、27（C2/C3）、28（C4）、30（C5）、31（C6）条同源。查询串里的 `tag=` / `word=` 两个参数名是**唯一的入参依据**。本次采用的口径：

| 未定义项 | 本次采用的口径 |
|---|---|
| 响应体 | 全库汇总行：`id` / `word_index` / `char` / `tag` / `tolerance` / `created_at` / `segment_id` / `segment_title` / `demo_id` / `demo_title` |
| 为什么带归属 | C7 面向**全库**，没有归属这张表就读不出「这条规则属于哪个曲目」。与 C4 相反：C4 不返回 `segment_id`（它是入参），C7 必须返回（它不是入参） |
| `tag=` | **精确相等**，下推到 SQL |
| `word=` | **与 `char` 精确相等**（单字，非模糊、非子串），在 service 的 Python 循环里筛 |
| 为什么两个参数不同层 | `word` 筛的字**不存在于 `annotations` 表**，得先归一 `segments.lyrics_json` 才算得出来，SQL 层拿不到。这个不对称是本质的 |
| 缺省 / 空串 | `?tag=` 与不带 `tag` 一律当「不筛」 |
| `tag=` 取值 | **不校验词表**。筛一个词表外的值是合法查询，回 `200` + `[]`，不是 `422`。词表只为写入端把关（C5），读取端宽容同 C4 出参 |
| 排序 | `demo_id, segment_id, word_index, id` 全升序。先按曲目分组，再按唱段、再按字序；末位 `id` 保证稳定 |
| `char` 取不到 | 回 `null`，**行保留不剔除**。三种来源：`segment_id` 为 NULL、`lyrics_json` 为 NULL、`word_index` 越界。同 C4 spec 5.5「越界保留、让脏数据可见」 |
| 连接方式 | `outerjoin` 而非 `join`——`annotations.segment_id` 与 `segments.demo_id` 在 DDL 上均可空，内连接会把脏行整条丢掉且毫无提示 |
| 分页 | 无 |
| 失败 | 只有 `401`（未登录）与 `403`（非教师）。**没有 404、没有 422**：无路径参数、不读 body、不校验入参取值 |
| `created_at` | 不做时区换算（同第 28.2 条，落库的就是北京时间） |

### 32.2 「`word` 筛选被迫读 `lyrics_json`」与第 28 条的表面冲突

第 28 条（C4 spec 3.2）曾明确**拒绝**让后端读 `lyrics_json` 去算 `char`，理由是「`_normalize_lyrics` 会丢弃非法条目，一丢弃就发生下标错位，取到的是别的字」。C7 反过来**必须**读，这不是自相矛盾：

1. **C4 的错位是「两份坐标系」造成的**——C4 里后端算一份、前端从自己加载的 `lyrics` 也算一份，两份可能不一致。C7 里前端根本没有别的唱段的 `lyrics`，**只有后端这一份**，不存在第二个坐标系。
2. **`_normalize_lyrics` 本来就是三处共用的同一个函数**：C3 出参（`segment_detail`）、C5 写入校验（`create_annotation` 判下标上界）、C7 的 `char`。三处必须同源，否则会出现「C5 说这个下标合法、C7 却取到别的字」。C4 让前端自己取反而是那个「第二份」。
3. C7 仍然**不返回**原始 `lyrics_json`，只返回算好的单字。

### 32.3 数据现状（2026-09-30 实测，**与前几条记的 0 行已不同**）

`annotations` 表**有 3 行真数据**，全部挂在 **seg 110**（demo 16「《穆桂英挂帅》· 辕门外三声炮」第 1 段「辕门外三声炮如同雷震」，10 字），`teacher_id` 都是 2（`teacher01`）：

| id | word_index | 对应字 | tag | tolerance |
|---|---|---|---|---|
| 109 | 3 | 三 | 归韵 | 30 |
| 110 | 7 | 同 | 拖腔 | 30 |
| 111 | 9 | 强音 | 强音 | 37 |

第 28.1 / 30.1 / 31.4 三条都写着「实测 0 行」，**已过时**。C7 是本组里第一个**读路径有真数据可验**的接口，临时插行只用于验「跨唱段排序」与「越界 / `segment_id` 为 NULL」三个真数据覆盖不到的分支。

### 32.4 与第 28 条「待确认」的关系

第 28.1 的「待文档方确认」第 1 问是：

> C4 出参是否够用？C7（规则列表管理，功能 9.6）是否需要更多字段（如教师名、创建时间）？

C7 落地后本次的回答：**要 `char` 与曲目/唱段归属，不要教师名**。

- `char`：不给的话前端渲染不出「哪个字」，而 C7 场景下前端无从自己取（见 32.2）
- 曲目 / 唱段归属：同上，没有它这张表读不出上下文
- **教师名不要**：C7 与 C4 一样不按教师隔离（第 28.1 条、第 31.2 条），名单既不可用于过滤也不可用于展示归属
- `created_at` 保留返回，但当前无调用方消费（同第 28.1 条对 C4 的观察）

**待文档方确认**：

1. `word=` 是**精确等于一个字**，还是期望模糊 / 包含匹配（如 `word=辕门` 匹配「辕门外」）？本次按精确。若期望模糊，`char` 的语义与前端输入框形态都要一起定。
2. **全库列表不分页**是否可行？当前 `annotations` 只有 3 行，但这是全库累积的表，标注量上来之后一次返回全部可能拖垮页面。本次不分页（同 C1–C4 无先例）。
3. `?tag=词表外的值` 回 `200` + `[]` 是否可行，还是期望 `422`？本次回空列表（理由见 32.1 表格）。
4. 是否需要「按曲目 / 唱段筛」的参数？功能 9.6 只给了 `tag` 与 `word`，但「规则列表管理」在界面上大概率还要按曲目过滤。
````

- [ ] **Step 2: 更新第 28 条「待确认」的第 1 问**

第 28 条「待文档方确认」列表的第 1 点是：

```
1. C4 出参是否够用？C7（规则列表管理，功能 9.6）是否需要更多字段（如教师名、创建时间）？
```

改为：

```
1. C4 出参是否够用？C7（规则列表管理，功能 9.6）是否需要更多字段（如教师名、创建时间）？——**C7 已于 2026-09-30 实现，回答见第 32.4 条**：要 `char` 与曲目/唱段归属，不要教师名。
```

- [ ] **Step 3: 跑建库一致性闸门**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python scripts/check_db.py
```

预期：**无新增差异**（本轮不改模型与 `schema.sql`）。脚本会报既有的 `demo_versions` 表 + `teacher_demos` 三列漂移——那是本轮之前就有的。**若报出 `annotations` 相关的差异，停下来查。**

- [ ] **Step 4: 终检——表回到 3 行**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
docker exec docker_postgres psql -U xiyun -d xiyun -At -c "SELECT count(*) FROM annotations;"
docker exec docker_postgres psql -U xiyun -d xiyun -At -c "SELECT id FROM annotations ORDER BY id;"
```

预期：`3`，然后 `109` / `110` / `111`。**真数据丢一行就说明前面某个任务清理时删错了。**

- [ ] **Step 5: 终检——占位确实没了、C6 确实还在**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
echo "--- C7 占位应无输出 ---"
grep -n 'return ok({"tag":tag,"word":word})' app/api/demos_segments_annotations.py
echo "--- C7 新实现应有输出 ---"
grep -n 'def annotations_rules' -A 3 app/api/demos_segments_annotations.py
echo "--- C6 应原样还在 ---"
grep -n 'annotations/<int:annotation_id>' app/api/demos_segments_annotations.py
grep -n 'return ok(None)' app/api/demos_segments_annotations.py
echo "--- 不应有 frontend 改动 ---"
git status --porcelain -- '*.html'
```

预期：第一段**无输出**；第二段有 `def annotations_rules`；第三段各 1 行；第四段**无输出**（本轮不碰任何 `.html`）。

- [ ] **Step 6: Commit**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add DOC_ISSUES.md
git commit -m "docs: 登记 C7 响应契约未定义与 word 筛选读 lyrics_json 的口径"
```

---

## 完成之后

全部任务做完、`annotations` 确认 **3 行**（109/110/111）之后，用 `superpowers:finishing-a-development-branch` 收尾（本项目历来是直接提交到 `main`，无 feature 分支，届时按实际状态处理）。

**C7 落地后 2.3 节的 7 个接口（C1–C7）全部实现完毕。** 前端接入（功能 9.6 的「规则列表管理」页面）是后续独立任务，不在本计划范围内。
