# 分段列表接口（C2 `GET /api/demos/<id>/segments`）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 C2——返回某曲目下的唱段列表，并让 `annotation.html` 在曲目选择器下面多一层分段选择器。

**Architecture:** service 层加一个 3 行函数（判曲目存在 → 404 → 复用既有的 `list_segments`），schema 层加一个四字段模型，api 层填掉占位路由并把 `<id>` 收紧成 `<int:demo_id>`。前端在 C1 那套 `demos` / `switchPiece` 下面加一层 `segments` / `switchSegment`，并加请求序号守卫防竞态。

**Tech Stack:** Python 3.11 / Flask / SQLAlchemy 2.x / PostgreSQL / pydantic v2 / 原生 JS 单页

**依据 spec:** `docs/superpowers/specs/2026-09-28-demos-segments-api-design.md`

## Global Constraints

- **不新增测试框架。** 本仓库没有任何测试文件、没有 `tests/` 目录、`requirements.txt` 里也没有 pytest。验证一律用**对真接口跑的 curl** 与 `/browse` 实测，命令与预期输出写在步骤里。不要 `pip install pytest`。
- **Python 解释器用 `.venv/bin/python`**，先 `cd` 到项目根目录。PATH 上的 `python`/`pip` 是 pyenv 的 3.12（见记忆 `pip-mirror-and-interpreter-gotchas`）。
- **`/api` 前缀只在 `app/api/__init__.py` 的 `url_prefix` 里写一次**，路由写相对路径。
- **响应一律用 `app/response.py` 的 `ok()`**；`data` 直接装数组。
- **`seq` / `title` / `duration` 在 pydantic 模型里必须写成 `| None = None`**——`segments` 这三列在 DDL 上均可空（`schema.sql:66-73`）。`id` 是主键，非空。
- **不返回 `lyrics_json`，也不返回 `demo_id`**（spec 3.1）。
- **权限只 `@login_required`**，不能加 `@teacher_required`（学生端陪练要选唱段）。
- **不改 `schema.sql` / `seed.sql` / `app/models/*` / `app-d.py`**，不引入新依赖。
- **只做 C2。** `app/api/demos_segments_annotations.py` 里 C3–C7 那 5 个占位路由（`/segments/<id>`、`/segments/<id>/annotations`、`/annotations`、`/annotations/<id>`、`/annotations/rules`）**原样保留**。
- **前端 `LYRICS` / `EXISTING_ANNS` / `renderLyrics()` / `renderAnnotations()` / `saveAnnotation()` 一律不动**，也不动底部登录用户条那段 IIFE。
- **当前真库基线**（2026-09-28 实测，`segments` 全表 11 行）：

  | demo_id | 段数 | segment.id | seq | title | duration |
  |---|---|---|---|---|---|
  | 1 | 1 | 1 | 1 | 第一段 | 30.5 |
  | 15 | **0** | — | — | — | — |
  | 16 | 5 | 78 / 102 / 103 / 104 / 105 | 1..5 | 第一段 / 辕门外三声炮 / 如同雷震 / 天波府走出来 / 保国臣 | 24.7 / 2.8 / 2.4 / 2.8 / 2.2 |
  | 17 | 3 | 79 / 106 / 107 | 1..3 | 第一段 / 海岛冰轮 / 初转腾 | 44.7 / 3.5 / 3.0 |
  | 18 | 2 | 80 / 108 | 1..2 | 第一段 / 看大王在帐中 | 38.5 / 4.0 |
  | 19 | **0** | — | — | — | — |

  写断言照这张表来。**如果实测条数对不上，先停下来核对，不要改断言去迁就结果**。
- 种子账号：`teacher01`（教师）/ `stu001`（学生），密码 `xiyun@2026`。
- 注释、commit message 一律中文；标识符英文。

---

## 文件结构

