# 标注列表接口（C4 `GET /api/segments/<id>/annotations`）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 C4——返回单个唱段的标注规则列表，并让 `annotation.html` 的标注列表与歌词格子 ✓ 标记第一次读真数据。

**Architecture:** 自下而上四层各一个小改动（repo 查询 → service 口径 → schema 出参模型 → HTTP 路由），再把页面里 `let annotations = []` 这个空数组换成 C4 的真数据；最后把两个本地假增删（`saveAnnotation` / `deleteAnnotation`）改成明确提示未实现——本轮之后标注列表只装真数据。

**Tech Stack:** Python 3.11 / Flask / SQLAlchemy 2.x / PostgreSQL / pydantic v2 / 原生 JS 单页

**依据 spec:** `docs/superpowers/specs/2026-09-29-segment-annotations-api-design.md`

## Global Constraints

- **不新增测试框架。** 本仓库没有 `tests/`、`requirements.txt` 里也没有 pytest。验证一律用**对真接口跑的 curl**、`.venv/bin/python` 与 `/browse` 实测。不要 `pip install pytest`。
- **Python 解释器用 `.venv/bin/python`**，先 `cd /Users/meiyazhao/Documents/lianshu/operaAI`。
- **`/api` 前缀只在 `app/api/__init__.py` 的 `url_prefix` 里写一次**，路由写相对路径。
- **响应一律用 `app/response.py` 的 `ok()`**。
- **权限是教师**：`@login_required` **加** `@teacher_required`，叠放顺序固定、`login_required` 在外层。**这与 C1/C2/C3 只要求 `@login_required` 不同，不要照抄 C3 的装饰器。**
- **不改 `schema.sql` / `app/models/*` / `app-d.py`**，不引 Alembic，不加依赖。
- **只做 C4。** `app/api/demos_segments_annotations.py` 里 C5（`POST /api/annotations`）、C6（`DELETE /api/annotations/<id>`）、C7（`GET /api/annotations/rules`）三个占位路由**原样保留，一个字都不要动**。
- **当前真库基线**（2026-09-29 实测）：
  - `annotations` 表 **0 行**；`seed.sql` 里也没有标注的 INSERT
  - `users`：`teacher01` 的 id 是 **2**（不是 1——id 1 已被删除，序列从 2 起）；`stu001` 是 3
  - `segments` 共 **16 个**：`1, 79, 80, 106, 107, 108, 110–119`
  - **C3 spec 里记的 `78` / `102–105` 已被重跑解析删除，不要再用**（demo 16 被重解析过，旧分段按 `demo_id` 整批替换成了 `110–119`）
  - 本轮验证固定用 **seg 119**：demo 16 的第 10 段，标题「谁料想我五十三岁又管三军」，**12 字**（下标 0–11，首字「谁」、末字「军」）
  - 两个外键都在：`segment_id → segments(id)`、`teacher_id → users(id)`。**临时插行必须用真实存在的 id，编一个会当场撞外键**
- 种子账号 `teacher01` / `stu001`，密码 `xiyun@2026`。
- 注释、commit message 一律中文；标识符英文。

### 临时验证数据：每个任务各插各删

`annotations` 表 0 行，所以真数据路径必须临时插行。**三个任务（1/2/3/4）各自插、各自删，不跨任务留隐藏状态**，每个任务结束时表必须回到 0 行。

**插入**（`RETURNING id` 抓住 id，删除时按 id 删，**不要**按 `segment_id` 一把删——那会连真数据一起删掉）：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
docker exec docker_postgres psql -U xiyun -d xiyun -Atq -c "
INSERT INTO annotations (segment_id, word_index, tag, tolerance, teacher_id) VALUES
  (119, 0,  '拖腔', 30,   2),
  (119, 5,  '滑音', NULL, 2),
  (119, 2,  '换气', 0,    2),
  (119, 2,  '强音', 100,  2),
  (119, 11, '归韵', 60,   2)
RETURNING id;" | tr -d ' ' | paste -sd, - | tee /tmp/c4-ann-ids.txt
```

预期输出形如 `21,22,23,24,25`（5 个自增 id，具体值随序列走）。

**`-Atq` 里的 `q` 不能省**：不带 `q` 时 psql 会把命令标签 `INSERT 0 5` 也打进 stdout，经 `tr -d ' '` 变成 `INSERT05`，id 文件就成了 `49,50,51,52,53,INSERT05`——下面那条 DELETE 会当场报语法错误、一条都删不掉。Task 1 实测踩到过。

**删除 + 确认**：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
docker exec docker_postgres psql -U xiyun -d xiyun -c "DELETE FROM annotations WHERE id IN ($(cat /tmp/c4-ann-ids.txt));"
docker exec docker_postgres psql -U xiyun -d xiyun -At -c "SELECT count(*) FROM annotations;"
```

预期最后一行输出 `0`。**不是 0 就停下来查，不要继续。**

---

## 文件结构

