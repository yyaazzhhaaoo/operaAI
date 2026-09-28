# 曲目列表接口（C1 `GET /api/demos`）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `GET /api/demos` 从占位（回空）换成返回库中全部曲目及各自分段数的真实查询，再把 `annotation.html` 的曲目选择器接到它上面。

**Architecture:** 沿用 `demo_library` 那套 api → service → repo 分层。repo 用一条 `outerjoin + group_by` 的 SQL 同时取回曲目与分段数（避免 N+1，也避免 `join` 丢掉没有分段的曲目）；service 摊平 `audio.duration_sec`；api 层只校验、组装响应。前端只动 `annotation.html` 的曲目选择器一块，歌词网格仍是 mock。

**Tech Stack:** Python 3.11 / Flask / SQLAlchemy 2.x（`select()` 2.0 风格）/ PostgreSQL / pydantic v2 / 原生 JS 单页

**依据 spec:** `docs/superpowers/specs/2026-09-28-demos-list-api-design.md`

## Global Constraints

- **不新增测试框架。** 本仓库当前**没有任何测试文件**（`find . -name "test_*.py"` 为空、无 `tests/` 目录、无 pytest 依赖），spec 第 6 节已明确本次不建。每个 Task 的验证一律用**对真库/真接口跑的 python 或 curl 片段**，命令与预期输出都写在步骤里——不要 `pip install pytest`，不要新建 `tests/`。
- **Python 解释器一律用 `.venv/bin/python`**，且**必须先 `cd` 到项目根目录**。PATH 上的 `python`/`pip` 是 pyenv 的 3.12，不是本项目的 venv（见记忆 `pip-mirror-and-interpreter-gotchas`）。
- **后端当前没在跑。** 实测 `http://127.0.0.1:8877/login.html` 连接被拒、`http://127.0.0.1/` 回 502（nginx 在，上游不在）。Task 2 与 Task 3 需要先起后端，命令写在步骤里。
- **`/api` 前缀只在 `app/api/__init__.py` 的 `url_prefix` 里写一次。** 路由一律写相对路径（`/demos`），不要在 `@api_bp.route("/api/demos")` 里拼前缀。
- **响应一律用 `app/response.py` 的 `ok()`**，形态 `{"code":0,"message":"ok","data":...}`；`data` 直接装数据本身（数组就装数组，不再外包一层）。
- **`role` / `banshi` / `duration` / `elo_difficulty` 在 pydantic 模型里必须写成 `| None = None`。** `teacher_demos` 与 `audio_files` 这几列在 DDL 上均可空，库里只要有一行空值，写成非空就整片 500（`app/schemas/demo_library.py` 的注释记着上一版正是栽在这个错上）。
- **`elo_difficulty` 不做后端兜底。** 库里有未标定的列默认值 `1000`，如实返回 `1000.0`，不要改成 `null`、不要夹到 1.0（spec 3.2、`DOC_ISSUES.md` 第 19 条）。
- **不改 `schema.sql` / `seed.sql` / `app/models/*` / `app-d.py`**——本次没有建表建列，也没有引入新依赖。
- **只做 C1。** `app/api/demos_segments_annotations.py` 里 C2–C7 那 6 个占位路由**原样保留**，不要顺手实现。
- **不改 `annotation.html` 的 `LYRICS` / `EXISTING_ANNS` / `renderLyrics()` / `renderAnnotations()` / `saveAnnotation()`**，也不动底部登录用户条那段 IIFE。
- **当前真库基线**（2026-09-28 实测，`teacher_demos` 全表 6 行）：

  | id | title | role | banshi | audio_id | audio.duration_sec | elo_difficulty | 分段数 |
  |---|---|---|---|---|---|---|---|
  | 1 | 贵妃醉酒·选段 | 旦 | 四平调 | NULL | — | 1000.0 | 1 |
  | 15 | 01_xipi_1931 | 青衣 | 西皮流水 | 74 | 182.8049375 | 1000.0 | 0 |
  | 16 | 《穆桂英挂帅》· 辕门外三声炮 | 青衣 | 西皮流水 | 75 | 24.7 | 0.72 | 5 |
  | 17 | 《贵妃醉酒》· 海岛冰轮初转腾 | 青衣 | 四平调 | 76 | 44.7 | 0.85 | 3 |
  | 18 | 《霸王别姬》· 看大王在帐中 | 青衣 | 南梆子 | 77 | 38.5 | 0.78 | 2 |
  | 19 | 《红娘》· 叫张生隐藏在棋盘之下 | 花旦 | 西皮流水 | 78 | 28.3 | 0.68 | 0 |

  所有验证断言都按这张表来。**如果实际跑出来条数不是 6，先停下来核对，不要改断言去迁就结果**。