| 文件 | 职责 | 本次改动 |
|---|---|---|
| `app/services/library_service.py` | 示范库的业务逻辑与口径 | +`demo_segments` |
| `app/schemas/demo.py` | C1/C2 的出参模型 | +`DemoSegmentOut` |
| `app/api/demos_segments_annotations.py` | 曲目/分段/标注的 HTTP 层 | `demos_segments()` 填实现，路由收紧为 `<int:demo_id>`；+1 import |
| `DOC_ISSUES.md` | 需求文档问题登记 | +第 27 条；第 20 条补注 |
| `annotation.html` | 歌词级标注页 | 分段选择器容器 + 2 条 CSS + `fetchSegments`/`segLabel`/`switchSegment` + 改 `switchPiece` 与 `fetchDemos` 的失败分支 |

---

## Task 1: service 与 schema

**Files:**
- Modify: `app/services/library_service.py`（文件末尾追加 `demo_segments`）
- Modify: `app/schemas/demo.py`（文件末尾追加 `DemoSegmentOut`）

**Interfaces:**
- Consumes: 无
- Produces（Task 2 依赖）:
  - `library_service.demo_segments(db: Session, demo_id: int) -> list[Segment]` —— 按 `seq` 升序；曲目不存在抛 `BusinessError(404, "曲目不存在")`；曲目存在但无分段返回 `[]`
  - `app.schemas.demo.DemoSegmentOut` —— 字段 `id / seq / title / duration`

- [ ] **Step 1: 在 `library_service.py` 末尾追加 `demo_segments`**

**不需要新增 import**：`BusinessError`（第 9 行）、`Segment`（第 11 行）、`library_repo`（第 12 行）顶部都已经引入。

```python
def demo_segments(db: Session, demo_id: int) -> list[Segment]:
    """某曲目的分段列表（按 seq 升序）。曲目不存在抛 404。供 C2。

    不复用同一文件里的 demo_library_get：它一次返回 (demo, segments)，其 docstring
    解释了为什么要一起取（避免「demo 存在但分段刚好被重跑清空」的不一致组合）——
    C2 只要分段，那个理由不成立；而且它的 404 文案是「示范曲目不存在」，会把示范库
    管理的措辞泄漏给陪练/标注场景（同 C1 不返回 status 的理由，spec 4.1）。

    「曲目存在但没有分段」返回空列表、不抛 404：那是正常状态，不是错误（spec 3.3）。
    库里 demo 15/19 就是这个状态。
    """
    if library_repo.get_demo(db, demo_id) is None:
        raise BusinessError(404, "曲目不存在")
    return library_repo.list_segments(db, demo_id)
```

- [ ] **Step 2: 在 `app/schemas/demo.py` 末尾追加 `DemoSegmentOut`**

```python
class DemoSegmentOut(BaseModel):
    """分段列表行（C2 `GET /api/demos/<id>/segments`）。

    **seq / title / duration 一律可空**：segments 表这三列在 DDL 上均可空
    （见 schema.sql），写成非空的话库里只要有一行空值，整个列表就 500。

    `id` 必须有——前端拿它去调 C3 `/segments/<id>` 与 C4 标注，不给 id 这个接口
    就没有下游（spec 3.1）。**不返回 lyrics_json**：文档把逐字数据划给 C3，
    而且库里那列目前有三种互不兼容的形状（DOC_ISSUES 第 27 条），未统一前
    返回什么都是错的。也不返回 demo_id——它是入参，调用方本来就知道。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    seq: int | None = None
    title: str | None = None
    duration: float | None = None
```

（`ConfigDict` 与 `BaseModel` 在该文件顶部已 import，不需要再加。）

- [ ] **Step 3: 验证——对真库跑一遍，核对分段数与顺序**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python -c "
from app.db import SessionLocal
from app.services.library_service import demo_segments
s = SessionLocal()
for did in (1, 15, 16, 17, 18, 19):
    segs = demo_segments(s, did)
    print(did, len(segs), [(x.id, x.seq, x.title, x.duration) for x in segs])