| 文件 | 职责 | 本次改动 |
|---|---|---|
| `app/repositories/annotations_repo.py` | 数据访问 | +`list_by_segment`（保留 `get_annotations_list`） |
| `app/services/library_service.py` | 业务逻辑与口径 | +`segment_annotations`；补 1 个 import |
| `app/schemas/demo.py` | 出参模型 | +`AnnotationOut`；补 `datetime` import |
| `app/api/demos_segments_annotations.py` | HTTP 层 | C4 填实现，路由收紧为 `<int:segment_id>`；补 1 个 import |
| `annotation.html` | 歌词级标注页 | +`TAG_CATEGORY`/`annChar`/`annNote`/`fetchAnnotations`/空态变量；`renderAnnotations`/`renderLyrics`/`switchSegment`/`saveAnnotation`/`deleteAnnotation` 改造 |
| `DOC_ISSUES.md` | 需求文档问题登记 | +第 28 条 |

---

## Task 1: 数据层——按唱段查标注 + 出参模型

**Files:**
- Modify: `app/repositories/annotations_repo.py`
- Modify: `app/schemas/demo.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `annotations_repo.list_by_segment(db: Session, segment_id: int) -> list[Annotation]`
  - `app.schemas.demo.AnnotationOut`（字段 `id: int` / `word_index: int` / `tag: str` / `tolerance: int | None` / `created_at: datetime | None`）

- [ ] **Step 1: 插入临时验证数据**

跑上面「临时验证数据」一节里的**插入**命令。预期输出 5 个 id。

- [ ] **Step 2: 写验证脚本并确认它失败**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python - <<'PY'
from app.db import SessionLocal
from app.repositories import annotations_repo
from app.schemas.demo import AnnotationOut

db = SessionLocal()
rows = annotations_repo.list_by_segment(db, 119)
assert len(rows) == 5, f"预期 5 条，实际 {len(rows)}"

# 排序：word_index 升序，同字按 id 升序
assert [(r.word_index, r.id) for r in rows] == sorted((r.word_index, r.id) for r in rows), \
    f"顺序不对: {[(r.word_index, r.id) for r in rows]}"
assert [r.word_index for r in rows] == [0, 2, 2, 5, 11], [r.word_index for r in rows]

# 出参模型：恰好 5 个键，且 tolerance 的 None 不被吞成 0
out = [AnnotationOut.model_validate(r).model_dump() for r in rows]
for o in out:
    assert set(o) == {"id", "word_index", "tag", "tolerance", "created_at"}, set(o)
assert [o["tolerance"] for o in out] == [30, 0, 100, None, 60], [o["tolerance"] for o in out]

# 按 segment_id 过滤真生效，不是全表返回
assert annotations_repo.list_by_segment(db, 110) == [], "110 不该有标注"
print("OK", len(out), "条")
PY
```

预期：**ImportError**，因为函数还没写。**具体缺哪个符号取决于脚本的执行顺序**：模块导入（`from app.repositories import annotations_repo`）不会暴露函数名，所以最先炸的是下一行的按名导入 `from app.schemas.demo import AnnotationOut`，报 `cannot import name 'AnnotationOut'`。Task 1 实测如此。失败类别（ImportError）不变，红绿判定不受影响。

- [ ] **Step 3: 实现 `list_by_segment`**

在 `app/repositories/annotations_repo.py` **末尾追加**（`get_annotations_list` 一个字都不动）：

```python
def list_by_segment(db: Session, segment_id: int) -> list[Annotation]:
    """按唱段取标注（C4），word_index 升序、同字按 id 升序。

    不与 get_annotations_list 合并：那个是全表取行给看板算总数
    （dashboard_service 在用），本函数按 segment_id 过滤给标注页。
    查询目的不同，合并只会多一个「要不要过滤」的参数分支。

    order_by 里带上 id 是为了**稳定**：同一个字可以挂多个 tag（UNIQUE 约束是
    segment_id + word_index + tag 三列），只按 word_index 排的话这两条谁先谁后
    由 PG 自由决定，同一次查询跑两次可能顺序不同。
    """
    return list(db.scalars(
        select(Annotation)
        .where(Annotation.segment_id == segment_id)
        .order_by(Annotation.word_index, Annotation.id)
    ).all())
```

- [ ] **Step 4: 实现 `AnnotationOut`**

`app/schemas/demo.py` 顶部当前是：

```python
from pydantic import BaseModel, ConfigDict
```

改成：

```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict
```

然后在**文件末尾追加**：

```python
class AnnotationOut(BaseModel):
    """标注列表行（C4 `GET /api/segments/<id>/annotations`）。

    **tolerance / created_at 可空**：DDL 上这两列可空，库里只要有一行空值，
    写成非空就整个接口 500（同 DemoListOut / DemoSegmentOut 的坑）。
    `id` / `word_index` / `tag` 三列在 DDL 上是 NOT NULL，保持非空。

    字段名沿用文档给 C5 的入参名 `word_index`（C5 的说明是「新增标注
    （segment_id, word_index, tag, tolerance）」），不叫 index——出参与将来的
    写入字段名对齐，前端多写一行映射而已。

    **不出 char / category / note**：库里没有这三列。char 由前端从已加载的
    lyrics[word_index] 取（后端按下标去读 lyrics_json 会踩 C3 归一函数的
    丢弃错位）；category 是 CSS 类名、note 是拼出来的显示串，都属于 UI 措辞，
    同 C3 对 note 词表的口径（spec 3.2）。

    **不出 teacher_id**：C4 不按教师隔离，返回该唱段的全部标注（spec 3.4），
    给出 teacher_id 只会让人误以为有归属过滤。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    word_index: int
    tag: str
    tolerance: int | None = None
    created_at: datetime | None = None
```

