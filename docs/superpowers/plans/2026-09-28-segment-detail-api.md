# 段落详情接口（C3 `GET /api/segments/<id>`）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 C3——返回单个唱段的元信息 + 归一后的逐字歌词，并让 `annotation.html` 的歌词网格第一次读真数据。

**Architecture:** 先把库里遗留的两套 `note` 词表归一到数据层（seed.sql + 真库 seg 1），再加一个纯函数把 `lyrics_json` 的库内形状映射成出参形状，最后把页面里两个按下标索引的 mock（`LYRICS` / `EXISTING_ANNS`）换成 C3 的真数据。

**Tech Stack:** Python 3.11 / Flask / SQLAlchemy 2.x / PostgreSQL(JSONB) / pydantic v2 / 原生 JS 单页

**依据 spec:** `docs/superpowers/specs/2026-09-28-segment-detail-api-design.md`

## Global Constraints

- **不新增测试框架。** 本仓库没有 `tests/`、`requirements.txt` 里也没有 pytest。验证一律用**对真接口跑的 curl**、`.venv/bin/python` 与 `/browse` 实测。不要 `pip install pytest`。
- **Python 解释器用 `.venv/bin/python`**，先 `cd` 到项目根目录。PATH 上的 `python`/`pip` 是 pyenv 的 3.12（见记忆 `pip-mirror-and-interpreter-gotchas`）。
- **`/api` 前缀只在 `app/api/__init__.py` 的 `url_prefix` 里写一次**，路由写相对路径。
- **响应一律用 `app/response.py` 的 `ok()`**。
- **权限只 `@login_required`**，不能加 `@teacher_required`（文档 C3 的权限列是「登录」，学生端陪练要看歌词）。
- **不改 `schema.sql` / `app/models/*` / `app-d.py`**，不引 Alembic，不加依赖。本轮**只改 seg 1 的数据**，不动表结构。
- **只做 C3。** `app/api/demos_segments_annotations.py` 里 C4–C7 那 4 个占位路由原样保留。
- **当前真库基线**（2026-09-28 实测，`segments` 全表 11 行）：

  | segment.id | 所属 demo | 条数 | `note` 词表 | 附点 |
  |---|---|---|---|---|
  | 1 | 1 | 2 | **`half`/`quarter`（本轮归一成 `NOTE_2`/`NOTE_4`）** | 0 |
  | 78 | 16 | 66 | `NOTE_*` | **0** |
  | 79 | 17 | 28 | `NOTE_*` | **6**（`NOTE_DOT_8`×1 + `NOTE_DOT_16`×5） |
  | 80 | 18 | 14 | `NOTE_*` | **6**（`NOTE_DOT_32`×1 + `NOTE_DOT_16`×5） |
  | 102 | 16 | 6 | 无（只有 `tip`） | 0 |
  | 103 | 16 | 4 | 无 | 0 |
  | 104 | 16 | 6 | 无 | 0 |
  | 105 | 16 | 3 | 无 | 0 |
  | 106 | 17 | 4 | 无 | 0 |
  | 107 | 17 | 3 | 无 | 0 |
  | 108 | 18 | 6 | 无 | 0 |

  汇总：142 条；`midi` 缺失 8 条（全是 seg 78 的标点）；`start`/`end` **无一缺失**；附点 12 条全在 seg 79/80。
  **写断言照这张表来；实测对不上就停下来核对，不要改断言去迁就结果。**
- `lyrics_json` 的库内形状是 `[{word, midi?, start, end, note?, tip?}]`（`app/models/demo.py:38` 的注释同此）。
- 种子账号 `teacher01`（教师）/ `stu001`（学生），密码 `xiyun@2026`。
- 注释、commit message 一律中文；标识符英文。

## 面板初始值（Task 4 重置时要还原成这些）

来自 `annotation.html` 的 HTML 字面量，**不是**猜的：

| 元素 | 初始值 | 出处 |
|---|---|---|
| `#bigChar` | `—` | 第 480 行 |
| `#charInfo` | `点击左侧歌词字进行标注` | 第 481 行 |
| `#charMeta` | `display:none` | 第 482 行 |
| `#annotateControls` | `opacity:1; pointer-events:none` | 第 489 行 |
| `#depsPanel` | 无 `.show` 类 | 第 507 行 |
| `.type-btn` | 无 `.active` 类 | `selectChar` 第 658 行 |

---

## 文件结构

| 文件 | 职责 | 本次改动 |
|---|---|---|
| `seed.sql` | 建库种子 | seg 1 的 `half`/`quarter` → `NOTE_2`/`NOTE_4` |
| `app/repositories/library_repo.py` | 数据访问 | +`get_segment` |
| `app/services/library_service.py` | 业务逻辑与口径 | +`segment_detail`、+`_normalize_lyrics`、+`_num` |
| `app/schemas/demo.py` | 出参模型 | +`LyricCharOut`、+`SegmentDetailOut` |
| `app/api/demos_segments_annotations.py` | HTTP 层 | `/segments/<id>` 填实现，路由收紧为 `<int:segment_id>`；+1 import |
| `DOC_ISSUES.md` | 需求文档问题登记 | 第 27.2 节写定四件事 + 更正一句错话 |
| `annotation.html` | 歌词级标注页 | 删 `LYRICS`/`EXISTING_ANNS`；+`noteLabel`/`fetchLyrics`/`resetAnnotationPanel`；`renderLyrics`/`selectChar`/`saveAnnotation`/`switchSegment` 改造 |

---

## Task 1: 把 `note` 词表归一到数据层

**Files:**
- Modify: `seed.sql:33-35`
- 真库：`segments` 表 id=1 那一行的 `lyrics_json`

**Interfaces:**
- Consumes: 无
- Produces: 库里 `note` 只剩 `NOTE_*` 一套词表（Task 2/3 的验证依赖这点）

- [ ] **Step 1: 改 `seed.sql`**

把第 33–35 行的 `"note":"half"` 与 `"note":"quarter"` 改掉。改完这一段应当是：