"
```

预期输出（**逐行核对**）：

```
1 1 [(1, 1, '第一段', 30.5)]
15 0 []
16 5 [(78, 1, '第一段', 24.7), (102, 2, '辕门外三声炮', 2.8), (103, 3, '如同雷震', 2.4), (104, 4, '天波府走出来', 2.8), (105, 5, '保国臣', 2.2)]
17 3 [(79, 1, '第一段', 44.7), (106, 2, '海岛冰轮', 3.5), (107, 3, '初转腾', 3.0)]
18 2 [(80, 1, '第一段', 38.5), (108, 2, '看大王在帐中', 4.0)]
19 0 []
```

**两个必须盯住的点**：

1. **15 与 19 是 `0 []`，不是报错**——若抛异常，说明空列表被误当成 404
2. **每行的 `seq` 是 1..N 升序**——若不是升序，说明 `list_segments` 的 `order_by` 没生效

- [ ] **Step 4: 验证——不存在的曲目抛 404**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python -c "
from app.db import SessionLocal
from app.common.errors import BusinessError
from app.services.library_service import demo_segments
try:
    demo_segments(SessionLocal(), 99999)
    print('失败：没有抛异常')
except BusinessError as e:
    print('OK code=', e.code, 'msg=', e.message)
"
```

预期：`OK code= 404 msg= 曲目不存在`。

若报 `AttributeError`（`e.code` 不存在），用 `.venv/bin/python -c "from app.common.errors import BusinessError; import inspect; print(inspect.getsource(BusinessError))"` 看一下该类的实际属性名，按实际名改上面那行。

- [ ] **Step 5: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add app/services/library_service.py app/schemas/demo.py
git commit -m "feat: 新增分段列表查询与出参模型（C2 数据层）"
```

---

## Task 2: 填路由 + 文档登记

**Files:**
- Modify: `app/api/demos_segments_annotations.py:25-28`（填 `demos_segments()`，补 1 个 import）
- Modify: `DOC_ISSUES.md`（在 `## 26.` 之后、`## 待核实` 之前插入第 27 条；另在第 20 条的「当前处理」段补一句）

**Interfaces:**
- Consumes: Task 1 的 `library_service.demo_segments(db, demo_id)` 与 `DemoSegmentOut`
- Produces: `GET /api/demos/<int:demo_id>/segments` —— 登录可见

- [ ] **Step 1: 补 import**

`app/api/demos_segments_annotations.py` 顶部当前是：

```python
from app.schemas.demo import DemoListOut
```

改成：

```python
from app.schemas.demo import DemoListOut, DemoSegmentOut
```

- [ ] **Step 2: 填掉 `demos_segments()`**

当前的占位实现（第 25–28 行）：

```python
@api_bp.route("/demos/<id>/segments",methods=["GET"])
@login_required
def demos_segments(id):
    return ok(id)
```

改成：

```python
@api_bp.route("/demos/<int:demo_id>/segments", methods=["GET"])
@login_required
def demos_segments(demo_id):
    """C2 分段列表。

    `<int:demo_id>` 与 /api/demo/library/<int:demo_id> 同理：非数字路径在**路由层**
    就 404，不进视图，畸形输入也就没有变成 500 的机会。

    权限只要求登录：学生端陪练要选唱段，加 @teacher_required 会堵死学生端。
    曲目不存在回 404；曲目存在但没有分段回 200 + []（spec 3.3）。
    """
    rows = library_service.demo_segments(get_db(), demo_id)
    return ok([DemoSegmentOut.model_validate(r).model_dump(mode="json") for r in rows])
```

**注意路由参数名从 `<id>` 改成 `<int:demo_id>` 后，视图函数的形参也要一起改成 `demo_id`**——Flask 把路径参数按**名字**传给视图，名字对不上会抛 `TypeError`。

**其余 5 个占位路由（C3–C7）原样保留，一个字符都不要动。**

- [ ] **Step 3: 确认后端在跑**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8877/login.html
```

若输出不是 `200`，起一个（**注意 `app-d.py` 没有开 debug 自动重载，改了代码必须重启**）：

```bash
pkill -f 'python app-d.py'; sleep 1
cd /Users/meiyazhao/Documents/lianshu/operaAI && (.venv/bin/python app-d.py > /tmp/xiyun-api.log 2>&1 &)
for i in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:8877/login.html && break; sleep 0.5; done
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8877/login.html
```

- [ ] **Step 4: 登录两个账号**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
curl -s -c /tmp/t.jar -X POST -H 'Content-Type: application/json' \
  -d '{"username":"teacher01","password":"xiyun@2026"}' http://127.0.0.1:8877/api/auth/login > /dev/null
curl -s -c /tmp/s.jar -X POST -H 'Content-Type: application/json' \
  -d '{"username":"stu001","password":"xiyun@2026"}' http://127.0.0.1:8877/api/auth/login > /dev/null
echo "登录完成"
```