- [ ] **Step 5: 重跑验证脚本，确认通过**

重跑 Step 2 的同一条命令。

预期输出：`OK 5 条`

- [ ] **Step 6: 删除临时数据并确认表回到 0 行**

跑上面「临时验证数据」一节里的**删除 + 确认**命令。预期最后一行是 `0`。

- [ ] **Step 7: Commit**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add app/repositories/annotations_repo.py app/schemas/demo.py
git commit -m "feat: 新增按唱段查标注与出参模型（C4 数据层）"
```

---

## Task 2: 接口层——service + 路由 + curl 验证

**Files:**
- Modify: `app/services/library_service.py`（补 1 个 import，末尾追加 `segment_annotations`）
- Modify: `app/api/demos_segments_annotations.py`（补 1 个 import，填掉 C4 占位）

**Interfaces:**
- Consumes: Task 1 的 `annotations_repo.list_by_segment` 与 `AnnotationOut`
- Produces:
  - `library_service.segment_annotations(db: Session, segment_id: int) -> list[dict]`
  - `GET /api/segments/<int:segment_id>/annotations` —— 教师可见

- [ ] **Step 1: 插入临时验证数据**

跑「临时验证数据」一节的**插入**命令。

- [ ] **Step 2: 补 `library_service.py` 的 import**

当前：

```python
from app.repositories import library_repo
```

改成：

```python
from app.repositories import annotations_repo, library_repo
```

- [ ] **Step 3: 实现 `segment_annotations`**

在 `app/services/library_service.py` **末尾追加**：

```python
def segment_annotations(db: Session, segment_id: int) -> list[dict]:
    """C4 标注列表。该唱段的全部标注，按 word_index 升序。

    **不按教师隔离**（spec 3.4）：annotations 的 UNIQUE 约束是
    (segment_id, word_index, tag)，**不含 teacher_id**——同一唱段的同一个字、
    同一个 tag 只能存一条，换个教师再标会撞唯一约束。这张表的设计前提就是
    「一个唱段一套全局唯一的规则集」，不是每教师一份。teacher_id 仍照常写入
    （C5 的事），只是不参与过滤。

    唱段不存在抛 404：**必须显式查 segments**，不能拿标注查询的结果反推——
    唱段不存在时查标注同样是空数组，不查 segments 就会把「唱段不存在」错答成
    200 + []，与 C3 的口径打架。

    唱段存在但没有标注回 []，不是 404（同 C2/C3 的「存在但为空」口径）。
    这是当前真库的唯一情况：annotations 表 0 行。

    返回 dict 而不是 ORM 对象：同 demo_list / demo_library_list 的风格，
    api 层直接喂给 pydantic。
    """
    if library_repo.get_segment(db, segment_id) is None:
        raise BusinessError(404, "唱段不存在")
    return [
        {
            "id": a.id,
            "word_index": a.word_index,
            "tag": a.tag,
            "tolerance": a.tolerance,
            "created_at": a.created_at,
        }
        for a in annotations_repo.list_by_segment(db, segment_id)
    ]
```

- [ ] **Step 4: 补 `demos_segments_annotations.py` 的 import**

当前第 7 行：

```python
from app.schemas.demo import DemoListOut, DemoSegmentOut, SegmentDetailOut
```

改成：

```python
from app.schemas.demo import AnnotationOut, DemoListOut, DemoSegmentOut, SegmentDetailOut
```

- [ ] **Step 5: 填掉 C4 占位路由**

当前（文件末尾附近）：

```python
@api_bp.route("/segments/<id>/annotations",methods=["GET"])
@login_required
@teacher_required
def segments_annotations(id):
    return ok(id);
```

改成：

```python
@api_bp.route("/segments/<int:segment_id>/annotations", methods=["GET"])
@login_required
@teacher_required
def segments_annotations(segment_id):
    """C4 标注规则列表。

    `<int:segment_id>` 同 C2/C3：非数字路径在**路由层**就 404，不进视图。

    **权限是教师**（文档 C4 的权限列就是「教师」），与 C1/C2/C3 的「登录」不同：
    2.3 节这一组里 C4–C7 都是教师专属。装饰器叠放顺序固定，login_required 在外层。

    唱段不存在回 404，唱段存在但没标注回 200 + []——「还没标过」是正常状态
    （当前真库 annotations 表 0 行，在没有标注数据时这就是唯一会遇到的情况）。
    """
    rows = library_service.segment_annotations(get_db(), segment_id)
    return ok([AnnotationOut.model_validate(r).model_dump(mode="json") for r in rows])