```sql
INSERT INTO segments (demo_id, seq, title, lyrics_json, duration) VALUES (1, 1, '第一段',
'[{"word":"海","midi":57,"start":0.00,"end":1.20,"note":"NOTE_2","tip":"起音轻，气息下沉"},
  {"word":"岛","midi":55,"start":1.20,"end":1.80,"note":"NOTE_4","tip":"归韵收净"}]'::jsonb, 30.5);
```

- [ ] **Step 2: 归一真库 seg 1**

**按「值」匹配，不按「下标」匹配**：`half`/`quarter` 各自唯一，而下标法一旦 `lyrics_json` 被重排就会静默改错字。脚本结尾断言**恰好改了 2 处**。

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python - <<'PY'
import json
from sqlalchemy import select, text
from app.db import SessionLocal
from app.models.demo import Segment

LEGACY = {"half": "NOTE_2", "quarter": "NOTE_4"}
db = SessionLocal()
changed = 0
for seg in db.scalars(select(Segment).where(Segment.lyrics_json.isnot(None))):
    old = seg.lyrics_json
    new = [{**e, "note": LEGACY[e["note"]]} if isinstance(e, dict) and e.get("note") in LEGACY else e
           for e in old]
    if new != old:
        n = sum(1 for a, b in zip(old, new) if a != b)
        changed += n
        # JSONB 不跟踪原地修改，走显式 UPDATE 而不是给 ORM 属性赋值
        db.execute(text("UPDATE segments SET lyrics_json = CAST(:j AS jsonb) WHERE id = :i"),
                   {"j": json.dumps(new, ensure_ascii=False), "i": seg.id})
        print(f"  seg {seg.id}: 改 {n} 处")
db.commit()
assert changed == 2, f"预期恰好 2 处，实际 {changed} 处"
print("OK 共归一", changed, "处")
PY
```

预期输出：

```
  seg 1: 改 2 处
OK 共归一 2 处
```

- [ ] **Step 3: 验证——全库只剩 `NOTE_*` 一套词表**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python -c "
import json
from collections import Counter
from sqlalchemy import text
from app.db import SessionLocal
rows = SessionLocal().execute(text('SELECT id, lyrics_json FROM segments WHERE lyrics_json IS NOT NULL ORDER BY id')).all()
c, tot = Counter(), 0
for sid, lj in rows:
    for e in lj:
        tot += 1
        if 'note' in e: c[e['note']] += 1
print('总条目', tot)
print('note 取值:', dict(sorted(c.items())))
legacy = [k for k in c if not k.startswith('NOTE_')]
print('非 NOTE_ 词表:', legacy or '无 ✓')
assert not legacy
assert tot == 142
print('条数 142 ✓')
"
```

预期：`note 取值` 里出现 `NOTE_1/2/4/8/16/32` 与 3 个 `NOTE_DOT_*`，**不再有 `half`/`quarter`**；总条目仍是 **142**。

- [ ] **Step 4: 确认 `check_db.py` 无新增差异**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python scripts/check_db.py; echo "exit=$?"
```

预期：只剩既有漂移（`demo_versions` 表 + `teacher_demos` 的 `parse_status`/`parse_time_sec`/`techniques_json` 三列，见记忆 `check-db-pre-existing-drift`）。本轮不动表结构，**不该有任何新差异**。

- [ ] **Step 5: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add seed.sql
git commit -m "fix: 归一 lyrics_json 的 note 词表，清掉 seed 里的 half/quarter"
```

---

## Task 2: repo + service + schema

**Files:**
- Modify: `app/repositories/library_repo.py`（`list_segments` 之后追加 `get_segment`）
- Modify: `app/services/library_service.py`（末尾追加 `_num`、`_normalize_lyrics`、`segment_detail`）
- Modify: `app/schemas/demo.py`（末尾追加 `LyricCharOut`、`SegmentDetailOut`）

**Interfaces:**
- Consumes: Task 1 归一后的数据
- Produces（Task 3 依赖）:
  - `library_repo.get_segment(db: Session, segment_id: int) -> Segment | None`
  - `library_service.segment_detail(db: Session, segment_id: int) -> dict` —— 键为 `id/seq/title/duration/lyrics`；唱段不存在抛 `BusinessError(404, "唱段不存在")`
  - `app.schemas.demo.SegmentDetailOut` / `LyricCharOut`

- [ ] **Step 1: 在 `library_repo.py` 的 `list_segments` 之后追加 `get_segment`**

**不需要新增 import。** `Segment` 已在该文件引入（`list_segments` 在用）。

先确认 `list_segments` 的结尾位置：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && sed -n '30,40p' app/repositories/library_repo.py
```

在 `list_segments` 函数结束后追加：

```python
def get_segment(db: Session, segment_id: int) -> Segment | None:
    """按主键取单个分段。供 C3。

    用 db.get 而不是 select().where()：它先查会话的 identity map，命中就不发 SQL。
    这里没有 join 需求，主键查询就是全部。
    """
    return db.get(Segment, segment_id)
```

- [ ] **Step 2: 在 `library_service.py` 末尾追加三个函数**

**不需要新增 import**：`Segment`、`BusinessError`、`library_repo` 顶部都已引入。

```python
def _num(v) -> float | None:
    """JSONB 列没有类型约束，只放行真正的数值，其余一律 None。

    挡住字符串 "64"、True 这类：前端拿 pitch 去算 midiToNote()，非数值会渲染成
    「NaN undefined」，不如按「没有值」处理（spec 3.2）。

    bool 要单独排除——Python 里 isinstance(True, int) 是 True。
    """
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v


