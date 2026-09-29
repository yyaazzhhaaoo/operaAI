# 删除标注接口（C6 `DELETE /api/annotations/<id>`）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 C6——把标注页每行的 ✕ 接上真删除链路，让老师标错的规则能撤掉（这是唯一能撤掉一条标注的手段）。

**Architecture:** 自下而上三层各一个小改动（repo 两个函数 → service 的 404 判定与事务 → HTTP 路由），再把 `annotation.html` 的 `deleteAnnotation` 从「弹未实现」换成真 DELETE + 原生 `confirm` + 成功后本地 `splice`。C7 的占位路由原样保留。

**Tech Stack:** Python 3.11 / Flask / SQLAlchemy 2.x / PostgreSQL / pydantic v2 / 原生 JS 单页

**依据 spec:** `docs/superpowers/specs/2026-09-29-delete-annotation-api-design.md`

## Global Constraints

- **不新增测试框架。** 本仓库没有 `tests/`、`requirements.txt` 里也没有 pytest。验证一律用**对真接口跑的 curl**、`.venv/bin/python` 脚本与 `/browse` 实测。不要 `pip install pytest`。
- **Python 解释器用 `.venv/bin/python`**，先 `cd /Users/meiyazhao/Documents/lianshu/operaAI`。
- **`/api` 前缀只在 `app/api/__init__.py` 的 `url_prefix` 里写一次**，路由写相对路径。
- **响应一律用 `app/response.py` 的 `ok()`**。C6 回 `ok(None)`，**200 不是 204**——204 按定义无响应体，会打破统一信封。
- **权限是教师**：`@login_required` **加** `@teacher_required`，叠放顺序固定、`login_required` 在外层（同 C4/C5/C7）。
- **路径参数用 `<int:annotation_id>`**，不是 `<id>`、不是 `<annotation_id>`。视图里的参数名也叫 `annotation_id`（`id` 遮蔽内置函数）。
- **不判归属**：任何教师可删任何人的标注（spec 3.3）。不要写 `if ann.teacher_id != current_user_id()`。
- **不改 `schema.sql` / `app/models/*` / `app-d.py`**，不引 Alembic，不加依赖。
- **只做 C6。** `app/api/demos_segments_annotations.py` 里的 **C7（`GET /api/annotations/rules`）占位路由一个字都不要动**；`annotation.html` 的 C4 列表读取（`fetchAnnotations`）、C5 写入（`saveAnnotation`）、技法依赖图谱面板（`TECHNIQUE_DEPS` / `RULE_IMPACT` / `renderDeps`）同样不动。
- **数据库时区是 `Asia/Shanghai`**（不是 UTC）。C6 不涉及时间列，此处仅备忘——**不要**给任何查询套 `AT TIME ZONE`。
- **后端是 `debug=True` 跑的，Werkzeug reloader 会自动重载**。改完 `.py` 不用手工重启，但**要 curl 一次确认改动真生效了**（reloader 在语法错时会留在旧代码上继续服务，症状是「改了没反应」）。`.env` 里 `SECRET_KEY` 是固定值，重载**不会**让浏览器已登录的会话失效。

### 当前真库基线（2026-09-29 实测）

- `annotations` 表 **0 行**——本轮所有验证数据都是**自己写进去的**，每个任务结束时必须删干净、回到 0 行
- `teacher01` 的 `users.id` 是 **2**（不是 1——id 1 已被删除，序列从 2 起）；`stu001` 是 **3**
- **seg 119**（demo 16 第 10 段「谁料想我五十三岁又管三军」）：`seq=10`，**12 个字**，下标 0–11
- `annotations` 的 DDL：`id SERIAL PRIMARY KEY` / `word_index INT NOT NULL` / `tag VARCHAR(10) NOT NULL` / `tolerance INT CHECK (0–100)` / `created_at TIMESTAMP DEFAULT NOW()` / `UNIQUE(segment_id, word_index, tag)`
- **没有任何外键指向 `annotations.id`**（`grep -n "REFERENCES annotations" schema.sql` 无结果）。删一行不会级联，也不会让别的表悬空——这是本接口能真删的前提
- 种子账号 `teacher01` / `stu001`，密码 `xiyun@2026`
- 登录：`POST /api/auth/login`，body `{"username":"...","password":"..."}`

### 验证数据的清理纪律

C6 的验证要**先有行才能删**，所以每个任务都是「借 C5 的接口造行 → 用 C6 删掉 → 确认回到 0」。

- 造行只能用 `library_service.create_annotation`（脚本里）或 `POST /api/annotations`（curl 里），**并抓住返回的 `data.id`**
- 清理**按 id 删**，**绝不** `DELETE FROM annotations WHERE segment_id = ...`——那会连真数据一起删掉
- 每个任务的最后一步都是 `SELECT count(*) FROM annotations;` 回 **0**。**不是 0 就停下来查，不要继续下一个任务**