```

**注意路由参数名从 `<id>` 改成 `<int:segment_id>` 后，视图函数形参也要一起改成 `segment_id`**——Flask 按**名字**传路径参数，对不上会抛 `TypeError`。

**注意不要顺手改下面 C5 / C6 / C7 那三个占位路由**：`POST /api/annotations`、`DELETE /api/annotations/<id>`、`GET /api/annotations/rules` 本轮不做，原样保留。

- [ ] **Step 6: 重启后端并登录**

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

> **重启会把已登录的浏览会话踢掉**：`/browse` 的 daemon 在 Task 3 里要重新登一次。

- [ ] **Step 7: 验证——未登录 401 / 学生 403**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
echo -n "未登录: "; curl -s -o /tmp/c4-a.json -w '%{http_code} ' http://127.0.0.1:8877/api/segments/119/annotations; cat /tmp/c4-a.json; echo
echo -n "学生:   "; curl -s -b /tmp/s.jar -o /tmp/c4-s.json -w '%{http_code} ' http://127.0.0.1:8877/api/segments/119/annotations; cat /tmp/c4-s.json; echo
```

预期：

```
未登录: 401 {"code":401,"message":"未登录","data":null}
学生:   403 {"code":403,"message":"需要教师权限","data":null}
```

**学生的 403 是本接口与 C1/C2/C3 的关键差别，必须实测通过**——若回 200，说明 `@teacher_required` 漏了或顺序错了。

- [ ] **Step 8: 验证——教师取到 5 条与排序**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
curl -s -b /tmp/t.jar http://127.0.0.1:8877/api/segments/119/annotations \
  | .venv/bin/python -c "
import json,sys
d = json.load(sys.stdin)
assert d['code'] == 0, d
rows = d['data']
assert len(rows) == 5, len(rows)
for r in rows:
    assert set(r) == {'id','word_index','tag','tolerance','created_at'}, set(r)
assert [r['word_index'] for r in rows] == [0,2,2,5,11], [r['word_index'] for r in rows]
assert [r['tolerance'] for r in rows] == [30,0,100,None,60], [r['tolerance'] for r in rows]
assert [r['tag'] for r in rows] == ['拖腔','换气','强音','滑音','归韵'], [r['tag'] for r in rows]
print('OK 5 条:', rows[0])
"
```

预期输出 `OK 5 条: {...}` 且断言全过。

`word_index` 为 2 的两条（`换气` id 更小、`强音` id 更大）必须**按 id 升序**出现在 `滑音` 之前——上面 `tag` 断言已经把顺序钉死了。

- [ ] **Step 9: 验证——空结果与 404**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
echo -n "seg 1 空:  "; curl -s -b /tmp/t.jar -w ' [%{http_code}]\n' http://127.0.0.1:8877/api/segments/1/annotations
echo -n "seg 110 空: "; curl -s -b /tmp/t.jar -w ' [%{http_code}]\n' http://127.0.0.1:8877/api/segments/110/annotations
echo -n "不存在:    "; curl -s -b /tmp/t.jar -w ' [%{http_code}]\n' http://127.0.0.1:8877/api/segments/99999/annotations
echo -n "非整数:    "; curl -s -b /tmp/t.jar -w ' [%{http_code}]\n' http://127.0.0.1:8877/api/segments/abc/annotations
```

预期：

```
seg 1 空:  {"code":0,"message":"ok","data":[]} [200]
seg 110 空: {"code":0,"message":"ok","data":[]} [200]
不存在:    {"code":404,"message":"唱段不存在","data":null} [404]
非整数:    [404]
```

`seg 110` 与 `seg 119` 同在 demo 16——它回 `[]` 才证明过滤真按 `segment_id` 生效，不是全表返回。

- [ ] **Step 10: 删除临时数据并确认表回到 0 行**

跑「临时验证数据」一节的**删除 + 确认**命令。预期最后一行是 `0`。

- [ ] **Step 11: Commit**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add app/services/library_service.py app/api/demos_segments_annotations.py
git commit -m "feat: 实现标注列表接口 C4 GET /api/segments/<id>/annotations"
```

---

## Task 3: 前端——标注列表接真数据

**Files:**
- Modify: `annotation.html`（第 538、555-556、602、610、716-732、887-906、908-911 行附近）

**Interfaces:**
- Consumes: Task 2 的 `GET /api/segments/<int:segment_id>/annotations`
- Produces:
  - 模块级 `let annotations`（内部形状 `{id, index, tag, tolerance, createdAt}`）
  - `TAG_CATEGORY` / `annChar(ann)` / `annNote(ann)`
  - `annReqToken` / `annEmptyMsg` / `annEmptyIcon` / `fetchAnnotations(segmentId)`

- [ ] **Step 1: 插入临时验证数据**

跑「临时验证数据」一节的**插入**命令。

- [ ] **Step 2: 改两处过期的「待 C4」注释**

第 538 行：

```js
// 标注列表同理待 C4（/segments/<id>/annotations），初始为空。
```

**整行删掉**——本轮之后它是假话（该行上面那句关于歌词的注释保留）。

第 555-556 行：

```js
// 待 C4：POST/GET/DELETE /api/annotations*。本轮永远是空数组
let annotations = [];
```

改成：

```js
// 当前唱段的标注（C4 出参，已映射成内部形状：word_index→index，见 fetchAnnotations）
let annotations = [];
```

- [ ] **Step 3: 加映射表与两个派生函数**

在第 602 行 `renderLyrics` 里那处 `hasAnn` 之前不好放，**统一放在 `renderAnnotations` 正上方**（即第 716 行之前），插入：

```js
// tag → CSS 类名，与 DOM 上按钮的 data-cat 同源（第 492–497 行）
const TAG_CATEGORY = {
  "滑音":"articulation", "归韵":"articulation", "擞音":"articulation",
  "换气":"breath", "强音":"pitch", "拖腔":"rhythm",
};