- **排序是 `id` 升序**，所以返回顺序是 `1, 15, 16, 17, 18, 19`（不是上面表格的书写顺序）。
- 种子账号：`teacher01`（教师）/ `stu001`（学生），初始密码均为 `xiyun@2026`。
- 注释、commit message 一律中文；标识符英文（用户全局约定）。

---

## 文件结构

| 文件 | 职责 | 本次改动 |
|---|---|---|
| `app/repositories/library_repo.py` | `teacher_demos` / `segments` 的 SQL 封装 | +1 函数 `get_demo_list`，+1 个 import（`func`） |
| `app/services/library_service.py` | 示范库的业务逻辑与口径 | +1 函数 `demo_list` |
| `app/schemas/demo.py` | **新建**，C1 的出参模型 | `DemoListOut` |
| `app/api/demos_segments_annotations.py` | 曲目/分段/标注的 HTTP 层 | `demos()` 填实现，+3 个 import；其余 6 个占位路由不动 |
| `DOC_ISSUES.md` | 需求文档问题登记 | 新增第 26 条 |
| `annotation.html` | 歌词级标注页 | 曲目选择器容器 + `fetchDemos()` + 重写 `switchPiece()` + 2 条 CSS |

---

## Task 1: 查询层与出参模型（repo + service + schema）

**Files:**
- Modify: `app/repositories/library_repo.py`（顶部 import 加 `func`；文件末尾追加 `get_demo_list`）
- Modify: `app/services/library_service.py`（文件末尾追加 `demo_list`；**不需要新增 import**，`library_repo` 已引入）
- Create: `app/schemas/demo.py`

**Interfaces:**
- Consumes: 无
- Produces（Task 2 依赖这三个）:
  - `library_repo.get_demo_list(db: Session) -> list[tuple[TeacherDemo, int]]` —— 全部曲目 + 各自分段数，按 `teacher_demos.id` 升序；无分段的曲目也在结果里，其分段数为 `0`
  - `library_service.demo_list(db: Session) -> list[dict]` —— 每项键为 `id / title / role / banshi / duration / elo_difficulty / segment_count`
  - `app.schemas.demo.DemoListOut` —— pydantic 模型，字段同上

- [ ] **Step 1: 在 `library_repo.py` 顶部 import 里补 `func`**

当前第 7 行是：

```python
from sqlalchemy import delete, select
```

改成：

```python
from sqlalchemy import delete, func, select
```

- [ ] **Step 2: 在 `library_repo.py` 末尾追加查询函数**

```python
def get_demo_list(db: Session) -> list[tuple[TeacherDemo, int]]:
    """全部曲目 + 各自的分段数，按 id 升序。供 C1 `GET /api/demos`。

    outerjoin 而非 join：没解析出分段的曲目也要出现在列表里（spec 3.3），
    join 会把它们整条丢掉。

    计数写 count(Segment.id) 而非 count(*)：outerjoin 未命中时 segments 侧
    全是 NULL，count(*) 会数成 1，count(Segment.id) 才是 0。

    一条 SQL 查完，不做 N+1。注意这与 demo_library_list 的取舍不同——那边逐行
    查一次 redis（状态在 redis 里），这里没有那个约束。

    返回 (TeacherDemo, 分段数) 二元组而不是 ORM 上挂个属性：分段数不是模型上的列，
    往模型上塞临时属性会让「哪些字段来自库、哪些是算出来的」变得看不出来。

    duration 不在这里取——它挂在 audio_files 上，由 service 层经 demo.audio
    关系惰性加载（逐行一次查询，曲目量级是几十条，够用；真到几百条再改 joinedload）。
    """
    return list(db.execute(
        select(TeacherDemo, func.count(Segment.id))
        .outerjoin(Segment, Segment.demo_id == TeacherDemo.id)
        .group_by(TeacherDemo.id)
        .order_by(TeacherDemo.id)
    ).all())
```