- [ ] **Step 5: 验证——未登录 401**

```bash
curl -s -o /tmp/seg-anon.json -w 'status=%{http_code}\n' http://127.0.0.1:8877/api/demos/16/segments
cat /tmp/seg-anon.json; echo
```

预期：`status=401`，body 为 `{"code":401,"message":"未登录","data":null}`。

- [ ] **Step 6: 验证——教师账号，逐曲目核对**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
for id in 1 15 16 17 18 19; do
  echo "--- demo $id ---"
  curl -s -b /tmp/t.jar "http://127.0.0.1:8877/api/demos/$id/segments" | .venv/bin/python -c "
import json,sys
b=json.load(sys.stdin)
d=b.get('data')
print('code=',b['code'],'len=',len(d) if d is not None else None)
for s in (d or []): print('   ', s)
"
done
```

预期：与 Global Constraints 的基线表逐行一致。**重点核对**：

- demo 1 → `len= 1`，一条 `{'id': 1, 'seq': 1, 'title': '第一段', 'duration': 30.5}`
- demo 16 → `len= 5`，`id` 为 `78,102,103,104,105`，`seq` 为 `1..5`
- demo 17 → `len= 3`；demo 18 → `len= 2`
- **demo 15 / 19 → `code= 0` 且 `len= 0`**（`data` 是 `[]` 而不是 `null`，也不是 404）
- 每条**只有** `id / seq / title / duration` 四个键，**没有** `lyrics_json`、**没有** `demo_id`

- [ ] **Step 7: 验证——学生账号能访问，且 404 / 路由层行为正确**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
echo -n "学生 demo16: "
curl -s -b /tmp/s.jar http://127.0.0.1:8877/api/demos/16/segments | .venv/bin/python -c "import json,sys; b=json.load(sys.stdin); print('code=',b['code'],'len=',len(b['data'] or []))"
echo -n "不存在的曲目 99999: "
curl -s -b /tmp/t.jar -o /tmp/seg404.json -w '%{http_code} ' http://127.0.0.1:8877/api/demos/99999/segments; cat /tmp/seg404.json; echo
echo -n "非数字路径 abc: "
curl -s -b /tmp/t.jar -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8877/api/demos/abc/segments
```

预期：

- 学生 → `code= 0 len= 5`。**若回 403，说明误加了 `@teacher_required`**，回 Step 2 去掉
- 99999 → `404` + `{"code":404,"message":"曲目不存在","data":null}`
- `abc` → `404`。这一条的 body 是 **Flask 的默认 404 页面（HTML）**，不是统一信封——路由没匹配上，压根没进本项目的错误处理器。这是 Flask 行为，不是缺陷，spec 3.3 已写明

- [ ] **Step 8: 验证——经 nginx（80 端口）再打一遍**

```bash
curl -s -b /tmp/t.jar http://127.0.0.1/api/demos/16/segments | head -c 200; echo
```

预期：与 Step 6 同样的 JSON。

- [ ] **Step 9: 在 `DOC_ISSUES.md` 插入第 27 条**

在 `## 26. …` 那一节结束后、`## 待核实` 之前插入：