---

## Task 1: 仓储层与服务层——删除的判定与事务边界

**Files:**
- Modify: `app/repositories/annotations_repo.py`（末尾追加 2 个函数，现有 5 个函数不动）
- Modify: `app/services/library_service.py`（末尾追加 1 个函数，现有函数不动）

**Interfaces:**
- Consumes: `app.models.Annotation`、`app.common.errors.BusinessError`、`app.db.session_scope`（脚本侧）
- Produces:
  - `annotations_repo.get_by_id(db: Session, annotation_id: int) -> Annotation | None`
  - `annotations_repo.remove(db: Session, ann: Annotation) -> None`
  - `library_service.delete_annotation(db: Session, annotation_id: int) -> None`（不存在抛 `BusinessError(404, "标注不存在")`；成功无返回值）

- [ ] **Step 1: 写验证脚本 `/tmp/c6-service.py`**

先写测试、后写实现。脚本全程用 `session_scope()`（脚本侧的会话，进出都管事务）。

```python
# C6 service 层验证：造行 → 删 → 验状态 → 清理。
# 全部走 session_scope()（脚本侧会话，与 Flask 请求内的 get_db() 契约不同，不可互换）。
import sys
sys.path.insert(0, "/Users/meiyazhao/Documents/lianshu/operaAI")

from app.common.errors import BusinessError
from app.db import session_scope
from app.repositories import annotations_repo
from app.services import library_service

SEG = 119        # 12 个字
TEACHER = 2      # teacher01


def count():
    with session_scope() as s:
        return len(annotations_repo.get_annotations_list(s))


# 基线：表必须是 0 行，否则说明上一轮没清干净
n0 = count()
assert n0 == 0, f"基线不是 0 行，实际 {n0}——先清理再跑"
print(f"[基线] annotations {n0} 行 OK")

# 借 C5 的 create_annotation 造两行（它会 commit）
with session_scope() as s:
    a = library_service.create_annotation(
        s, segment_id=SEG, word_index=0, tag="拖腔", tolerance=30, teacher_id=TEACHER)
    b = library_service.create_annotation(
        s, segment_id=SEG, word_index=1, tag="滑音", tolerance=40, teacher_id=TEACHER)
    id_a, id_b = a["id"], b["id"]
print(f"[自造] id={id_a} (字0 拖腔) / id={id_b} (字1 滑音)")

# ① get_by_id：取得到 / 取不到回 None（不是抛异常）
with session_scope() as s:
    row = annotations_repo.get_by_id(s, id_a)
    assert row is not None, "get_by_id 没取到刚写的行"
    assert row.id == id_a and row.word_index == 0 and row.tag == "拖腔"
    assert annotations_repo.get_by_id(s, 999999) is None, "不存在的 id 应回 None"
print("[1] get_by_id 取得到 / 取不到回 None OK")

# ② 正常删除：返回 None、行没了、兄弟行还在
with session_scope() as s:
    ret = library_service.delete_annotation(s, id_a)
assert ret is None, f"delete_annotation 应回 None，实际 {ret!r}"
with session_scope() as s:
    assert annotations_repo.get_by_id(s, id_a) is None, "行没删掉"
    assert annotations_repo.get_by_id(s, id_b) is not None, "误删了兄弟行"
print("[2] 正常删除：回 None / 行没了 / 兄弟行在 OK")

# ③ 再删同一个 id → 404
try:
    with session_scope() as s:
        library_service.delete_annotation(s, id_a)
except BusinessError as e:
    assert e.code == 404, f"应 404，实际 {e.code}"
    assert e.message == "标注不存在", f"文案不对：{e.message}"
    print(f"[3] 重复删除 -> {e.code} {e.message} OK")
else:
    raise AssertionError("重复删除没抛 BusinessError")

# ④ id=0 与 999999 → 404
for bad in (0, 999999):
    try:
        with session_scope() as s:
            library_service.delete_annotation(s, bad)
    except BusinessError as e:
        assert e.code == 404 and e.message == "标注不存在", f"id={bad} 回 {e.code} {e.message}"
    else:
        raise AssertionError(f"id={bad} 没抛 404")
print("[4] id=0 / 999999 -> 404 OK")

# ⑤ 失败路径不该动到已有行
with session_scope() as s:
    assert annotations_repo.get_by_id(s, id_b) is not None, "失败路径误删了 id_b"
print("[5] 失败路径不动已有行 OK")

# 清理：只删自己造的 id_b
with session_scope() as s:
    library_service.delete_annotation(s, id_b)
n1 = count()
assert n1 == 0, f"清理后不是 0 行，实际 {n1}"
print(f"[清理] annotations 回到 {n1} 行 OK")
print("\n全部通过")
```