- [ ] **Step 3: 在 `library_service.py` 末尾追加 `demo_list`**

```python
def demo_list(db: Session) -> list[dict]:
    """C1 曲目列表（陪练选曲 + 作业布置用）。

    duration 取自 audio_files.duration_sec（经 demo.audio 惰性加载）——teacher_demos
    自己没有时长列。曲目无音频、或音频未回填时长时为 None。

    elo_difficulty 如实返回，**不做 0–1 兜底**：库里有未标定的列默认值 1000，
    那是「数据没标定」不是「取不到值」，后端悄悄改成 None 或夹到 1.0 会让调用方
    分不清两者（spec 3.2、DOC_ISSUES 第 19 条）。判定留给前端。

    不过滤 segment_count = 0 的曲目（spec 3.3）：标注页要置灰展示「还没解析」、
    陪练选曲要直接跳过，两个场景诉求不同，接口保持中立。

    返回 dict 而不是 ORM 对象：已经把分段数与 audio 摊平进来了，再让 api 层去
    ORM 上拼一遍等于把同一件事写两处（与 demo_library_list 同风格）。
    """
    return [
        {
            "id": demo.id,
            "title": demo.title,
            "role": demo.role,
            "banshi": demo.banshi,
            "duration": demo.audio.duration_sec if demo.audio else None,
            "elo_difficulty": demo.elo_difficulty,
            "segment_count": segment_count,
        }
        for demo, segment_count in library_repo.get_demo_list(db)
    ]
```

- [ ] **Step 4: 新建 `app/schemas/demo.py`**

```python
# -*- coding: utf-8 -*-
"""曲目列表接口（C1 `GET /api/demos`）的出参模型。

**role / banshi / duration / elo_difficulty 一律可空**：teacher_demos 与
audio_files 里这几列在 DDL 上都可空（见 schema.sql）。写成非空的话，库里只要
有一行空值，整个列表就 500——与 app/schemas/demo_library.py 同一个坑。

与 DemoLibraryListOut 的差别只有两点：不含 status（那是解析进度，属于示范库
管理场景，泄漏给陪练/作业只会让它们平白依赖 redis），多一个 segment_count
（调用方要据此判断「这条能不能用」）。
"""

from pydantic import BaseModel, ConfigDict


class DemoListOut(BaseModel):
    """曲目列表行。segment_count 无分段时是 0，不是 None。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    role: str | None = None
    banshi: str | None = None
    duration: float | None = None
    elo_difficulty: float | None = None
    segment_count: int
```

- [ ] **Step 5: 验证——对真库跑一遍，核对 6 行的分段数与时长**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python -c "
from app.db import SessionLocal
from app.services.library_service import demo_list
for r in demo_list(SessionLocal()):
    print(r['id'], '|', r['title'], '|', r['segment_count'], '|', r['duration'], '|', r['elo_difficulty'])
"
```

预期输出（顺序必须是 id 升序）：

```
1 | 贵妃醉酒·选段 | 1 | None | 1000.0
15 | 01_xipi_1931 | 0 | 182.8049375 | 1000.0
16 | 《穆桂英挂帅》· 辕门外三声炮 | 5 | 24.7 | 0.72
17 | 《贵妃醉酒》· 海岛冰轮初转腾 | 3 | 44.7 | 0.85
18 | 《霸王别姬》· 看大王在帐中 | 2 | 38.5 | 0.78
19 | 《红娘》· 叫张生隐藏在棋盘之下 | 0 | 28.3 | 0.68
```

**三个必须盯住的点**：

1. **id 15 与 19 的分段数是 `0` 而不是 `1`**——若出现 `1`，说明计数写成了 `count(*)`，回到 Step 2 改
2. **id 15 与 19 出现在结果里**——若少了它们，说明 `outerjoin` 写成了 `join`
3. **id 1 的 duration 是 `None`**（它的 `audio_id` 是 NULL），不是 `0`

- [ ] **Step 6: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add app/repositories/library_repo.py app/services/library_service.py app/schemas/demo.py
git commit -m "feat: 新增曲目列表查询与出参模型（C1 数据层）"
```