```markdown
## 27. 分段列表（C2）只有一句话描述；`lyrics_json` 存在三种互不兼容的形状

**涉及**：《5-接口清单》2.3 节 C2、C3 / `app/api/demos_segments_annotations.py` / `app/services/library_service.py` / `annotation.html`

### 27.1 C2 的响应契约全未定义

C2 在文档里的**全部**内容是「`GET /api/demos/<id>/segments` ｜ 登录 ｜ 分段列表」一行。本次采用的口径：

| 未定义项 | 本次采用的口径 |
|---|---|
| 响应体字段 | `id` / `seq` / `title` / `duration` |
| 是否返回 `id` | **返回**。文档只说「分段列表」，但不给 `id` 前端就无法调 C3 `/segments/<id>` 与 C4 标注，这个接口没有下游 |
| 是否返回 `lyrics_json` | **不返回**。文档把逐字数据划给 C3（「段落详情，含 lyrics_json」） |
| 排序 | `segments.seq` 升序 |
| 曲目不存在 | `404`（路由用 `<int:demo_id>`，非数字路径也在路由层 404） |
| 曲目存在但无分段 | `200` + `[]`，不是 404——「还没解析出唱段」是正常状态 |
| 分页 | 无。一个曲目的分段是个位数到几十条 |

与第 26（C1）、22、24、25 条同源：接口清单只给一句「说明」，没有响应契约。

### 27.2 `lyrics_json` 的三种形状（做 C3 前必须先定）

`segments.lyrics_json` 在库里**不是 NULL**——全表 11 行都有内容。第 20 条写的「该列恒 NULL」指的是**解析链路不写它**（`app/repositories/library_repo.py` 的 `replace_segments` 确实传 `None`），但 `seed.sql` 与后来人工录入的行都有值。

现有三种形状，字段名与取值都对不上：

| 形状 | 样例 | 出现在 |
|---|---|---|
| A 带 `note` | `{"word":"辕","midi":64,"start":0,"end":0.234,"note":"NOTE_8"}` | seg 78/79/80 |
| B 带 `tip` | `{"word":"辕","midi":64,"start":0,"end":0.4,"tip":"起音稳，气息下沉…"}` | seg 102–108 |
| 种子 | `{"word":"海","midi":57,"start":0,"end":1.2,"note":"half","tip":"起音轻…"}` | seg 1 |

而前端 `annotation.html` 的 `LYRICS` mock 要的是**第四套**：`{char, pitch, note, start, duration}`，`note` 取值 `"8"/"4"/"2"/"16"/"1"`。也就是说 C3 落地时要同时处理：

1. 字段名映射：`word`→`char`、`midi`→`pitch`、`end - start`→`duration`
2. `note` 的**三套词表**：`NOTE_8` / `half` / `"8"` 要归一（`NOTE_DOT_16` 这种附点音符在 mock 里没有对应档）
3. 标点：mock 里有 `{char:"，", pitch:null, ...}` 这样的整行空值，库里没有标点条目
4. `tip` 是 shape A 没有的，前端 `renderLyrics` 目前也不渲染它

**待文档方确认**：

1. `lyrics_json` 的权威形状是哪一种？A / B / 种子三选一，还是重定一个新 schema？`note` 用 `NOTE_8` 还是 `"8"` 还是 `half`？
2. 标点符号要不要进 `lyrics_json`（影响前端的分句逻辑，`renderLyrics` 现在靠 `["，","。"].includes(...)` 换行）？
3. `tip`（唱前提示，功能 2.4）与 `note` 能否共存？
4. 第 20 条那个更根本的问题仍未解：**解析链路给不出「字」**，人工录入是唯一路径。库里现有的歌词全是人工/种子数据。

另见第 19、20、26 条。

---

## 待核实
```

**注意**：`## 待核实` 那一行已经在文件里，插入内容要以它结尾——不要把原来的 `## 待核实` 变成两份。

- [ ] **Step 10: 给第 20 条补一句现状**

第 20 条末尾「**当前处理**：已落地——解析**不写 `lyrics_json`**（该列恒 NULL，与 `seed.sql` 之外的现状一致）…」里的「该列恒 NULL」与当前库不符。把那一句改成：

```
**当前处理**：已落地——解析**不写 `lyrics_json`**，解析只落分段与时长，同时回填 `audio_files.duration_sec`。**注意「该列恒 NULL」只对解析产出的行成立**：`seed.sql` 的 seg 1 与后来人工录入的 seg 78/79/80/102–108 都有内容，且形状互不兼容（见第 27 条）。
```