- [ ] **Step 2: 跑脚本，确认它失败**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
.venv/bin/python /tmp/c6-service.py
```

预期：**`AttributeError: module 'app.repositories.annotations_repo' has no attribute 'get_by_id'`**（在第 ① 步）。

**若报的是「基线不是 0 行」，先清理再跑，不要继续。**

- [ ] **Step 3: 实现仓储层的两个函数**

在 `app/repositories/annotations_repo.py` **末尾追加**（`add` 函数之后）：

```python
def get_by_id(db: Session, annotation_id: int) -> Annotation | None:
    """按主键取一条标注（C6 的存在性判定）。取不到返回 None。

    返回 None 表示「没有」——调用方据此抛 404，不拿它当别的信号。

    用 db.get() 而不是 select().where()：直接走主键查询 / identity map，
    是本文件已有写法里最短的一个。
    """
    return db.get(Annotation, annotation_id)


def remove(db: Session, ann: Annotation) -> None:
    """删除一条标注。只标脏，提交交给 service 层（同 add 只 flush 的约定）。

    收 ORM 对象而不是 id：调用方（service）已经为了判 404 把行查出来了，
    再收一个 id 去发 DELETE 语句等于把同一次查找做两遍。

    **不用 `DELETE ... WHERE id = ?` 拿 rowcount**：rowcount 只有 0/1，
    拿到 0 时还要再 SELECT 一次才能区分「不存在」与「并发被删」，省下的
    那次查询又还回去了；而且本层一律以 ORM 对象为出入口，写原生 delete()
    会让这一层出现两种风格。C6 的量级是「一次一行」，不值得为它优化。
    """
    db.delete(ann)
```

- [ ] **Step 4: 实现服务层的 `delete_annotation`**

在 `app/services/library_service.py` **末尾追加**（`create_annotation` 之后）：

```python
def delete_annotation(db: Session, annotation_id: int) -> None:
    """C6 删除标注。不存在抛 404。成功无返回值。

    只有一条判定——路径参数已由 `<int:annotation_id>` 保证是非负整数，
    没有请求体也就没有入参校验，重复删除在第一步就撞 404。所以这里没有
    create_annotation 那样的 404/422/409 三级。

    **不判归属**：任何教师可删任何人的标注（spec 3.3）。C4 的前提是
    「一个唱段一套全局唯一的规则集」，规则的所有者是唱段而不是标它的
    那位教师；且 C4 出参不返回 teacher_id，判归属只会让用户遇到
    「删不掉又不知道为什么」。若文档方要求按人隔离，改动点在这里。

    返回 None 而不是 dict：删除没有「新状态」可返回。本文件其他 service
    函数都返回 dict/ORM，是因为它们的出参有内容，这里没有。
    """
    ann = annotations_repo.get_by_id(db, annotation_id)
    if ann is None:
        raise BusinessError(404, "标注不存在")
    annotations_repo.remove(db, ann)
    db.commit()
```

`annotations_repo` 与 `BusinessError` 都已在文件顶部 import 过（`create_annotation` 在用），**不需要新增 import**。

- [ ] **Step 5: 跑脚本，确认通过**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
.venv/bin/python /tmp/c6-service.py
```

预期输出：

```
[基线] annotations 0 行 OK
[自造] id=<N> (字0 拖腔) / id=<N+1> (字1 滑音)
[1] get_by_id 取得到 / 取不到回 None OK
[2] 正常删除：回 None / 行没了 / 兄弟行在 OK
[3] 重复删除 -> 404 标注不存在 OK
[4] id=0 / 999999 -> 404 OK
[5] 失败路径不动已有行 OK
[清理] annotations 回到 0 行 OK

全部通过
```

- [ ] **Step 6: 确认表回到 0 行**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
docker exec docker_postgres psql -U xiyun -d xiyun -At -c "SELECT count(*) FROM annotations;"
```

预期输出：`0`

- [ ] **Step 7: Commit**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add app/repositories/annotations_repo.py app/services/library_service.py
git commit -m "feat: 新增标注删除仓储与业务逻辑（C6 数据层 + service）"
```

---

## Task 2: 接口层——`DELETE /api/annotations/<int:annotation_id>`

**Files:**
- Modify: `app/api/demos_segments_annotations.py:117-121`（替换 C6 占位路由）

**Interfaces:**
- Consumes: `library_service.delete_annotation(db, annotation_id) -> None`（Task 1）
- Produces: HTTP `DELETE /api/annotations/<int:annotation_id>` → `200` + `{"code":0,"message":"ok","data":null}`