---

## Task 2: 路由填实现 + 文档问题登记

**Files:**
- Modify: `app/api/demos_segments_annotations.py:8-11`（填 `demos()`，补 import）
- Modify: `DOC_ISSUES.md`（在 `## 25.` 那一节之后、`## 待核实` 之前插入第 26 条）

**Interfaces:**
- Consumes: Task 1 的 `library_service.demo_list(db)` 与 `app.schemas.demo.DemoListOut`
- Produces: `GET /api/demos` —— 登录可见，返回 `{"code":0,"message":"ok","data":[DemoListOut,...]}`

- [ ] **Step 1: 填充 `demos()` 并补齐 import**

把 `app/api/demos_segments_annotations.py` 顶部的 import 段：

```python
from flask import request

from app.api import api_bp
from app.common.decorators import login_required, teacher_required
from app.response import ok
```

改成：

```python
from flask import request

from app.api import api_bp
from app.common.decorators import login_required, teacher_required
from app.db import get_db
from app.response import ok
from app.schemas.demo import DemoListOut
from app.services import library_service
```

再把现有的 `demos()`：

```python
@api_bp.route("/demos",methods=["GET"])
@login_required
def demos():
    return ok();
```

改成：

```python
@api_bp.route("/demos", methods=["GET"])
@login_required
def demos():
    """C1 曲目列表（陪练选曲 + 作业布置用）。

    权限只要求登录（文档 C1 的权限列写的也是「登录」）：本接口要服务学生端的
    「陪练选曲」，加 @teacher_required 会当场堵死学生端。注意这与
    /api/demo/library/list（教师专属）不是同一个场景。

    不过滤 segment_count = 0 的曲目，由调用方自己判断（spec 3.3）。
    """
    rows = library_service.demo_list(get_db())
    return ok([DemoListOut.model_validate(r).model_dump(mode="json") for r in rows])
```

**其余 6 个占位路由（C2–C7）原样保留，一个字符都不要动。**

- [ ] **Step 2: 起后端**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python app-d.py > /tmp/xiyun-api.log 2>&1 &
for i in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:8877/login.html && break; sleep 0.5; done
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8877/login.html
```

预期：最后一行输出 `200`。若一直是 `000`，看 `/tmp/xiyun-api.log` 的报错。

- [ ] **Step 3: 验证——未登录必须 401**

```bash
curl -s -o /tmp/demos-anon.json -w '%{http_code}\n' http://127.0.0.1:8877/api/demos
cat /tmp/demos-anon.json
```

预期：状态码 `401`，body 为 `{"code":401,"message":"未登录","data":null}`。

- [ ] **Step 4: 验证——教师账号拿到 6 条，逐字段核对**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
curl -s -c /tmp/t.jar -X POST -H 'Content-Type: application/json' \
  -d '{"username":"teacher01","password":"xiyun@2026"}' \
  http://127.0.0.1:8877/api/auth/login
curl -s -b /tmp/t.jar http://127.0.0.1:8877/api/demos | .venv/bin/python -m json.tool
```

预期：`code` 为 `0`，`data` 恰好 **6** 项，顺序为 id `1, 15, 16, 17, 18, 19`，内容与 Global Constraints 的基线表一致。逐条核对：

| 检查点 | 期望 |
|---|---|
| `data` 长度 | `6` |
| id 1 | `duration` 为 `null`、`elo_difficulty` 为 `1000.0`、`segment_count` 为 `1` |
| id 15 | `segment_count` 为 `0`、`duration` 为 `182.8049375` |
| id 16 | `segment_count` 为 `5`、`duration` 为 `24.7`、`elo_difficulty` 为 `0.72` |
| 每条都有 `id/title/role/banshi/duration/elo_difficulty/segment_count` 七个键 | 是 |
| 任何一条出现 `status` 或 `created_at` | **失败**（spec 3.1 明确不返回） |