- [ ] **Step 11: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add app/api/demos_segments_annotations.py DOC_ISSUES.md
git commit -m "feat: 实现分段列表接口 C2 GET /api/demos/<id>/segments"
```

---

## Task 3: `annotation.html` 加分段选择器

**Files:**
- Modify: `annotation.html:191-207`（曲目选择器 CSS 段，追加两条规则）
- Modify: `annotation.html:440-444`（`#pieceSelector` 之后加分段容器）
- Modify: `annotation.html:759-826`（改注释、加分段逻辑、改 `switchPiece`、改 `fetchDemos` 失败分支）

**Interfaces:**
- Consumes: Task 2 的 `GET /api/demos/<int:demo_id>/segments`
- Produces: 无（页面终态）

- [ ] **Step 1: 追加分段选择器的 CSS**

在 `annotation.html` 的 `/* ===== 曲目选择 ===== */` 段里，`.piece-empty{...}` 那一行**之后**、`/* ===== 歌词网格 ===== */` 之前追加：

```css
/* 分段比曲目低一层：字号小一点、上边距收紧，免得两行看着像同级 */
#segmentSelector{margin-top:-6px}
#segmentSelector .piece-btn{font-size:12px;padding:6px 12px}
```

- [ ] **Step 2: 加分段容器**

`annotation.html` 当前是：

```html
  <!-- 曲目按钮由页末脚本从 GET /api/demos 渲染 -->
  <div class="piece-selector" id="pieceSelector"></div>
```

改成：

```html
  <!-- 曲目按钮由页末脚本从 GET /api/demos 渲染 -->
  <div class="piece-selector" id="pieceSelector"></div>
  <!-- 唱段按钮由页末脚本从 GET /api/demos/<id>/segments 渲染 -->
  <div class="piece-selector" id="segmentSelector"></div>
```

- [ ] **Step 3: 追加分段逻辑，并改 `switchPiece` / `fetchDemos` 的失败分支**

**(a)** 把这段注释：

```js
// ============================================
// 曲目选择器（C1 GET /api/demos）
// 歌词网格仍是上面的 LYRICS mock——换歌词要等 C2/C3
// （/demos/<id>/segments、/segments/<id>）实现，本轮只把曲目列表接真。
// ============================================
```

改成：

```js
// ============================================
// 曲目选择器（C1 GET /api/demos）
// 歌词网格仍是上面的 LYRICS mock——换歌词要等 C3（/segments/<id>）实现。
// ============================================
```

**(b)** 在 `fetchDemos` 的 catch 分支里，把：

```js
    // 不弹 toast、不打断页面：歌词网格仍是 mock，曲目列表拿不到
    // 不该让整个标注页不可用
    box.innerHTML = '<span class="piece-empty">曲目列表加载失败</span>';
    return;
```

改成：

```js
    // 不弹 toast、不打断页面：歌词网格仍是 mock，曲目列表拿不到
    // 不该让整个标注页不可用
    box.innerHTML = '<span class="piece-empty">曲目列表加载失败</span>';
    // 分段区一并清空：曲目都没了，留着上一次的分段只会误导
    document.getElementById("segmentSelector").innerHTML = "";
    return;
```

> **与 spec 5.7 的一处偏差（有意）**：spec 那句末尾写的是「分段区显示同一句话即可」，与它前半句的「一并清空」自相矛盾——两行都写「加载失败」是重复噪音，而分段失败的真正原因（曲目列表都没拿到）在上方已经说清了。**取「清空」**，spec 那句末半句作废。

**(c)** 把当前的 `switchPiece`：

```js
function switchPiece(idx) {
  const d = demos[idx];
  if (!d) return;
  currentDemoIdx = idx;
  document.querySelectorAll(".piece-btn").forEach((b, i) => {
    b.classList.toggle("active", i === idx);
  });
  // 文案不能说「已加载新曲目数据」——歌词网格仍是 mock，那会让人以为
  // 网格跟着换了
  showToast("info", "🎵 已选择曲目", `${d.title} · 歌词数据待接入（C2/C3 未实现）`);
}
```

改成：