- [ ] **Step 1: 先确认占位路由现在是什么样（这就是「测试失败」的证据）**

后端已在 8877 跑着。先登录教师拿 cookie，再打现在的 C6：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
U=http://127.0.0.1:8877
J='Content-Type: application/json'
curl -s -c /tmp/c6-t.jar -H "$J" -X POST \
  -d '{"username":"teacher01","password":"xiyun@2026"}' $U/api/auth/login >/dev/null
echo -n "DELETE /api/annotations/1 → "
curl -s -b /tmp/c6-t.jar -X DELETE $U/api/annotations/1 -w ' [%{http_code}]\n'
```

预期：`{"code":0,"message":"ok","data":"1"} [200]`

**`data` 是字符串 `"1"`**——占位路由 `return ok(id)` 把路径参数原样吐回来了，既没删库、也不是 `null`。这就是未实现的证据。

- [ ] **Step 2: 替换 C6 路由**

把 `app/api/demos_segments_annotations.py` 第 117–121 行：

```python
@api_bp.route("/annotations/<id>",methods=["DELETE"])
@login_required
@teacher_required
def del_annotations(id):
    return ok(id)
```

整段替换为：

```python
@api_bp.route("/annotations/<int:annotation_id>", methods=["DELETE"])
@login_required
@teacher_required
def del_annotations(annotation_id):
    """C6 删除标注。

    路径参数用 `<int:annotation_id>`：非整数与负数在**路由层**就 404，不进
    视图（同 C2/C3/C4 的 `<int:...>`）。所以本层与 service 层都不必判负数
    或非数字——那是永不可达的死分支。已实测：`/api/segments/abc/annotations`
    与 `/api/segments/-1/annotations` 都回 404（Werkzeug 的 IntegerConverter
    正则是 `\d+`，不收负号）。

    参数名不叫 `id`：`id` 遮蔽内置函数，且读代码时分不清是「标注的 id」
    还是别的什么。

    **权限是教师**（文档 C6 的权限列就是「教师」），与同组 C4/C5/C7 一致。

    **不判归属**（spec 3.3）：任何教师可删任何人的标注，理由见 service 层。

    回 `ok(None)`，**不是 204**：本项目统一信封（《5-接口清单》），204 按
    定义无响应体，会打破它。也不回被删的行——行已经没了，而前端本来就知道
    自己删的是哪个 id（这点与 C5 不同：新建的 id 由数据库生成，前端不知道）。

    与 C7 `/annotations/rules` 不冲突，且不依赖注册顺序：`rules` 不是整数，
    永远匹配不上 `<int:annotation_id>`。反过来说，若这里保持字符串转换器，
    C7 能不能用就取决于两条路由谁先注册了。
    """
    library_service.delete_annotation(get_db(), annotation_id)
    return ok(None)
```

**C7（`/annotations/rules`，紧随其后）原样保留，一个字都不要动。**

- [ ] **Step 3: 确认 reloader 吃到了改动**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
sleep 2
echo -n "DELETE /api/annotations/1 → "
curl -s -b /tmp/c6-t.jar -X DELETE http://127.0.0.1:8877/api/annotations/1 -w ' [%{http_code}]\n'
```

预期：`{"code":404,"message":"标注不存在","data":null} [404]`

（`data` 从字符串 `"1"` 变成了 `null`、状态码从 200 变成 404，说明新代码生效了。**若仍回 `"1"`，说明 reloader 没重载**——去看跑 `app-d.py` 那个终端的报错，多半是语法错让 reloader 留在了旧代码上。）

- [ ] **Step 4: 跑接口验证矩阵**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
U=http://127.0.0.1:8877
J='Content-Type: application/json'
C() { curl -s -b "$1" -X DELETE "$2" -w ' [%{http_code}]\n'; }

# 学生 cookie
curl -s -c /tmp/c6-s.jar -H "$J" -X POST \
  -d '{"username":"stu001","password":"xiyun@2026"}' $U/api/auth/login >/dev/null

# 造两行（借 C5 的写接口），抓住 id
echo -n "造行 A: "
curl -s -b /tmp/c6-t.jar -H "$J" -X POST \
  -d '{"segment_id":119,"word_index":0,"tag":"拖腔","tolerance":30}' $U/api/annotations
echo
echo -n "造行 B: "
curl -s -b /tmp/c6-t.jar -H "$J" -X POST \
  -d '{"segment_id":119,"word_index":1,"tag":"滑音","tolerance":40}' $U/api/annotations
echo
```

把上面两条返回的 `data.id` 记下来（下面用 `$A` / `$B` 代指实际数字）：

```bash
A=<行A的id>
B=<行B的id>