def _normalize_lyrics(raw: list | None) -> list[dict]:
    """把 lyrics_json 的库内形状映射成 C3 出参的逐字形状（spec 3.2）。

    | 库          | 出参       | 规则                                        |
    | word        | char       | 缺失/非字符串 → **整条丢弃**（构造不出字）       |
    | midi        | pitch      | 缺失/非数值 → None（前端靠 pitch === null 判标点）|
    | start       | start      | 缺失/非数值 → None                            |
    | end - start | duration   | 任一缺失 → None；标点是 end == start → 0.0     |
    | note        | note       | **原样传 NOTE_***，不做分数串映射（那是前端显示词）|
    | tip         | tip        | 缺失 → None                                  |

    raw 为 None（解析产出的新段落就是这样，见 DOC_ISSUES 第 20 条）→ 返回 []，
    不是 None：前端统一按数组处理，少一个分支。这是**常态不是边角**。

    条目不是对象就跳过，不让一个脏条目把整个接口打成 500。
    """
    out = []
    for e in raw or []:
        if not isinstance(e, dict):
            continue
        word = e.get("word")
        if not isinstance(word, str):
            continue
        start = _num(e.get("start"))
        end = _num(e.get("end"))
        out.append({
            "char": word,
            "pitch": _num(e.get("midi")),
            "start": start,
            "duration": (end - start) if (start is not None and end is not None) else None,
            "note": e.get("note"),
            "tip": e.get("tip"),
        })
    return out


def segment_detail(db: Session, segment_id: int) -> dict:
    """C3 段落详情。含归一后的逐字歌词。

    曲目列表（C1）与分段列表（C2）都不碰 lyrics_json，这里是唯一入口——
    也正是因此，映射逻辑写在这一个地方就够了，不必给每个调用方各写一遍。

    不返回 demo_id（调用方从 C2 过来，本来就知道，同 C2 不返回它的理由），
    不返回原始 lyrics_json 字符串（那是 JSONB 列的内部表示）。
    """
    seg = library_repo.get_segment(db, segment_id)
    if seg is None:
        raise BusinessError(404, "唱段不存在")
    return {
        "id": seg.id,
        "seq": seg.seq,
        "title": seg.title,
        "duration": seg.duration,
        "lyrics": _normalize_lyrics(seg.lyrics_json),
    }
```

- [ ] **Step 3: 在 `app/schemas/demo.py` 末尾追加两个模型**

```python
class LyricCharOut(BaseModel):
    """逐字歌词的一格（C3）。

    字段名对齐前端 annotation.html 的 LYRICS：库里的 word/midi/end 在这里换成
    char/pitch，end 与 start 合成 duration（spec 3.2）。

    **pitch 为 None 表示这是标点**——前端靠 `item.pitch === null` 加 .punct 类
    且不挂 onclick。所以映射时「库里的 midi 键缺失」必须补成显式 None，
    漏成 undefined 的话 undefined === null 为 false，标点会渲染成可点的坏格子。

    note 原样是 NOTE_* 词表（backend 不决定怎么显示，spec 3.4）。
    """

    model_config = ConfigDict(from_attributes=True)

    char: str
    pitch: float | None = None
    start: float | None = None
    duration: float | None = None
    note: str | None = None
    tip: str | None = None