```js
function switchPiece(idx) {
  const d = demos[idx];
  if (!d) return;
  currentDemoIdx = idx;
  // 必须限定在 #pieceSelector 内：加了分段选择器之后，裸的 ".piece-btn"
  // 会把分段按钮也算进来，下标当场错位
  document.querySelectorAll("#pieceSelector .piece-btn").forEach((b, i) => {
    b.classList.toggle("active", i === idx);
  });
  // 换曲目的瞬间旧分段必须立刻消失，否则会在新分段到达前一直显示上一个曲目的分段
  document.getElementById("segmentSelector").innerHTML = "";
  // 不 await：高亮与 toast 不依赖分段结果，不该等它
  fetchSegments(d.id);
  // 文案不能说「已加载新曲目数据」——歌词网格仍是 mock，那会让人以为
  // 网格跟着换了
  showToast("info", "🎵 已选择曲目", `${d.title} · 歌词网格待接入（C3 未实现）`);
}

// ============================================
// 分段选择器（C2 GET /api/demos/<id>/segments）
// 歌词网格仍是上面的 LYRICS mock——换歌词要等 C3（/segments/<id>）实现。
// ============================================

let segments = [];       // 当前曲目的分段（按 seq 升序）
let currentSegIdx = -1;  // 渲染顺序的下标，不是 segments.id
let segReqToken = 0;     // 竞态守卫，见 fetchSegments

async function fetchSegments(demoId) {
  const box = document.getElementById("segmentSelector");
  // 领号必须在 await 之前；await 之后再领就等于没领
  const token = ++segReqToken;
  let rows;
  try {
    const r = await fetch(`/api/demos/${demoId}/segments`, { credentials: 'same-origin' });
    const body = await r.json();
    if (!r.ok || body.code !== 0) throw new Error(body.message || String(r.status));
    rows = body.data || [];
  } catch (e) {
    // 期间又切过曲目的话，这个失败属于上一个曲目，不该覆盖当前的状态
    if (token !== segReqToken) return;
    box.innerHTML = '<span class="piece-empty">分段加载失败</span>';
    return;
  }

  // 判定必须在 await 之后：快速连点两个曲目时，先发的慢响应可能后到，
  // 不能让它把后发的正确结果覆盖掉（分段会显示成上一个曲目的）
  if (token !== segReqToken) return;

  if (rows.length === 0) {
    box.innerHTML = '<span class="piece-empty">该曲目暂无分段</span>';
    return;
  }

  segments = rows;
  currentSegIdx = -1;
  box.innerHTML = "";
  rows.forEach((s, i) => {
    const btn = document.createElement("button");
    btn.className = "piece-btn";
    btn.textContent = segLabel(s);
    btn.onclick = () => switchSegment(i);
    box.appendChild(btn);
  });

  switchSegment(0);
}

function segLabel(s) {
  // seq / title / duration 三列在 DDL 上均可空，缺哪个少显示哪个，
  // 不要拼出「第 null 段 · nulls」这种
  const parts = [];
  if (s.seq !== null && s.seq !== undefined) parts.push(`第 ${s.seq} 段`);
  if (s.title) parts.push(s.title);
  if (typeof s.duration === 'number') parts.push(`${s.duration.toFixed(1)}s`);
  return parts.join(" · ") || `片段 ${s.id}`;
}

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

**注意**：末尾的 `renderLyrics(); renderAnnotations(); fetchDemos();` 三行**原样保留**，不要重复粘贴。

- [ ] **Step 4: 验证——静态检查**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
curl -s -b /tmp/t.jar http://127.0.0.1/annotation.html -o /tmp/ann2.html -w 'status=%{http_code}\n'
echo -n "segmentSelector: "; grep -c 'segmentSelector' /tmp/ann2.html
echo -n "fetchSegments: ";   grep -c 'fetchSegments' /tmp/ann2.html
echo -n "switchSegment: ";   grep -c 'switchSegment' /tmp/ann2.html
```

预期：`status=200`；`segmentSelector` = **7**（CSS 2 条 + HTML 容器 1 + `fetchSegments` 里 getElementById 1 + `fetchDemos` catch 里 1 + `switchPiece` 里 1 + `switchSegment` 里 querySelectorAll 1）；`fetchSegments` = **2**（定义 1 + `switchPiece` 里调用 1）；`switchSegment` = **2**（定义 1 + `onclick` 里 1）。