function annChar(ann) {
  // 兜底 "?" 而不是隐藏：word_index 越界说明库里的标注指向一个不存在的字，
  // 是数据有问题，要让人看见
  const item = lyrics[ann.index];
  return item ? item.char : "?";
}

function annNote(ann) { return `${annChar(ann)}字${ann.tag}标注`; }
```

`renderLyrics` 里的 `annNote(hasAnn)`（Step 5）会用到这两个函数——函数声明会提升，位置在后方也调得到。`lyrics` 是 `let`（无提升），但 `renderLyrics()` 的首次调用在第 945 行、晚于 `let lyrics` 的初始化，不存在 TDZ 问题。

- [ ] **Step 4: 改造 `renderAnnotations`**

当前（第 716-732 行）整段替换成：

```js
function renderAnnotations() {
  const list = document.getElementById("annotationList");
  document.getElementById("annCount").textContent = `(${annotations.length}条)`;
  if (annotations.length === 0) {
    list.innerHTML = `<div class="empty-state"><div class="empty-icon">${annEmptyIcon}</div>${annEmptyMsg}</div>`;
    return;
  }
  list.innerHTML = annotations.map((ann, i) => {
    // tolerance 在 DDL 上可空，为 null 时不渲染这一格——照着拼会显示「±nullc」
    const tol = (ann.tolerance === null || ann.tolerance === undefined)
      ? "" : `<div class="ann-tol">±${ann.tolerance}c</div>`;
    // tag 认不出来时 TAG_CATEGORY 取不到值，拼出的 tag-undefined 没有对应样式
    // 规则，落回 .ann-tag 的基础外观。不兜底成某个已知类——那是给一个不认识
    // 的 tag 硬安一个语义配色
    const cat = TAG_CATEGORY[ann.tag] || "";
    return `<div class="annotation-item">
      <div class="ann-char">${annChar(ann)}</div>
      <div class="ann-tag tag-${cat}">${ann.tag}</div>
      <div style="color:var(--text-secondary);font-size:11px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${annNote(ann)}</div>
      ${tol}
      <div class="ann-del" onclick="deleteAnnotation(${i})">✕</div>
    </div>`;
  }).join("");
}
```

四处改动：`ann.char` → `annChar(ann)`；`tag-${ann.category}` → `tag-${cat}`；`${ann.note || ""}` → `${annNote(ann)}`；`±${ann.tolerance}c` 改成条件渲染。空态的图标与文案改读两个新变量。

**`map((ann, i) =>` 与 `onclick="deleteAnnotation(${i})"` 这两处本轮原样保留、不要动**——`deleteAnnotation` 要等 Task 4 才改签名，这时若先把调用处改成无参，中间态下点 ✕ 会执行 `splice(undefined, 1)`（`undefined` 当 0 用），把列表第一条删掉。

- [ ] **Step 5: 改 `renderLyrics` 的 ✓ 提示文案**

第 610 行：

```js
      if (hasAnn) html += `<div class="ann-indicator" title="${hasAnn.tag}: ${hasAnn.note}">✓</div>`;
```

改成：

```js
      if (hasAnn) html += `<div class="ann-indicator" title="${annNote(hasAnn)}">✓</div>`;
```

现状读的是 mock 的 `hasAnn.note`，真数据没有这个字段，不改会渲染成「拖腔: undefined」。

第 602 行的 `hasAnn` 判定本身**不用动**——`a.index === idx` 对内部形状仍然成立。

- [ ] **Step 6: 加空态变量与 `fetchAnnotations`**

把第 908-911 行的分节注释：

```js
// ============================================
// 歌词（C3 GET /api/segments/<id>）
// 标注相关的仍是 mock：saveAnnotation/renderAnnotations 待 C4–C6。
// ============================================
```

改成：

```js
// ============================================
// 歌词（C3 GET /api/segments/<id>）
// ============================================
```

然后在第 943 行（`fetchLyrics` 函数结束的 `}`）之后、第 945 行的 `renderLyrics();` 之前，插入：

```js
// ============================================
// 标注（C4 GET /api/segments/<id>/annotations）
// ============================================

let annReqToken = 0;              // 竞态守卫，见 fetchAnnotations
let annEmptyMsg = "暂无标注规则";  // 列表为空时显示哪句话
let annEmptyIcon = "📝";          // 与上面的文案配套的图标