echo "1 正常删除 A     :"; C /tmp/c6-t.jar $U/api/annotations/$A
echo "2 再删 A（404）  :"; C /tmp/c6-t.jar $U/api/annotations/$A
echo "3 删 id 0        :"; C /tmp/c6-t.jar $U/api/annotations/0
echo "4 删 id 999999   :"; C /tmp/c6-t.jar $U/api/annotations/999999
echo "5 负数（路由层） :"; C /tmp/c6-t.jar $U/api/annotations/-1
echo "6 abc（路由层）  :"; C /tmp/c6-t.jar $U/api/annotations/abc
echo "7 未登录         :"; curl -s -X DELETE $U/api/annotations/$B -w ' [%{http_code}]\n'
echo "8 学生登录       :"; C /tmp/c6-s.jar $U/api/annotations/$B
echo "9 GET 同一路径   :"; curl -s -b /tmp/c6-t.jar $U/api/annotations/$B -w ' [%{http_code}]\n'
echo "10 B 还在不在    :"
curl -s -b /tmp/c6-t.jar $U/api/segments/119/annotations
echo
```

预期逐条：

| # | 用例 | 期望 |
|---|---|---|
| 1 | 正常删除 A | `{"code":0,"message":"ok","data":null}` `[200]`，**`data` 是 `null`**，不是 `{}`、不是被删的行、不是字符串 |
| 2 | 再删 A | `{"code":404,"message":"标注不存在","data":null}` `[404]` |
| 3 | 删 id 0 | `404`「标注不存在」 |
| 4 | 删 id 999999 | `404`「标注不存在」 |
| 5 | `/api/annotations/-1` | `{"code":404,"message":"接口不存在",...}` `[404]`——**文案是「接口不存在」不是「标注不存在」**，说明是路由层拦的 |
| 6 | `/api/annotations/abc` | 同 5，`404`「接口不存在」 |
| 7 | 未登录 + 合法 id | `{"code":401,"message":"未登录",...}` `[401]` |
| 8 | 学生登录 + 合法 id | `{"code":403,"message":"需要教师权限",...}` `[403]` |
| 9 | `GET /api/annotations/<B>` | `{"code":405,"message":"请求方法不允许",...}` `[405]`——该路径只注册了 DELETE |
| 10 | 查 C4 列表 | 只剩 B 那一行（A 已删），B 的行**内容与删除前一致** |

**用例 7 与 8 都不能删掉 B**——它们被权限拦在 service 之前。用例 10 就是验这件事。

- [ ] **Step 5: 清理，确认表回到 0 行**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
U=http://127.0.0.1:8877
echo -n "清理 B: "
curl -s -b /tmp/c6-t.jar -X DELETE $U/api/annotations/<B> -w ' [%{http_code}]\n'
docker exec docker_postgres psql -U xiyun -d xiyun -At -c "SELECT count(*) FROM annotations;"
```

预期：清理那行回 `[200]`，行数输出 `0`

- [ ] **Step 6: Commit**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add app/api/demos_segments_annotations.py
git commit -m "feat: 实现删除标注接口 C6 DELETE /api/annotations/<id>"
```

---

## Task 3: 前端——✕ 接真删除

**Files:**
- Modify: `annotation.html:808`（✕ 那行传 id）
- Modify: `annotation.html:813-818`（`deleteAnnotation` 整体替换）

**Interfaces:**
- Consumes: `DELETE /api/annotations/<int:annotation_id>`（Task 2）、`annNote(ann)`（`:786`）、`renderAnnotations()`（`:788`）、`renderLyrics()`（`:588`）、`showToast()`、本地 `annotations` 数组（元素形状 `{ id, index, tag, tolerance, createdAt }`）
- Produces: 页面函数 `deleteAnnotation(id)`（`id` 是库里的自增主键 `ann.id`，**不是** `ann.index`）

- [ ] **Step 1: ✕ 传 id**

`annotation.html:808`，把：

```html
      <div class="ann-del" onclick="deleteAnnotation()">✕</div>
```

改为：

```html
      <div class="ann-del" onclick="deleteAnnotation(${ann.id})">✕</div>