- [ ] **Step 5: 验证——学生账号也能拿到完整列表**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
curl -s -c /tmp/s.jar -X POST -H 'Content-Type: application/json' \
  -d '{"username":"stu001","password":"xiyun@2026"}' \
  http://127.0.0.1:8877/api/auth/login
curl -s -b /tmp/s.jar http://127.0.0.1:8877/api/demos | .venv/bin/python -c "
import json,sys
b=json.load(sys.stdin)
print('code=',b['code'],'len=',len(b['data'] or []))
"
```

预期：`code= 0 len= 6`。**若回 403，说明误加了 `@teacher_required`**，回到 Step 1 去掉。

- [ ] **Step 6: 验证——经 nginx（80 端口）再打一遍**

页面走的是 nginx 代理，不是直连 8877：

```bash
curl -s -b /tmp/t.jar http://127.0.0.1/api/demos | head -c 200; echo
```

预期：与 Step 4 同样的 JSON（nginx 的 `/api` 代理生效）。这一步同时验证了 Task 3 里前端同源相对路径能走通。

- [ ] **Step 7: 在 `DOC_ISSUES.md` 插入第 26 条**

在 `## 25. …` 那一节结束后、`## 待核实` 之前插入（保持与前面各条一致的格式）：

```markdown
## 26. 曲目列表（C1）只有一句话描述，响应体字段/排序/分页全部未定义

**涉及**：《5-接口清单》2.3 节 C1 / `app/api/demos_segments_annotations.py` / `app/services/library_service.py`

**问题**：C1 在文档里的**全部**内容是「`GET /api/demos` ｜ 登录 ｜ 曲目列表（陪练选曲 + 作业布置用）」一行，以下**一项都没有规定**：

| 未定义项 | 本次采用的口径 |
|---|---|
| 响应体字段 | `id` / `title` / `role` / `banshi` / `duration` / `elo_difficulty` / `segment_count` |
| `duration` 从哪来 | `audio_files.duration_sec`（经 `teacher_demos.audio_id`）——`teacher_demos` 自己没有时长列 |
| 是否返回解析状态 | **不返回**。`status` 是示范库管理（`/api/demo/library/list`）的概念，泄漏给陪练/作业只会让这两个场景平白依赖 redis |
| 无分段的曲目是否过滤 | **不过滤**，全部返回，由调用方按 `segment_count` 判断。标注页要置灰展示、陪练选曲要跳过，两个场景诉求不同 |
| 排序 | `teacher_demos.id` 升序（稳定、可预期） |
| 分页 | 无。曲目是剧目级量级（真实使用几十条） |

与第 22（G5 推荐）、24（G6 过程指标）、25（G7 作业进度）条同源：**接口清单的表格只给了一句「说明」，没有响应契约**。

**待文档方确认**：

1. 字段是否够用？后续 C2/C3（分段列表、段落详情）若也需要 `role`/`banshi`，是否会要求 C1 之外的入口。
2. 是否需要按行当/板式筛选、按难度排序（当前前端只能拿到全量再自己筛）。
3. `elo_difficulty` 的量纲仍未定（第 19 条：库里是 1000 分制默认值，前端按 0–1 用）。本接口如实返回原值、不做兜底，判定在调用方。

另见第 19、22 条。
```