数目对不上不要紧，**关键是都大于 0 且没有明显的重复粘贴**。用 `grep -n` 看一眼每处的位置是否合理。

- [ ] **Step 5: 验证——`/browse` 实测**

后端在跑、`/tmp/t.jar` 的会话已登录。用 `/browse` 技能打开 `http://127.0.0.1/annotation.html`，逐项确认：

1. 曲目区 6 个按钮，分段区渲染出**当前选中曲目**的分段。默认选中的曲目是 id 1（`贵妃醉酒·选段 (1段)`），所以分段区应有 **1** 个按钮「**第 1 段 · 第一段 · 30.5s**」，且是 active
2. 点 id 16（`《穆桂英挂帅》· 辕门外三声炮 (5段)`）→ 分段区变成 **5** 个：`第 1 段 · 第一段 · 24.7s` / `第 2 段 · 辕门外三声炮 · 2.8s` / `第 3 段 · 如同雷震 · 2.4s` / `第 4 段 · 天波府走出来 · 2.8s` / `第 5 段 · 保国臣 · 2.2s`，默认选中第 1 段
3. **曲目区的高亮没有错位**——切到 id 16 后，曲目区只有第 3 个按钮（index 2）是 active，分段按钮**不会**被误标 active。这一条是在测 Step 3 把 `.piece-btn` 限定成 `#pieceSelector .piece-btn` 的修复
4. 点第 3 段 → 高亮切过去，toast 为「🎵 已选择唱段 / 第 3 段 · 如同雷震 · 2.4s · 歌词网格待接入（C3 未实现）」
5. **歌词网格无变化**（首字仍是「辕」）——预期行为
6. 切到 id 1 → 分段区回到 1 个按钮
7. 停在后端可用的状态，`git status` 确认没有临时文件

- [ ] **Step 6: 验证——降级分支**

临时把 `fetchSegments` 里的 URL：

```js
    const r = await fetch(`/api/demos/${demoId}/segments`, { credentials: 'same-origin' });
```

改成：

```js
    const r = await fetch(`/api/demos-not-exist/${demoId}/segments`, { credentials: 'same-origin' });
```

刷新页面，确认：

1. 分段区显示「**分段加载失败**」
2. **没有**弹 toast
3. 曲目区正常（6 个按钮）、歌词网格正常、标注面板可用

确认完**改回 `/api/demos/${demoId}/segments`**，刷新确认恢复正常。

- [ ] **Step 7: 验证——竞态守卫**

在 `/browse` 里连续快速切换两个曲目，确认最终渲染的分段属于**最后点的那个**：

```js
// 先后点 id 1（1 段）与 id 16（5 段），不等中间结果
document.querySelectorAll("#pieceSelector .piece-btn")[0].click();
document.querySelectorAll("#pieceSelector .piece-btn")[2].click();
```

等待渲染完成后读分段区：按钮数应为 **5**（属于 id 16），而不是 1。若出现 1，说明竞态守卫没生效，回 Step 3 检查 `token !== segReqToken` 的判定位置。

- [ ] **Step 8: 收尾检查**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
.venv/bin/python scripts/check_db.py; echo "exit=$?"
git status --short
git diff annotation.html | grep -n "demos-not-exist" || echo "无 not-exist 残留 ✓"
```

预期：

- `check_db.py` 只报既有漂移（`demo_versions` 表 + `teacher_demos` 三列，见记忆 `check-db-pre-existing-drift`），**没有新增差异**
- `git status --short` 只有 `annotation.html` 一个改动
- 无 `demos-not-exist` 残留

- [ ] **Step 9: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add annotation.html
git commit -m "feat: 标注页新增唱段选择器，接上 GET /api/demos/<id>/segments"
```

---

## 收尾

三个 Task 完成后，C2 落地。**歌词网格仍是 mock**——这是 spec 明确的范围，不是遗留缺陷；接真要等 C3，且要先解掉 `DOC_ISSUES.md` 第 27.2 节那四种形状的归一问题（那是产品决策，不是实现细节）。