```

传的是 `ann.id`（库里的自增主键），**不是 `ann.index`**。两者同名不同义：`index` 是「第几个字」，传错维度会删掉另一条标注，而且不会报错——那个 id 很可能真的存在。

- [ ] **Step 2: 替换 `deleteAnnotation`**

`annotation.html:813-818` 的整段：

```js
function deleteAnnotation() {
  // C6 未实现：不从列表里移除。本地 splice 掉的条目刷新就回来了，
  // 而点了 ✕ 却什么都没发生是更清楚的说法
  // &lt;id&gt; 是 HTML 实体：showToast 走 innerHTML，直接写 <id> 会被当未知标签吞掉
  showToast("info", "删除接口未实现", "C6（DELETE /api/annotations/&lt;id&gt;）尚未实现，标注仍在库中");
}
```

替换为：

```js
async function deleteAnnotation(id) {
  const ann = annotations.find((a) => a.id === id);
  if (!ann) return;   // 行已被别处删掉、本地也找不到了，没什么可删
  // 删错一个 tag 在 C6 之前是撤不回的，而误点只需一次轻触——先确认。
  // 文案带上字与 tag（annNote 拼「谁字拖腔标注」）：只写「确定删除吗？」
  // 用户无从判断删的是哪一条
  if (!confirm(`确定删除「${annNote(ann)}」吗？`)) return;

  try {
    const r = await fetch(`/api/annotations/${id}`, {
      method: 'DELETE',
      // 同源相对路径 + same-origin：与 C1–C5 同理，写成跨源地址时 fetch
      // 默认不带 Cookie，后端 login_required 只会看到空 session 并回 401
      credentials: 'same-origin',
    });
    const body = await r.json();
    if (!r.ok || body.code !== 0) throw new Error(body.message || String(r.status));
  } catch (e) {
    // 只弹 toast、不改本地列表：annotations 只装服务端确认过的状态。
    // 失败时那一行必须原样留着——否则用户以为删掉了，刷新才发现还在
    showToast("error", "删除失败", e.message);
    return;
  }

  // 文案在 splice 之前算：ann 对象 splice 后仍在（只是不在数组里），
  // 但把「读本地状态的东西」放在改本地状态之前，读起来不必回头确认
  showToast("success", "已删除标注", annNote(ann));
  const i = annotations.findIndex((a) => a.id === id);
  if (i >= 0) annotations.splice(i, 1);
  renderAnnotations();
  renderLyrics();   // 格子上的 ✓ 由 renderLyrics 画，删了要重画一次
}
```

**不需要 C5 那套 `annLoaded` 降级分支**，两条理由：

1. `annLoaded === false` 的两个赋值点（`switchSegment`、`fetchAnnotations` 的失败分支）都紧跟在 `annotations = []` 之后，所以它为 false 时列表必为空、根本没有 ✕ 可点。
2. 语义不同：插入是在断言「这就是全部」，本地列表不完整时会说错话；删除只是拿掉**一个确定存在的行**，哪怕服务端还有本地不知道的行，删掉已知的这一条依然正确。

- [ ] **Step 3: 静态检查**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
.venv/bin/python - <<'EOF'
import re
src = open("annotation.html", encoding="utf-8").read()
blocks = re.findall(r"<script>(.*?)</script>", src, re.S)
print(f"抽出 {len(blocks)} 个 script 块")
open("/tmp/c6-ann.js", "w", encoding="utf-8").write("\n;\n".join(blocks))
EOF
node --check /tmp/c6-ann.js && echo "语法 OK"
grep -n "deleteAnnotation\|ann-loaded\|splice" annotation.html | head
```

预期：`语法 OK`，且 grep 出 `onclick="deleteAnnotation(${ann.id})"` 与 `async function deleteAnnotation(id)`。

`node --check` 只做语法检查、不执行，所以顶层 `document` 未定义不影响它。**若机器上没有 node**，跳过这一步，靠 Step 4 的浏览器实测兜底（语法错会让整个页面白屏，一眼可见）。

- [ ] **Step 4: 用 `/browse` 验证**

先用 `/browse` 技能登录 `teacher01`（`http://127.0.0.1:8877/annotation.html`，密码 `xiyun@2026`）。

切到 **demo 16**（《穆桂英挂帅》· 辕门外三声炮，**10 段**）→ 第 10 段（seg 119，12 个字）。

先造数据：选「谁」(下标 0) + 「拖腔」 + 添加标注，再选「料」(下标 1) + 「滑音」 + 添加标注。此时列表应是 `(2条)`。

1. **确认框文案**：点第一行的 ✕ →
   - 弹出原生 confirm，文案是 **「确定删除「谁字拖腔标注」吗？」**（带字与 tag，不是干巴巴的「确定删除吗？」）
   - 用 `dialog-accept` / `dialog-dismiss` 处理；**处理器要在点击之前设好**，否则弹窗会挂住后续命令