async function fetchAnnotations(segmentId) {
  // 领号必须在 await 之前；await 之后再领就等于没领
  const token = ++annReqToken;
  let rows;
  try {
    const r = await fetch(`/api/segments/${segmentId}/annotations`, { credentials: 'same-origin' });
    const body = await r.json();
    if (!r.ok || body.code !== 0) throw new Error(body.message || String(r.status));
    rows = body.data || [];
  } catch (e) {
    // 期间又切过唱段的话，这个失败属于上一个唱段，不该覆盖当前的状态
    if (token !== annReqToken) return;
    annotations = [];
    annEmptyMsg = "标注加载失败";
    annEmptyIcon = "⚠️";
    renderAnnotations();
    return;
  }

  // 判定必须在 await 之后：快速连点两个唱段时，先发的慢响应可能后到
  if (token !== annReqToken) return;

  // 映射成内部形状，渲染函数就不必知道网络字段名。
  // 空态文案**无条件复位**：否则「先失败、再切到有数据的唱段」会把上一次的
  // 失败文案带过来
  annotations = rows.map(r => ({
    id: r.id, index: r.word_index, tag: r.tag,
    tolerance: r.tolerance, createdAt: r.created_at,
  }));
  annEmptyMsg = "暂无标注规则";
  annEmptyIcon = "📝";
  renderAnnotations();
  // 歌词格子上的 ✓ 由 renderLyrics 画，标注换了要重画一次
  renderLyrics();
}
```

- [ ] **Step 7: `switchSegment` 追调 `fetchAnnotations`**

第 894-905 行当前是：

```js
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
```

改成：

```js
  // 换唱段＝换一整套字。annotations 的 index 是「第几个字」，留着会挂到
  // 新唱段的同序号字上——那不是同一个字
  annotations = [];
  annEmptyMsg = "标注加载中…";
  annEmptyIcon = "📝";
  renderAnnotations();
  resetAnnotationPanel();
  // 旧歌词立刻让位，否则会在新数据到达前一直显示上一个唱段的字
  lyrics = [];
  lyricsEmptyMsg = "歌词加载中…";
  renderLyrics();
  // 不 await：高亮与 toast 不依赖歌词与标注结果，不该等它
  fetchLyrics(s.id);
  fetchAnnotations(s.id);
  showToast("info", "🎵 已选择唱段", segLabel(s));
```

歌词格子上的 ✓ 不需要额外清理：上面 `renderLyrics()` 已经把网格重画成「歌词加载中…」，✓ 随之消失。

- [ ] **Step 8: 用 `/browse` 验证**

**先用 `/browse` 技能登录 `teacher01`**（`http://127.0.0.1:8877/annotation.html`，密码 `xiyun@2026`）——Task 2 Step 6 重启过后端，旧会话已失效。

1. 默认落在 demo 1 → seg 1：标注列表显示 📝「暂无标注规则」，歌词网格无 ✓
2. 切到 **demo 16**（《穆桂英挂帅》· 辕门外三声炮，**10 段**）→ 切到**第 10 段**「谁料想我五十三岁又管三军」：
   - 列表 **5 条**，`annCount` 是 `(5条)`
   - 每条显示 字 + tag 色块 + 「N字X标注」；末列 `±Nc`
   - `tolerance` 为 `NULL` 的那条（`滑音`）**不显示** `±Nc`——不是「±nullc」
3. **歌词格子 ✓**：`word_index` 0 / 2 / 5 / 11 四个格子有 ✓（对应「谁」「想」「十」「军」），hover 的 title 是「谁字拖腔标注」这类，**不是 `undefined`**
4. 刷新页面，列表仍是这 5 条（证明它们来自接口而非内存）
5. **竞态**：快速连点第 9 段和第 10 段 → 最终列表属于**后点**的那个
6. **降级**：临时把 `fetchAnnotations` 里的 URL 改成 `/api/segments-x/${segmentId}/annotations` → 列表显示 ⚠️「标注加载失败」，**歌词网格正常显示**、页面其余部分可用 → **验证完改回，并确认文件里无残留**

- [ ] **Step 9: 删除临时数据并确认表回到 0 行**

跑「临时验证数据」一节的**删除 + 确认**命令。预期最后一行是 `0`。

- [ ] **Step 10: Commit**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add annotation.html
git commit -m "feat: 标注页标注列表接上 GET /api/segments/<id>/annotations"
```

---

## Task 4: 前端——增删改为提示未实现

**Files:**
- Modify: `annotation.html`（`saveAnnotation` 第 692-714 行、`deleteAnnotation` 第 734-737 行）

**Interfaces:**
- Consumes: Task 3 的 `annotations` 内部形状与 `renderAnnotations`
- Produces: `saveAnnotation()` / `deleteAnnotation()` 改为只提示、不改状态

**为什么单独一个任务**：这是用户明确拍板的行为决定（本轮不做本地假增删），与 Task 3 的读路径是两件事，评审时可以单独否决。

- [ ] **Step 1: 插入临时验证数据**

跑「临时验证数据」一节的**插入**命令。**这一步是必需的**——列表为空时点不到 ✕，Step 4 的第 3 条验不了。

- [ ] **Step 2: 改 `saveAnnotation`**

当前（第 692-714 行）整段替换成：

```js
function saveAnnotation() {
  if (selectedIndex < 0 || !selectedTag) { alert("请先选择一个字和标注类型"); return; }
  // C5 未实现：不往列表里 push。本地条目刷新即消失，却与真数据长得一模一样，
  // 是「看起来像真数据」——列表只装真数据
  showToast("info", "写入接口未实现", "C5（POST /api/annotations）尚未实现，本条标注未落库");
}
```

一并删掉的：`item` / `tolerance` / `existingIdx` / `newAnn` / `impactCount` 几个局部变量（都不再使用）、绿色「✓ 已添加」按钮动画（原第 711-713 行，本轮之后它是假话）、`RULE_IMPACT` 那句「该技法将影响 N 个唱句」（描述的是一个没发生的动作）。

前置校验保留：它是真前置条件，且选中状态驱动着右栏面板。`#toleranceSlider` 的值本轮不再被读取，但滑块与它的数值显示照常工作。