class SegmentDetailOut(BaseModel):
    """段落详情（C3）。

    `duration` 是**唱段时长**，与 `lyrics[].duration`（单字时长）同名不同义，
    靠层级区分（spec 3.1）。

    `lyrics` 无歌词时是 []，不是 None：lyrics_json 为 NULL 的新段落会大量命中。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    seq: int | None = None
    title: str | None = None
    duration: float | None = None
    lyrics: list[LyricCharOut] = []
```

- [ ] **Step 4: 验证——对真库跑，逐唱段核对**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python -c "
from app.db import SessionLocal
from app.services.library_service import segment_detail
db = SessionLocal()
for sid in (1, 78, 79, 80, 102, 103, 104, 105, 106, 107, 108):
    d = segment_detail(db, sid)
    notes = {x['note'] for x in d['lyrics']}
    print(f\"seg {sid}: {len(d['lyrics'])} 条  demo={d['seq']}  duration={d['duration']}  note={sorted(n for n in notes if n)}\")
"
```

预期：条数与 Global Constraints 的基线表**逐行一致**（1→2、78→66、79→28、80→14、102→6、103→4、104→6、105→3、106→4、107→3、108→6），且：

- **seg 1 的 note 是 `['NOTE_2', 'NOTE_4']`**（Task 1 归一生的效）
- seg 79 含 `NOTE_DOT_16` / `NOTE_DOT_8`；seg 80 含 `NOTE_DOT_16` / `NOTE_DOT_32`
- seg 102–108 的 note 集合为空（只有 `tip`）

- [ ] **Step 5: 验证——映射规则的四个分支**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python -c "
from app.db import SessionLocal
from app.services.library_service import segment_detail, _normalize_lyrics
db = SessionLocal()

d = segment_detail(db, 78)
first = d['lyrics'][0]
print('首条:', first)
assert first == {'char':'辕','pitch':64,'start':0.0,'duration':0.234,'note':'NOTE_8','tip':None}, first
assert set(first) == {'char','pitch','start','duration','note','tip'}
print('键集合与首条 ✓')

# 标点：库里没有 midi 键 → 必须补成显式 None
punct = [x for x in d['lyrics'] if x['char'] in '，。']
print('标点', len(punct), '条，样例:', punct[0])
assert len(punct) == 8
assert all(x['pitch'] is None and x['note'] is None and x['duration'] == 0.0 for x in punct), punct
print('标点补齐为显式 null ✓')

# tip-only 形状
t = segment_detail(db, 102)['lyrics']
assert all(x['note'] is None and x['tip'] for x in t), t
print('tip-only ✓')

# raw 为 None → []
assert _normalize_lyrics(None) == []
# 脏条目：非对象、无 word、midi 是字符串
dirty = _normalize_lyrics([None, 'x', {'midi':1}, {'word':'好','midi':'64','start':0,'end':1}])
print('脏数据结果:', dirty)
assert len(dirty) == 1 and dirty[0]['pitch'] is None and dirty[0]['duration'] == 1.0
print('全部通过 ✓')
"
```

预期：全部断言通过，末行 `全部通过 ✓`。

- [ ] **Step 6: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add app/repositories/library_repo.py app/services/library_service.py app/schemas/demo.py
git commit -m "feat: 新增段落详情查询与逐字歌词归一（C3 数据层）"
```

---

## Task 3: 填路由 + 文档登记

**Files:**
- Modify: `app/api/demos_segments_annotations.py:30-33`（填 `segments()`，补 1 个 import）
- Modify: `DOC_ISSUES.md`（第 27.2 节）

**Interfaces:**
- Consumes: Task 2 的 `library_service.segment_detail` 与 `SegmentDetailOut`
- Produces: `GET /api/segments/<int:segment_id>` —— 登录可见

- [ ] **Step 1: 补 import**

把：

```python
from app.schemas.demo import DemoListOut, DemoSegmentOut
```

改成：

```python
from app.schemas.demo import DemoListOut, DemoSegmentOut, SegmentDetailOut
```

- [ ] **Step 2: 填掉 `segments()`**

当前的占位实现（C2 之后行号约 37–40）：

```python
@api_bp.route("/segments/<id>",methods=["GET"])
@login_required
def segments(id):
    return ok(id);
```

改成：

```python
@api_bp.route("/segments/<int:segment_id>", methods=["GET"])
@login_required
def segments(segment_id):
    """C3 段落详情，含逐字歌词。

    `<int:segment_id>` 同 C2：非数字路径在**路由层**就 404，不进视图。

    权限只要求登录（文档 C3 的权限列就是「登录」）：学生端陪练要看歌词，
    加 @teacher_required 会堵死学生端。注意 C4–C7 才是教师专属。

    唱段存在但还没歌词时回 200 + lyrics: []，不是 404——解析产出的新段落
    lyrics_json 就是 NULL（DOC_ISSUES 第 20 条），那是常态。
    """
    data = library_service.segment_detail(get_db(), segment_id)
    return ok(SegmentDetailOut.model_validate(data).model_dump(mode="json"))
```

**注意路由参数名从 `<id>` 改成 `<int:segment_id>` 后，视图函数形参也要一起改成 `segment_id`**——Flask 按**名字**传路径参数，对不上会抛 `TypeError`。

**注意这一处与上面 `/segments/<id>/annotations` 不是同一个路由**，后者（C4）原样保留，一个字都不要动。

- [ ] **Step 3: 重启后端并登录**

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

> **重启会把已登录的浏览会话踢掉**：`/browse` 的 daemon 在 Task 4 里要重新登一次。

- [ ] **Step 4: 验证——未登录 401 / 学生可访问 / 404**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
echo -n "未登录: "; curl -s -o /tmp/c3-anon.json -w '%{http_code} ' http://127.0.0.1:8877/api/segments/78; cat /tmp/c3-anon.json; echo
echo -n "学生 seg78: "; curl -s -b /tmp/s.jar http://127.0.0.1:8877/api/segments/78 | .venv/bin/python -c "import json,sys; b=json.load(sys.stdin); print('code=',b['code'],'lyrics=',len(b['data']['lyrics']))"
echo -n "不存在 99999: "; curl -s -b /tmp/t.jar -o /tmp/c3-404.json -w '%{http_code} ' http://127.0.0.1:8877/api/segments/99999; cat /tmp/c3-404.json; echo
echo -n "非数字 abc: "; curl -s -b /tmp/t.jar -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8877/api/segments/abc
```

预期：

- 未登录 → `401` + `{"code":401,...}`
- 学生 → `code= 0 lyrics= 66`。**若回 403，说明误加了 `@teacher_required`**
- 99999 → `404` + `{"code":404,"message":"唱段不存在","data":null}`
- `abc` → `404`，body 是 Flask 默认 HTML 页（路由没匹配上，不进统一错误处理器；C2 spec 3.3 已写明这是 Flask 行为）

- [ ] **Step 5: 验证——全库 11 个唱段逐个跑，没有一个 500**

这一条最重要：JSONB 里的脏条目最容易让某个唱段**单独**炸。

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
for id in 1 78 79 80 102 103 104 105 106 107 108; do
  code=$(curl -s -b /tmp/t.jar -o /tmp/c3-$id.json -w '%{http_code}' http://127.0.0.1:8877/api/segments/$id)
  .venv/bin/python -c "
import json,sys
b=json.load(open('/tmp/c3-$id.json'))
d=b['data']
ks={k for x in d['lyrics'] for k in x}
bad=[x for x in d['lyrics'] if set(x)!={'char','pitch','start','duration','note','tip'}]
print(f\"seg $id: http=$code code={b['code']} 条数={len(d['lyrics'])} 键={sorted(ks)} 坏条目={len(bad)}\")
assert '$code'=='200' and b['code']==0 and not bad
"
done
echo "---- 出参不得含 demo_id / lyrics_json ----"
curl -s -b /tmp/t.jar http://127.0.0.1:8877/api/segments/78 | grep -c 'demo_id\|lyrics_json' || echo "无 ✓"
```

预期：11 行全是 `http=200 code=0 坏条目=0`，条数与基线表一致；末行输出 `无 ✓`（`grep -c` 无匹配时退出码 1，走 `||` 分支）。

- [ ] **Step 6: 验证——附点原样返回（seg 79/80）**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
for id in 79 80; do
  echo -n "seg $id 附点: "
  curl -s -b /tmp/t.jar http://127.0.0.1:8877/api/segments/$id | .venv/bin/python -c "
import json,sys
from collections import Counter
d=json.load(sys.stdin)['data']['lyrics']
c=Counter(x['note'] for x in d if x['note'] and x['note'].startswith('NOTE_DOT'))
print(dict(c), '共', sum(c.values()), '条')
"
done
```

预期：

- seg 79 → `{'NOTE_DOT_16': 5, 'NOTE_DOT_8': 1}` 共 **6** 条
- seg 80 → `{'NOTE_DOT_16': 5, 'NOTE_DOT_32': 1}` 共 **6** 条

**关键：`NOTE_DOT_16` 没有被截成 `NOTE_16`**（若出现 `NOTE_16` 计数异常升高，说明映射把附点前缀吃掉了）。

- [ ] **Step 7: 验证——`lyrics_json` 为 NULL 时回 `200` + `[]`**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python -c "
from sqlalchemy import text
from app.db import SessionLocal
db = SessionLocal()
db.execute(text(\"INSERT INTO segments (demo_id, seq, title, lyrics_json, duration) VALUES (16, 99, 'C3空歌词验证', NULL, 1.0)\"))
db.commit()
new_id = db.execute(text(\"SELECT id FROM segments WHERE title='C3空歌词验证'\")).scalar()
print('临时 segment id =', new_id)
"
```

拿到 id 后：

```bash
echo -n "空歌词: "; curl -s -b /tmp/t.jar -o /tmp/c3-null.json -w '%{http_code} ' http://127.0.0.1:8877/api/segments/<上一步的id>; cat /tmp/c3-null.json; echo
```

预期：`200` + `"lyrics": []`（**不是 404，也不是 null**）。

**验证完立刻删掉这行**：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python -c "
from sqlalchemy import text
from app.db import SessionLocal
db = SessionLocal()
db.execute(text(\"DELETE FROM segments WHERE title='C3空歌词验证'\"))
db.commit()
print('已删除，剩余行数:', db.execute(text('SELECT count(*) FROM segments')).scalar())
"
```

预期剩余 **11** 行。**若忘了删，demo 16 会多出一个假的「99 段」**，Task 4 的页面验证会看到它。

- [ ] **Step 8: 验证——经 nginx（80 端口）**

```bash
curl -s -b /tmp/t.jar http://127.0.0.1/api/segments/78 | head -c 200; echo
```

预期：与 Step 5 同样的 JSON。

- [ ] **Step 9: 改写 `DOC_ISSUES.md` 第 27.2 节**

把整个 27.2 节换成下面这版。**它同时承担两件事**：把本轮定下的四件事写成结论，以及**更正原文里那句错话**（原文写「库里没有标点条目」，实际 seg 78 有 8 条）。

从 `### 27.2 \`lyrics_json\` 的三种形状（做 C3 前必须先定）` 这一行起，到 `另见第 19、20、26 条。` 这一行为止（含），整段替换成：

```markdown
### 27.2 `lyrics_json` 的形状与词表（C3 已定）

**更正**：本节初版写「库里没有标点条目」，与库不符——seg 78 有 8 条标点。下文为准。

第 20 条写的「该列恒 NULL」只对**解析产出**的行成立（`replace_segments` 确实传 `None`）；`seed.sql` 与后来人工录入的行都有内容。

**库内形状**是 `[{word, midi?, start, end, note?, tip?}]`（`app/models/demo.py:38` 的注释同此）。所谓「三种形状」的差别不在字段名（名字一致），而在**哪些键存在**（142 条，2026-09-28 实测）：

| 条数 | 键集合 | 出现在 |
|---|---|---|
| 8 | `word, start, end` | seg 78 的标点。**直接没有 `midi`/`note` 键**，不是 `null` |
| 66 | `word, midi, start, end, note` | seg 78–80 |
| 34 | `word, midi, start, end, tip` | seg 102–108（33 条）+ seg 1（1 条） |
| 34 | `word, midi, start, end, note, tip` | seg 1 |

`midi` 缺失 8 条（全是标点）；`start`/`end` **无一缺失**。

**C3 定下的四件事**：

1. **字段名：库不动，接口层改名。** 出参用 `char/pitch/start/duration/note/tip`（`word→char`、`midi→pitch`、`end-start→duration`），前端零改动。库里 142 条已一致用 `word/midi/start/end`，没有改库的理由。
2. **`note` 词表统一成 `NOTE_*`**，已落到数据层：`half→NOTE_2`、`quarter→NOTE_4`（原本只有 seg 1 的两条），`seed.sql` 与真库同步改掉。分数串（`"8"`）是**前端显示词**，接口不做这层映射——`NOTE_8` 是领域取值，`"8"` 是 UI 措辞，两件事（同第 26 条对 `elo_difficulty` 的处置）。
3. **标点以「无 `midi` 键」表示**。接口层必须把它补成**显式 `null`**：前端 `renderLyrics` 靠 `pitch === null` 加 `.punct` 类并跳过 `onclick`，而 `undefined === null` 为 `false`，漏补会让标点渲染成一个带音高、可点击的坏格子。
4. **`tip` 与 `note` 正交**（seg 1 两者都有），不是二选一，接口两个都返回。附点（`NOTE_DOT_16` 等 12 条，全在 seg 79/80）**前端加档显示**，乐理信息不丢。

**仍未解**：解析链路给不出「字」，人工录入是唯一路径（第 20 条）。库里现有歌词全是人工/种子数据，C3 只是把已有的读出来。

**待文档方确认**：

1. `[{word, midi?, start, end, note?, tip?}]` 这个形状是否作为权威 schema 定下来？`NOTE_*` 那 8 个基本档 + 3 个附点够不够覆盖戏谱的时值？
2. 标点要不要一直用「缺 `midi` 键」表示，还是显式写 `"midi": null`？两者前端都吃，但显式更不容易被下一个录入者漏掉。
3. 只有 seg 78 有标点、其余唱段会渲染成一整行不断句。断句是否该由录入时补标点解决，还是另设行界字段？

另见第 19、20、26 条。
```

- [ ] **Step 10: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add app/api/demos_segments_annotations.py DOC_ISSUES.md
git commit -m "feat: 实现段落详情接口 C3 GET /api/segments/<id>"
```

---

## Task 4: `annotation.html` 歌词接真

**Files:**
- Modify: `annotation.html`（删除 537–586 行的两个 mock；改 `renderLyrics`/`selectChar`/`saveAnnotation`/`switchSegment`；新增 `noteLabel`/`fetchLyrics`/`resetAnnotationPanel`）

**Interfaces:**
- Consumes: Task 3 的 `GET /api/segments/<int:segment_id>`
- Produces: 无（页面终态）

- [ ] **Step 1: 删掉两个 mock**

`LYRICS`（537–571）与 `EXISTING_ANNS`（573–586）都是**按下标索引**的 mock，真歌词一进来就全错位。留下一半比删掉更糟——一个按 mock 下标索引、却渲染在真数据上的标注列表，看起来像真数据。

用带断言的脚本删，避免删错行：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python - <<'PY'
p = 'annotation.html'
lines = open(p, encoding='utf-8').read().split('\n')
# 1-based 537..586 → 0-based 536..585
assert lines[536].startswith('const LYRICS = ['), lines[536]
assert lines[570] == '];', repr(lines[570])
assert lines[572].startswith('const EXISTING_ANNS = ['), lines[572]
assert lines[585] == '];', repr(lines[585])
lines[536:586] = [
    '// 歌词不再有 mock：来自 C3（GET /api/segments/<id>），见页末 fetchLyrics()。',
    '// 标注列表同理待 C4（/segments/<id>/annotations），初始为空。',
]
open(p, 'w', encoding='utf-8').write('\n'.join(lines))
print('已删除 537-586 行')
PY
```

预期：`已删除 537-586 行`。**若抛 AssertionError，说明行号漂了**，用 `grep -n 'const LYRICS = \[\|const EXISTING_ANNS = \[' annotation.html` 重新定位后改脚本里的下标，不要直接硬删。

- [ ] **Step 2: 改状态声明**

现在的：

```js
let selectedIndex = -1;
let selectedTag = null;
let annotations = [...EXISTING_ANNS];
```

改成：

```js
let selectedIndex = -1;
let selectedTag = null;
// 待 C4：POST/GET/DELETE /api/annotations*。本轮永远是空数组
let annotations = [];
```

- [ ] **Step 3: 新增 `noteLabel`，并把两处嵌套三元换掉**

在 `midiToNote` 之后新增：

```js
const NOTE_LABELS = {
  "NOTE_1": "1/1 拍", "NOTE_2": "1/2 拍", "NOTE_4": "1/4 拍",
  "NOTE_8": "1/8 拍", "NOTE_16": "1/16 拍", "NOTE_32": "1/32 拍",
};
const NOTE_DOT_LABELS = {
  "NOTE_DOT_2": "1/2 附点拍", "NOTE_DOT_4": "1/4 附点拍", "NOTE_DOT_8": "1/8 附点拍",
  "NOTE_DOT_16": "1/16 附点拍", "NOTE_DOT_32": "1/32 附点拍",
};

function noteLabel(note) {
  // 后端统一传 NOTE_* 词表（DOC_ISSUES 第 27.2 条），分数串是这一层的显示词
  if (note === null || note === undefined) return "—";
  // 认不出来就原样显示。**不能有兜底档**：改造前那两处嵌套三元只认 "16"/"8"/"4"/"2"，
  // 遇到 NOTE_8 会一路落到最后的 "1/1"，把 1/8 拍显示成 1/1 拍
  return NOTE_LABELS[note] || NOTE_DOT_LABELS[note] || note;
}
```

`renderLyrics` 里第 632 行：

```js
      html += `<div class="lyric-note">${item.note==="16"?"1/16":(item.note==="8"?"1/8":(item.note==="4"?"1/4":(item.note==="2"?"1/2":"1/1")))}拍</div>`;
```

改成：

```js
      html += `<div class="lyric-note">${noteLabel(item.note)}</div>`;
```

`selectChar` 里第 653 行：

```js
  document.getElementById("metaNote").textContent = `时值: ${item.note==="16"?"1/16":(item.note==="8"?"1/8":(item.note==="4"?"1/4":(item.note==="2"?"1/2":"1/1")))}拍`;
```

改成：

```js
  // noteLabel 自带「拍」字，这里不要再拼一个
  document.getElementById("metaNote").textContent = `时值: ${noteLabel(item.note)}`;
```

- [ ] **Step 4: `renderLyrics` 改读 `lyrics`，并加空态**

现在的开头：

```js
function renderLyrics() {
  const grid = document.getElementById("lyricsGrid");
  grid.innerHTML = "";
  LYRICS.forEach((item, idx) => {
```

改成：

```js
function renderLyrics() {
  const grid = document.getElementById("lyricsGrid");
  grid.innerHTML = "";
  if (lyrics.length === 0) {
    // 三种空态（未选唱段 / 该唱段暂无歌词 / 加载失败）共用这一个出口，
    // 具体说哪句由 lyricsEmptyMsg 决定
    grid.innerHTML = `<span class="piece-empty">${lyricsEmptyMsg}</span>`;
    return;
  }
  lyrics.forEach((item, idx) => {
```

再把函数体中剩下的 `LYRICS[idx-1]` 改成 `lyrics[idx-1]`（第 622 行）：

```js
    if (idx > 0 && ["，", "。"].includes(lyrics[idx-1].char)) {
```

**其余整段（`.punct` 判定、`hasAnn`、`item.start.toFixed(1)`）都不要动。**

> `item.start.toFixed(1)` 只在 `pitch !== null` 时执行。库内 142 条里，凡有 `midi` 的必有 `start`（缺 `start` 的 8 条正是缺 `midi` 的标点），所以这条路径不会碰到 null。**这是刻意保留的不变量**，不是漏了判空：为不可能发生的情况加兜底，正是「多余异常捕获」。

- [ ] **Step 5: `selectChar` / `saveAnnotation` 改读 `lyrics`**

`selectChar` 第 646 行：

```js
  const item = LYRICS[idx];
```

改成：

```js
  const item = lyrics[idx];
```

`saveAnnotation` 第 703 行（**容易漏的一处**，全文第 5 个 `LYRICS` 引用）：

```js
  const item = LYRICS[selectedIndex];
```

改成：

```js
  const item = lyrics[selectedIndex];
```

- [ ] **Step 6: 新增 `resetAnnotationPanel`（放在 `selectChar` 之后）**

```js
function resetAnnotationPanel() {
  // 还原成 HTML 里的初始值（bigChar/charInfo/charMeta/annotateControls/depsPanel），
  // 不这么做的话，切唱段后右栏还停在上一个唱段选中那个字的音高、时值上
  selectedIndex = -1;
  selectedTag = null;
  document.getElementById("bigChar").textContent = "—";
  document.getElementById("charInfo").textContent = "点击左侧歌词字进行标注";
  document.getElementById("charMeta").style.display = "none";
  const ctrl = document.getElementById("annotateControls");
  ctrl.style.opacity = "1"; ctrl.style.pointerEvents = "none";
  document.getElementById("depsPanel").classList.remove("show");
  document.querySelectorAll(".type-btn").forEach(b => b.classList.remove("active"));
}
```

- [ ] **Step 7: 改 `switchSegment`**

现在的：

```js
function switchSegment(idx) {
  const s = segments[idx];
  if (!s) return;
  currentSegIdx = idx;
  document.querySelectorAll("#segmentSelector .piece-btn").forEach((b, i) => {
    b.classList.toggle("active", i === idx);
  });
  // 同 switchPiece：不能说「已加载新唱段数据」，歌词网格仍是 mock
  showToast("info", "🎵 已选择唱段", `${segLabel(s)} · 歌词网格待接入（C3 未实现）`);
}
```

改成：

```js
function switchSegment(idx) {
  const s = segments[idx];
  if (!s) return;
  currentSegIdx = idx;
  document.querySelectorAll("#segmentSelector .piece-btn").forEach((b, i) => {
    b.classList.toggle("active", i === idx);
  });
  // 换唱段＝换一整套字。annotations 的 index 是「第几个字」，留着会挂到
  // 新唱段的同序号字上——那不是同一个字
  annotations = [];
  renderAnnotations();
  resetAnnotationPanel();
  // 旧歌词立刻让位，否则会在新数据到达前一直显示上一个唱段的字
  lyrics = [];
  lyricsEmptyMsg = "歌词加载中…";
  renderLyrics();
  // 不 await：高亮与 toast 不依赖歌词结果，不该等它
  fetchLyrics(s.id);
  showToast("info", "🎵 已选择唱段", segLabel(s));
}
```

- [ ] **Step 8: 新增 C3 段（`switchSegment` 之后、`renderLyrics();` 初始化之前）**

```js
// ============================================
// 歌词（C3 GET /api/segments/<id>）
// 标注相关的仍是 mock：saveAnnotation/renderAnnotations 待 C4–C6。
// ============================================

let lyrics = [];                  // 当前唱段的逐字数据（C3 出参 data.lyrics）
let lyricsEmptyMsg = "请选择唱段"; // 网格为空时显示哪句话
let lyricReqToken = 0;            // 竞态守卫，见 fetchLyrics

async function fetchLyrics(segmentId) {
  // 领号必须在 await 之前；await 之后再领就等于没领
  const token = ++lyricReqToken;
  let data;
  try {
    const r = await fetch(`/api/segments/${segmentId}`, { credentials: 'same-origin' });
    const body = await r.json();
    if (!r.ok || body.code !== 0) throw new Error(body.message || String(r.status));
    data = body.data || {};
  } catch (e) {
    // 期间又切过唱段的话，这个失败属于上一个唱段，不该覆盖当前的状态
    if (token !== lyricReqToken) return;
    lyrics = [];
    lyricsEmptyMsg = "歌词加载失败";
    renderLyrics();
    return;
  }

  // 判定必须在 await 之后：快速连点两个唱段时，先发的慢响应可能后到
  if (token !== lyricReqToken) return;

  lyrics = data.lyrics || [];
  // 「这个唱段还没有歌词」是常态（解析产出的新段落 lyrics_json 就是 NULL），
  // 与「加载失败」必须分开说
  lyricsEmptyMsg = lyrics.length === 0 ? "该唱段暂无歌词" : "";
  renderLyrics();
}
```

**末尾的 `renderLyrics(); renderAnnotations(); fetchDemos();` 三行原样保留**，不要重复粘贴。

- [ ] **Step 9: 更新两处过时注释**

第 766 行与第 842 行现在是同一句：

```js
// 歌词网格仍是上面的 LYRICS mock——换歌词要等 C3（/segments/<id>）实现。
```

**两处都删掉**（C3 已实现，这句话成了假话；`LYRICS` 这个常量也已不存在）。它们所在的区块标题（`曲目选择器（C1 …）` / `分段选择器（C2 …）`）保留不动。

两处文本**完全相同**，用 Edit 时必须 `replace_all: true`，否则会因「不唯一」报错：

```
old_string: // 歌词网格仍是上面的 LYRICS mock——换歌词要等 C3（/segments/<id>）实现。
new_string: (留空)
replace_all: true
```

检查残留：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && grep -n 'LYRICS\|EXISTING_ANNS' annotation.html || echo "无残留 ✓"
```

预期：`无残留 ✓`。

- [ ] **Step 10: 验证——静态检查**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
curl -s -b /tmp/t.jar http://127.0.0.1/annotation.html -o /tmp/ann3.html -w 'status=%{http_code}\n'
for k in fetchLyrics lyricReqToken noteLabel resetAnnotationPanel lyricsEmptyMsg; do echo -n "$k: "; grep -c "$k" /tmp/ann3.html; done
grep -n 'fetchLyrics' /tmp/ann3.html
```

预期（`grep -c` 数的是**行数**）：

| 标识符 | 预期 | 出处 |
|---|---|---|
| `fetchLyrics` | **3** | 定义 1 + `switchSegment` 调用 1 + Step 1 留下的注释 1 |
| `noteLabel` | **4** | 定义 1 + `renderLyrics` 1 + `selectChar` 1 + Step 3 的注释 1 |
| `lyricReqToken` | **4** | 声明 1 + 领号 1 + catch 里比对 1 + await 后比对 1 |
| `lyricsEmptyMsg` | **5** | 声明 1 + `renderLyrics` 读 1 + 加载中 1 + 加载失败 1 + 三元赋值 1 |
| `resetAnnotationPanel` | **2** | 定义 1 + `switchSegment` 调用 1 |

用 `grep -n` 逐处确认位置——**数字对但位置不对（比如重复粘贴了一份定义）同样是 bug**。

- [ ] **Step 11: 验证——`/browse` 实测**

后端在跑。`/browse` 的会话在 Task 3 重启后端时被踢掉了，**先重新登录**：打开 `http://127.0.0.1/login.html`，填 `teacher01` / `xiyun@2026`。若已直接进到 `dashboard.html` 就跳过。

逐项确认。**唱段的「第几段」按 `seq` 排序**，界面上的标签是 `第 N 段 · 标题 · N.Ns`——用标签里的**时长**去和基线表对，比用「第几段」可靠：

1. 打开 `http://127.0.0.1/annotation.html` → 默认选中 demo 1 的第 1 段（唯一一段）→ 网格 **2 格**「海」「岛」，时值分别是 `1/2 拍`、`1/4 拍`
   **这是 Task 1 归一的直接证据。若显示成 `1/1 拍`，说明 `noteLabel` 落进了兜底或归一没生效——停下来查，不要放过。**
2. 切到 demo 16（`辕门外三声炮`，**5 段**）→ 第 1 段 → 网格 **66 格**，首字「辕」，时值 `1/8 拍`
3. **标点格子**：在同一个网格里找到「，」格 → 确认它**没有音高行**、点击后 `#bigChar` 仍是 `—`、`#charMeta` 仍是 `display:none`（即根本没挂 `onclick`）。这是 §3.2「缺 `midi` 补显式 null」的端到端证据
4. 点第 5 个字左右 → 右栏出现「音高: xx (Xx)」与「时值: 1/8 拍」
5. 切到 demo 17（`海岛冰轮初转腾`，**3 段**）→ 第 1 段 → 网格 **28 格**，**其中应能看到附点时值**（`1/8 附点拍`、`1/16 附点拍`）
   **这是 `noteLabel` 附点档的唯一端到端验证。** 若全是 `1/16 拍` 而没有「附点」二字，说明 `NOTE_DOT_*` 没被识别、落到了「原样显示」
6. demo 18 的第 1 段 → **14 格**，应能看到 `1/32 附点拍`
7. 切到 demo 16 的第 2 段（`第 2 段 · 辕门外三声炮 · 2.8s`，**6 格**）→ 网格全是字、**没有标点**；且右栏已归零（`#bigChar` 是 `—`、`#charMeta` 隐藏）——这一步验证 `switchSegment` 里的 `resetAnnotationPanel()`
8. **竞态**：同一 tick 内先后点 demo 1 与 demo 16 的**曲目**按钮，等渲染稳定 → 网格应是 **66 格**（属于 demo 16），不是 2 格
9. 控制台无报错

**照着这张表认段**（2026-09-28 实测，`ORDER BY demo_id, seq` —— 三个 demo 的 seq 序都恰好等于 id 序）：

| 界面标签 | segment.id | 网格格数 | 看点 |
|---|---|---|---|
| 曲目 1 第 1 段 · 30.5s | 1 | **2** | 时值 `1/2 拍` / `1/4 拍`（Task 1 的证据） |
| 曲目 16 第 1 段 · 24.7s | 78 | **66** | 首字「辕」；含 **8 个标点格** |
| 曲目 16 第 2 段 · 辕门外三声炮 · 2.8s | 102 | **6** | 无标点；只有 `tip` 没有 `note` → 时值全 `—` |
| 曲目 17 第 1 段 · 44.7s | 79 | **28** | **6 个附点**（`1/8 附点拍`×1 + `1/16 附点拍`×5） |
| 曲目 18 第 1 段 · 38.5s | 80 | **14** | **6 个附点**（`1/32 附点拍`×1 + `1/16 附点拍`×5） |

- [ ] **Step 12: 验证——降级分支**

临时把 `fetchLyrics` 里的 URL：

```js
    const r = await fetch(`/api/segments/${segmentId}`, { credentials: 'same-origin' });
```

改成：

```js
    const r = await fetch(`/api/segments-not-exist/${segmentId}`, { credentials: 'same-origin' });
```

刷新页面，确认：

1. 网格显示「**歌词加载失败**」
2. **没有**弹 toast（唯一的 toast 应仍是 `switchPiece` 默认选曲那条「已选择曲目」）
3. 曲目区 6 个按钮、分段区正常、右栏可用

确认完**改回 `/api/segments/${segmentId}`**，刷新确认网格恢复正常。

- [ ] **Step 13: 验证——空歌词分支（`lyrics: []`）**

用浏览器的 `js` 直接调一次，不必改代码：

```bash
$B js "fetch('/api/segments/99999',{credentials:'same-origin'}).then(r=>r.json()).then(b=>'code='+b.code+' msg='+b.message)"
```

预期 `code=404 msg=唱段不存在`。

空数组那条路径在库里没有现成的行（11 个唱段全有歌词），靠 Task 3 Step 7 的接口级验证覆盖。**不要为此在库里留任何假数据**。

- [ ] **Step 14: 收尾检查**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
.venv/bin/python scripts/check_db.py > /tmp/checkdb3.txt 2>&1; echo "check_db exit=$?"; tail -4 /tmp/checkdb3.txt
echo "--- git ---"; git status --short
git diff annotation.html | grep -c 'segments-not-exist' || echo "无 not-exist 残留 ✓"
.venv/bin/python -c "
from sqlalchemy import text
from app.db import SessionLocal
print('segments 行数（应为 11）:', SessionLocal().execute(text('SELECT count(*) FROM segments')).scalar())
"
```

预期：

- `check_db.py` 只报既有漂移（`demo_versions` + `teacher_demos` 三列），**无新增差异**
- `git status --short` 只有 `annotation.html`
- 无 `segments-not-exist` 残留
- `segments` 行数 **11**

- [ ] **Step 15: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add annotation.html
git commit -m "feat: 标注页歌词网格接上 GET /api/segments/<id>"
```

---

## 收尾

C3 落地后，C1→C2→C3 这条链走通：选曲目 → 选唱段 → 看逐字歌词。

**仍不做**：歌词的断句（只有 seg 78 有标点，其余唱段渲染成一整行——数据现状，`DOC_ISSUES` 第 27.2 节的待确认第 3 条）；标注的增删查（C4–C6）；`saveAnnotation` 仍是把标注塞进本地数组，刷新即失。