2. **取消不删**：设 `dialog-dismiss` → 点 ✕ → 列表**仍是 `(2条)`**，`Network` 里**没有** `DELETE` 请求
3. **确认后删掉**：设 `dialog-accept` → 点第一行的 ✕ → 列表变 `(1条)`、那一行消失、**歌词格「谁」上的 ✓ 消失**（「料」的 ✓ 还在）、弹 ✅「已删除标注 / 谁字拖腔标注」
4. **真落库**：**刷新页面** → 列表**仍是 `(1条)`**，只剩「料」那条。这是「真删除」的唯一证明
5. **删最后一条回空态**：再把「料」那条也删掉 → 列表显示 **「📝 暂无标注规则」**、`(0条)`，两个字的 ✓ 都没了
6. **失败路径不动列表**：用 fetch 补丁让 `DELETE /api/annotations/*` 回 404「接口不存在」（**不要改文件**，否则会留残留）→ 先造一条 → 点 ✕ → 确认 → 弹 ⚠️「删除失败 / 接口不存在」、**列表条数不变**、那一行的 ✓ 仍在
7. **删完不串段**：在某段删掉一条后，立刻快速连点第 9 段和第 10 段 → 最终列表属于**后点**的那个唱段，没有混进另一段的条目

（第 6 项用页面内 `window.fetch` 补丁，不改磁盘上的文件，天然无残留。）

- [ ] **Step 5: 清理并确认表回到 0 行**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
docker exec docker_postgres psql -U xiyun -d xiyun -c "SELECT id,segment_id,word_index,tag,tolerance,teacher_id,created_at FROM annotations ORDER BY id;"
```

**先肉眼确认列出来的每一行都是本次浏览造的**（`teacher_id` 应为 `2`、`created_at` 是今天的当前时间、`segment_id` 是 119 或浏览时用过的段），**再删**：

```bash
docker exec docker_postgres psql -U xiyun -d xiyun -c "DELETE FROM annotations;" -c "SELECT count(*) FROM annotations;"
```

预期：`DELETE <N>`，然后 `count` 为 `0`

- [ ] **Step 6: Commit**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add annotation.html
git commit -m "feat: 标注页 ✕ 接上 DELETE /api/annotations"
```

---

## Task 4: 登记 DOC_ISSUES 第 31 条 + 终检

**Files:**
- Modify: `DOC_ISSUES.md`（在 `## 待核实` 之前插入第 31 条；并更新第 30 条里关于 C6 的两点）

**Interfaces:**
- Consumes: Task 1–3 的全部结论
- Produces: 无代码接口

- [ ] **Step 1: 写 `DOC_ISSUES.md` 第 31 条**

在 `## 待核实` 之前插入：

````markdown
## 31. 删除标注（C6）只有一句话描述，请求与响应契约、「不存在」语义与归属规则全未定义

**涉及**：《5-接口清单》2.3 节 C6 / 《3-功能清单》9.7 / `app/api/demos_segments_annotations.py` / `app/services/library_service.py` / `app/repositories/annotations_repo.py` / `annotation.html`

### 31.1 C6 的契约全未定义

C6 在文档里的**全部**内容是「`DELETE /api/annotations/<id>` ｜ 教师 ｜ 删除标注（功能 9.7）」一行，《3-功能清单》9.7 的全文是「删除标注 / 移除规则」。与第 26（C1）、27（C2/C3）、28（C4）、30（C5）条同源。请求体、响应体、状态码、删不存在的 id 回什么、能不能删别人的标注，一概没有。本次采用的口径：

| 未定义项 | 本次采用的口径 |
|---|---|
| 路径参数 | `<int:annotation_id>`。非整数与负数在**路由层**就 `404`（Werkzeug 的 `IntegerConverter` 正则是 `\d+`），不进视图 |
| 请求体 | 无。本接口不读 body，`_payload()` 不参与 |
| 成功 | `200` + `{"code":0,"message":"ok","data":null}` |
| 出参为什么是 null | 行已经没了，「返回被删的那一行」要么多查一次、要么把删前状态随手抛回去；前端本来就知道自己删的是哪个 id。**与 C5 不同**：C5 回整行是因为新建的 id 由数据库生成、前端不知道 |
| **不是 204** | 本项目统一信封（《5-接口清单》），204 按定义无响应体，会打破它。`ok()` 也固定回 200 |
| 不存在 | `404` +「标注不存在」 |
| **不采用幂等语义** | REST 教条会说删不存在的也该回 200/204。本项目没有幂等先例（C3/C4/C5 对「资源不存在」一律 404），且幂等在这里没有收益：前端点 ✕ 时那一行确实在屏幕上，404 只在并发下出现，此时告诉用户「这条已经没了」比静默成功更有用 |
| **不判归属** | 任何教师可删任何人的标注。见 31.2 |

### 31.2 归属：为什么任何教师都能删任何人的标注

C6 的权限列写「教师」，但**没有**规定能否删**别人标的**标注。本次选择不判归属：