- [ ] **Step 3: 改 `deleteAnnotation`**

当前（第 734-737 行）整段替换成：

```js
function deleteAnnotation() {
  // C6 未实现：不从列表里移除。本地 splice 掉的条目刷新就回来了，
  // 而点了 ✕ 却什么都没发生是更清楚的说法
  showToast("info", "删除接口未实现", "C6（DELETE /api/annotations/<id>）尚未实现，标注仍在库中");
}
```

**同一提交里还要把调用处一起改掉**（两处必须同时改，只改一处会出现 `splice(undefined, 1)` 删掉列表第一条）：

1. `renderAnnotations` 里 `annotations.map((ann, i) => {` 的 `i` 不再被使用 → 改成 `annotations.map((ann) => {`
2. 同一函数里 `<div class="ann-del" onclick="deleteAnnotation(${i})">✕</div>` → `<div class="ann-del" onclick="deleteAnnotation()">✕</div>`

改完这两处后 grep 一遍确认没有残留：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
grep -n "deleteAnnotation" annotation.html
```

预期只有两行：`function deleteAnnotation() {` 与 `onclick="deleteAnnotation()"`。

- [ ] **Step 4: 用 `/browse` 验证**

1. 切到有标注的唱段（demo 16 → 第 10 段，5 条）
2. 点「添加标注」→ 先只点字不选类型 → 应弹 `alert("请先选择一个字和标注类型")`；再选一个类型后点 → **列表条数不变**（仍是 `(5条)`），弹 ℹ️「写入接口未实现」toast，按钮**没有**绿色「✓ 已添加」动画
3. 点任意一条的 ✕ → **该条仍在列表里**，弹 ℹ️「删除接口未实现」toast
4. 刷新页面 → 列表仍是 5 条（证明第 3 步确实没删库）

- [ ] **Step 5: 删除临时数据并确认表回到 0 行**

跑「临时验证数据」一节的**删除 + 确认**命令。预期最后一行是 `0`。

- [ ] **Step 6: Commit**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add annotation.html
git commit -m "refactor: 标注页增删不再做本地假动作，改为提示接口未实现"
```

---

## Task 5: 文档登记与收尾

**Files:**
- Modify: `DOC_ISSUES.md`（在「## 待核实」之前插入第 28 条）

**Interfaces:**
- Consumes: Task 1–4 的全部结论
- Produces: 无代码接口

- [ ] **Step 1: 写 `DOC_ISSUES.md` 第 28 条**

在 `## 待核实` 之前插入：

````markdown
## 28. 标注列表（C4）只有一句话描述，响应契约全未定义；另：`CLAUDE.md` 的数据库时区记载与实测不符

**涉及**：《5-接口清单》2.3 节 C4 / `app/api/demos_segments_annotations.py` / `app/services/library_service.py` / `annotation.html`

### 28.1 C4 的响应契约全未定义

C4 在文档里的**全部**内容是「`GET /api/segments/<id>/annotations` ｜ 教师 ｜ 标注规则列表」一行。与第 26（C1）、27（C2/C3）条同源。本次采用的口径：

| 未定义项 | 本次采用的口径 |
|---|---|
| 响应体字段 | `id` / `word_index` / `tag` / `tolerance` / `created_at` |
| 字段名 | 用 `word_index`，**沿用文档给 C5 的入参名**（C5 的说明写的是「新增标注（segment_id, word_index, tag, tolerance）」），不叫 `index` |
| `char` / `category` / `note` | **不由后端返回**。`char` 由前端从已加载的 `lyrics[word_index]` 取——后端按下标去读 `lyrics_json` 会踩 C3 归一函数的丢弃错位（见 27.2）；`category` 是 CSS 类名、`note` 是拼出来的显示串，都是 UI 措辞，同第 26 条对 `elo_difficulty` 的处置 |
| 是否按教师隔离 | **不隔离**，返回该唱段全部标注。依据是表自己的约束：`UNIQUE(segment_id, word_index, tag)` **不含 `teacher_id`**，同一唱段的同一个字同一个 tag 只能存一条——这张表的设计前提就是「一个唱段一套全局唯一的规则集」，不是每教师一份 |
| 排序 | `word_index, id` 升序（带 `id` 是为了稳定性） |
| 唱段不存在 | `404`（**显式查 `segments`**，不能拿标注查询的结果反推，否则会错答成 `200 + []`） |
| 唱段存在但无标注 | `200` + `[]` |
| 分页 | 无 |

**数据现状**：`annotations` 表实测 **0 行**，`seed.sql` 里也没有标注的 INSERT。所以本接口在真实数据上恒定返回 `[]`，标注页恒定走空态；真数据路径是靠临时插行验的。

**待文档方确认**：

1. C4 出参是否够用？C7（规则列表管理，功能 9.6）是否需要更多字段（如教师名、创建时间）？
2. 不按教师隔离是否与预期一致？若预期「各教师管各自的标注」，需要**同时**改 `UNIQUE` 约束（去掉或加入 `teacher_id`），否则会出现「标不了（撞唯一约束）又看不见（被过滤掉）」的死角。
3. `created_at` 是否有用？当前前端一处都没读它。

### 28.2 `CLAUDE.md` 的数据库时区记载与实测不符

`CLAUDE.md`「数据库接入层」一节写「**容器内 PostgreSQL 的时区是 `Etc/UTC`**，`NOW()` 返回 UTC，比北京时间早整 8 小时。所有 `created_at`/`recorded_at`/`submitted_at` 等 `DEFAULT NOW()` 的列存进去的都是 UTC 时间」。**实测不是这样**：

```
$ docker exec docker_postgres psql -U xiyun -d xiyun -c "SHOW timezone;"
   TimeZone
---------------
 Asia/Shanghai

$ docker exec docker_postgres psql -U xiyun -d xiyun -c "SELECT now(), now() AT TIME ZONE 'Asia/Shanghai';"
            db_now             |          asia_now
-------------------------------+----------------------------
 2026-09-29 08:58:49.787046+08 | 2026-09-29 08:58:49.787046
```

两者**相等**，即 `NOW()` 落库的**就是北京时间**。`app/repositories/practice_records_repo.py:53` 的注释记的是对的，`CLAUDE.md` 那句是错的。

**影响**：所有 `DEFAULT NOW()` 的列一律**不做** `AT TIME ZONE` 换算。照着 `CLAUDE.md` 换算会把时间整体推后 8 小时，跨零点的那几条会串到第二天（`practice_records_repo.py` 的注释已经指出过这个后果）。C4 的 `created_at` 因此直接返回原值。

**待确认**：这条是 `CLAUDE.md`（本仓库自己的文件）与实测不符，不是《…》文档的问题——是否要顺手把 `CLAUDE.md` 那句改掉？本次只登记、不改，因为改它会影响其他接口对时区的既有假设，需要单独过一遍。
````

- [ ] **Step 2: 跑建库一致性闸门**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python scripts/check_db.py
```

预期：**无新增差异**（本轮不改模型与 `schema.sql`）。脚本可能会报既有的 `demo_versions` + `teacher_demos` 三列漂移——那是本轮之前就有的，与本次改动无关。**若报出 `annotations` 相关的差异，停下来查。**

- [ ] **Step 3: 终检——表回到 0 行**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
docker exec docker_postgres psql -U xiyun -d xiyun -At -c "SELECT count(*) FROM annotations;"
```

预期输出 `0`。**不是 0 就说明前四个任务里有一步没清理干净，按 `/tmp/c4-ann-ids.txt` 里的 id 删掉。**

- [ ] **Step 4: 终检——注释里没有残留的「待 C4」**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
grep -n "待 C4\|mock：saveAnnotation\|annotations 待 C4" annotation.html
```

预期：**无输出**。有输出说明 Task 3 Step 2/6 的注释没改干净。

- [ ] **Step 5: Commit**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add DOC_ISSUES.md
git commit -m "docs: 登记 C4 响应契约未定义与 CLAUDE.md 时区记载有误"
```

---

## 收尾

C4 落地后，`annotation.html` 的曲目 → 唱段 → 歌词 → 标注四层都是真数据。

**仍不做**：

- **C5（`POST /api/annotations`）、C6（`DELETE /api/annotations/<id>`）、C7（`GET /api/annotations/rules`）**——三个占位路由原样保留。页面上的「添加标注」与 ✕ 只弹「接口未实现」，这是诚实反映它们没实现
- **`TECHNIQUE_DEPS` / `RULE_IMPACT` / `renderDeps()`** 仍是 mock——「技法依赖图谱」面板与本轮无关
- **歌词断句**（只有少数唱段有标点）——数据现状，见 `DOC_ISSUES` 第 27.2 节待确认第 3 条

**一个已知的潜伏问题**（本轮规避了，但值得记着）：`annotations.word_index` 指的是 `lyrics_json` 的**库内下标**，而 C3 的 `_normalize_lyrics` 会**丢弃**非法条目（非对象、`word` 非字符串）。只要有一条被丢弃，出参 `lyrics[]` 的下标就与库内错位，`word_index` 就会指向另一个字——前端拿它取 `char`、标 ✓ 全会错。当前库内 142 条歌词全部合法，所以不会命中。若将来真出现脏条目，症状是「标注挂到了别的字上」，届时要么让 `_normalize_lyrics` 保留占位条目，要么让 C3 出参带上库内下标。