- [ ] **Step 8: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add app/api/demos_segments_annotations.py DOC_ISSUES.md
git commit -m "feat: 实现曲目列表接口 C1 GET /api/demos"
```

---

## Task 3: `annotation.html` 接上曲目选择器

**Files:**
- Modify: `annotation.html:191-205`（曲目选择器 CSS，追加两条规则）
- Modify: `annotation.html:440-444`（3 个写死的 button → 空容器）
- Modify: `annotation.html:758-766`（重写 `switchPiece`，新增 `fetchDemos`）

**Interfaces:**
- Consumes: Task 2 的 `GET /api/demos`（同源相对路径 `/api/demos`，需带 Cookie）
- Produces: 无（页面终态）

- [ ] **Step 1: 给曲目选择器补两条 CSS**

在 `annotation.html` 的 `/* ===== 曲目选择 ===== */` 段里，`.piece-btn.active{...}` 规则**之后**、`/* ===== 歌词网格 ===== */` 之前追加：

```css
.piece-btn:disabled{opacity:0.45;cursor:not-allowed}
.piece-btn:disabled:hover{border-color:var(--border-light);color:var(--text-secondary)}
.piece-empty{font-size:13px;color:var(--text-muted);padding:8px 0}
```

（`.piece-btn:disabled:hover` 是为了盖掉上面 `.piece-btn:hover` 的高亮，否则鼠标划过禁用按钮仍会变色、看起来像可点。）

- [ ] **Step 2: 把写死的 3 个 button 换成空容器**

`annotation.html` 当前是：

```html
  <div class="piece-selector">
    <button class="piece-btn active" onclick="switchPiece(0)">《穆桂英挂帅》· 辕门外三声炮</button>
    <button class="piece-btn" onclick="switchPiece(1)">《贵妃醉酒》· 海岛冰轮初转腾</button>
    <button class="piece-btn" onclick="switchPiece(2)">《霸王别姬》· 看大王在帐中</button>
  </div>
```

改成：

```html
  <!-- 曲目按钮由页末脚本从 GET /api/demos 渲染 -->
  <div class="piece-selector" id="pieceSelector"></div>
```

- [ ] **Step 3: 重写 `switchPiece` 并新增 `fetchDemos`**

把 `annotation.html` 当前的：

```js
function switchPiece(idx) {
  document.querySelectorAll(".piece-btn").forEach((b, i) => {
    b.classList.toggle("active", i === idx);
  });
  showToast("info", "🎵 切换曲目", "已加载新曲目数据（模拟）");
}

renderLyrics();
renderAnnotations();
```

整个替换成：

```js
// ============================================
// 曲目选择器（C1 GET /api/demos）
// 歌词网格仍是上面的 LYRICS mock——换歌词要等 C2/C3
// （/demos/<id>/segments、/segments/<id>）实现，本轮只把曲目列表接真。
// ============================================

let demos = [];          // /api/demos 的原样结果（已按 id 升序）
let currentDemoIdx = -1; // 渲染顺序的下标，不是 demo_id；-1 = 未选中

async function fetchDemos() {
  const box = document.getElementById("pieceSelector");
  let rows;
  try {
    // 必须用同源相对路径：写成 location.host + ':8877' 那样的跨源地址时，
    // fetch 默认不带 Cookie，后端 login_required 只会看到空 session 并回 401
    // （与 pitch_comparison.html、demo_library.html 同一个坑）
    const r = await fetch('/api/demos', { credentials: 'same-origin' });
    const body = await r.json();
    if (!r.ok || body.code !== 0) throw new Error(body.message || String(r.status));
    rows = body.data || [];
  } catch (e) {
    // 不弹 toast、不打断页面：歌词网格仍是 mock，曲目列表拿不到
    // 不该让整个标注页不可用
    box.innerHTML = '<span class="piece-empty">曲目列表加载失败</span>';
    return;
  }

  if (rows.length === 0) {
    // 「拿不到」和「确实没有」不能混成同一句文案
    box.innerHTML = '<span class="piece-empty">暂无曲目</span>';
    return;
  }

  demos = rows;
  currentDemoIdx = -1;
  box.innerHTML = "";
  rows.forEach((d, i) => {
    const usable = d.segment_count > 0;
    const btn = document.createElement("button");
    btn.className = "piece-btn";
    btn.textContent = `${d.title} (${d.segment_count}段)`;
    btn.disabled = !usable;
    if (usable) {
      btn.onclick = () => switchPiece(i);
    } else {
      // 仍然渲染、只置灰：标注页标不了没分段的曲目，但要让人看见
      // 「这条还没解析」，直接隐藏等于把问题藏起来
      btn.title = "该曲目尚未解析出分段，无法标注";
    }
    box.appendChild(btn);
  });

  // 默认选中第一条有分段的；全都没有分段时一条都不选
  const first = rows.findIndex(d => d.segment_count > 0);
  if (first >= 0) switchPiece(first);
}

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