1. C4 spec 3.4 已定 `annotations` 是「**一个唱段一套全局唯一的规则集**」——`UNIQUE(segment_id, word_index, tag)` **不含 `teacher_id`** 就是这条前提的物化。在这个前提下，规则的所有者是「这个唱段」，不是「标它的那位教师」。
2. C4 出参（`AnnotationOut`）**干脆不返回 `teacher_id`**（第 28 条）。前端拿不到归属，也就无从展示「这是谁标的」；此时后端判归属，用户看到的会是「删不掉但不知道为什么」。
3. 判归属会堵死「甲老师标错、乙老师来改」——而 C6 是唯一的撤回手段。

**这是本次自行采用的口径**。若文档方要求按人隔离，改动点在 `library_service.delete_annotation` 一个 if，但会与 C4 的「全局规则集」前提打架，届时两条都要一起改。

### 31.3 与第 30 条的关系

第 30 条「待确认」里有两处提到 C6，本条落地后状态变化：

- ~~「标错了撤不掉」~~ ——**已解除**。C6 实现后，标错 tag 可以删了重标。
- 「C5 是否需要『更新已有标注』接口」——**仍待文档方回答**。当前「改一个标注的 tag」只能靠「删 + 重标」两步，`id` 与 `created_at` 会变。若文档方认为需要原地更新，那是新接口，不在 C6 范围内。

### 31.4 数据现状

`annotations` 表实测 0 行，`seed.sql` 里也没有标注的 INSERT。本轮全部验证都是接口自己写进去、验完删掉的。

**待文档方确认**：

1. 删除成功回 `200` + `data: null` 是否可行？还是要 `204 No Content`（会打破统一信封）？
2. 删不存在的 id 回 `404` 是否可行？还是要求幂等（回 `200`）？
3. **删除是否应当限制在「本人标注」范围内？** 当前不限制（31.2）。若要限制，C4 的出参也得补 `teacher_id`，前端才能解释「为什么这条删不掉」。
4. 删除是否需要留痕（谁在什么时候删了哪条）？当前是物理删除、无审计表。
````

- [ ] **Step 2: 更新第 30 条里关于 C6 的两点**

第 30 条正文里有一句：

```
**「标错了撤不掉」**：C6（`DELETE /api/annotations/<id>`）未实现，标错 tag 只能等 C6。这是 C6 的事，但页面上已经把这条限制说明白了。
```

改为：

```
**「标错了撤不掉」**：C6（`DELETE /api/annotations/<id>`）已于 2026-09-29 实现，见第 31 条。在它之前，标错 tag 只能直接改库。
```

第 30 条「待确认」列表里的第 4 点：

```
4. C5 是否需要一个「更新已有标注」的接口？当前设计下改 `tag` 必须靠 C6 删了重标，而 C6 尚未实现。
```

改为：

```
4. C5 是否需要一个「更新已有标注」的接口？当前设计下改 `tag` 只能靠「C6 删 + C5 重标」两步，`id` 与 `created_at` 会变（C6 已实现，见第 31 条）。
```

- [ ] **Step 3: 跑建库一致性闸门**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && .venv/bin/python scripts/check_db.py
```

预期：**无新增差异**（本轮不改模型与 `schema.sql`）。脚本会报既有的 `demo_versions` 表 + `teacher_demos` 三列漂移——那是本轮之前就有的。**若报出 `annotations` 相关的差异，停下来查。**

- [ ] **Step 4: 终检——表回到 0 行**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
docker exec docker_postgres psql -U xiyun -d xiyun -At -c "SELECT count(*) FROM annotations;"
```

预期输出 `0`。**不是 0 就说明前面某个任务没清理干净。**

- [ ] **Step 5: 终检——没有残留的「C6 未实现」**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
grep -n "C6（DELETE\|C6 未实现\|删除接口未实现" annotation.html
```

预期：**无输出**。有输出说明 Task 3 没把那段占位注释清干净。

再确认 C7 的占位**仍在**（本轮不该动它）：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
grep -n "def annotations_rules" -A 5 app/api/demos_segments_annotations.py
```

预期：函数体内仍是 `return ok({"tag":tag,"word":word})` 的占位形态。

同时确认 C6 的**新**实现确实在：

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
grep -n 'annotations/<int:annotation_id>' -A 2 app/api/demos_segments_annotations.py
grep -n 'return ok(None)' app/api/demos_segments_annotations.py
```

预期：各 1 行。

- [ ] **Step 6: Commit**

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI
git add DOC_ISSUES.md
git commit -m "docs: 登记 C6 请求与响应契约未定义"
```

---

## 完成之后

全部任务做完、`annotations` 确认 0 行之后，用 `superpowers:finishing-a-development-branch` 收尾（本项目历来是直接提交到 `main`，无 feature 分支，届时按实际状态处理）。