renderLyrics();
renderAnnotations();
fetchDemos();
```

**注意**：`renderLyrics()` / `renderAnnotations()` 两行必须保留，`fetchDemos()` 放在它们**之后**调用（异步，不阻塞渲染）。

- [ ] **Step 4: 验证——经 HTTP 打开页面，确认脚本无语法错误**

后端应仍在跑（Task 2 Step 2 起的那个进程）。若已停，重新起一遍。

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
curl -s -c /tmp/t.jar -X POST -H 'Content-Type: application/json' \
  -d '{"username":"teacher01","password":"xiyun@2026"}' \
  http://127.0.0.1:8877/api/auth/login > /dev/null
curl -s -b /tmp/t.jar http://127.0.0.1/annotation.html -o /tmp/ann.html -w '%{http_code}\n'
grep -c 'pieceSelector' /tmp/ann.html
grep -c 'fetchDemos' /tmp/ann.html
```

预期：状态码 `200`；`pieceSelector` 命中 **2** 次（HTML 容器 1 次 + `getElementById` 1 次）；`fetchDemos` 命中 **2** 次（定义 1 次 + 调用 1 次）。

- [ ] **Step 5: 验证——浏览器里真实渲染**

用 `/browse` 技能打开 `http://127.0.0.1/annotation.html`（会复用 Task 2 Step 4 登录的会话），逐项确认：

1. 曲目选择区出现 **6** 个按钮，文案带分段数
2. id 15（`01_xipi_1931 (0段)`）与 id 19（`《红娘》· 叫张生隐藏在棋盘之下 (0段)`）**呈置灰且点不动**
3. 默认选中的是 **id 1**（`贵妃醉酒·选段 (1段)`）——它是 id 升序里第一条 `segment_count > 0` 的。**不要以为该选 16**：排序是 id 升序，1 排在 16 前面
4. 点 id 16 的按钮，高亮切过去，toast 文案是「《穆桂英挂帅》· 辕门外三声炮 · 歌词数据待接入（C2/C3 未实现）」
5. **歌词网格没有变化**——这是本轮的预期行为（`LYRICS` 仍是 mock），不是 bug
6. 右侧「老师标注」面板、字格点击、`saveAnnotation()` 等原有功能照常可用

- [ ] **Step 6: 验证——接口拿不到时页面照常可用**

**不要停后端**：页面本身也由 Flask 提供，后端死了整页 502，验证不了这个分支。

改为临时把请求指向一个不存在的接口，逼出 `catch` 分支。把 Step 3 代码里的：

```js
    const r = await fetch('/api/demos', { credentials: 'same-origin' });
```

临时改成：

```js
    const r = await fetch('/api/demos-not-exist', { credentials: 'same-origin' });
```

刷新页面，确认：

1. 选择区显示「**曲目列表加载失败**」
2. **没有**弹 toast
3. 歌词网格正常渲染、字格能点、右侧标注面板可用、`saveAnnotation()` 能弹成功 toast

确认完**把 `/api/demos-not-exist` 改回 `/api/demos`**，再刷新一次确认恢复正常（6 个按钮回来）。这一步的改动**不进 commit**——Step 7 的 `git status` 会暴露它。

- [ ] **Step 7: 重新起后端并做收尾检查**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
.venv/bin/python app-d.py > /tmp/xiyun-api.log 2>&1 &
for i in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:8877/login.html && break; sleep 0.5; done
.venv/bin/python scripts/check_db.py; echo "exit=$?"
git status --short
```

预期：

- `check_db.py` 只报**既有漂移**（`demo_versions` 表 + `teacher_demos` 三列，见记忆 `check-db-pre-existing-drift`），**没有新增差异**。本次没动 `schema.sql` 与 `app/models/`
- `git status --short` 只有 `annotation.html` 一个改动，**没有 `_t_*.py` 之类的临时文件残留**

- [ ] **Step 8: 提交**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add annotation.html
git commit -m "feat: 标注页曲目选择器接上 GET /api/demos"
```

---

## 收尾

三个 Task 全部完成后，把后端进程留着（用户可能要继续验证）或停掉，并在汇报里说明。本轮**没有**实现 C2–C7，`annotation.html` 的歌词网格仍是 mock——这是 spec 明确的范围，不是遗留缺陷。
