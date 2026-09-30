# 标注规则列表管理接口（C7 `GET /api/annotations/rules`）实现设计

日期：2026-09-30 ｜ 状态：已评审待实现 ｜ 关联：《5-接口清单》2.3 节 C7、《3-功能清单》9.6；`DOC_ISSUES.md` 第 32 条

## 1. 背景与目标

C1 → C2 → C3 → C4 → C5 → C6 这条链已落地，2.3 节只剩 C7 未实现。C7 是**跨唱段的全库标注列表**：C4 看的是「这一个唱段标了哪些字」，C7 看的是「整个库里所有标注规则」，对应《3-功能清单》9.6「标注规则列表管理 / 集中展示 + 筛选」。

**目标**：

1. `GET /api/annotations/rules` 返回全库标注，可按 `tag` 与 `word` 筛选
2. 每行自带归属（曲目 / 唱段）与字，前端一次请求就能渲染整张表
3. 把 `app/api/demos_segments_annotations.py:147-153` 的占位（当前只回显入参）换成真实现

**非目标（明确不做）**：

- **不做前端页面**。`功能 9.6` 在 `annotation.html` 里没有对应 UI，全项目也搜不到任何 `annotations/rules` 的调用方（见 2.3）。本轮只交付接口
- **不做分页**（同 C1–C4，仓库无先例）
- **不返回 `seq`**（唱段标题已够定位；后加字段不是破坏性变更）
- **不返回 `teacher_id`**（同 C4，不按教师隔离）
- **不校验 `tag` 入参取值**（理由见 3.2）
- 不改 `schema.sql` / `app/models/*`，不引 Alembic，不引新依赖，不动任何 `.html`

## 2. 文档给的 vs 库里有的

### 2.1 文档只有一行

| 编号 | 接口 | 权限 | 说明 |
|---|---|---|---|
| C7 | `GET /api/annotations/rules?tag=&word=` | **教师** | 规则列表管理（功能 9.6） |

《3-功能清单》9.6 的全文是「标注规则列表管理 ｜ 集中展示+筛选」。**响应体、两个参数的匹配语义、排序、分页一概没有**——与第 26（C1）、27（C2/C3）、28（C4）、30（C5）、31（C6）条同源。查询串里的 `tag=` / `word=` 两个参数名是**唯一的入参依据**。

同组 C5 的说明给出了字段名 `word_index`（「新增标注（`segment_id`, `word_index`, `tag`, `tolerance`）」），C7 出参沿用同一个坐标系。

### 2.2 卡点：`annotations` 表里没有「字」

`schema.sql:76-85`：

```sql
CREATE TABLE annotations (
  id SERIAL PRIMARY KEY,
  segment_id INT REFERENCES segments(id),
  word_index INT NOT NULL,
  tag VARCHAR(10) NOT NULL,  -- 滑音/归韵/换气/强音/拖腔/擞音
  tolerance INT CHECK (tolerance BETWEEN 0 AND 100),
  teacher_id INT REFERENCES users(id),
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(segment_id, word_index, tag)
);
```

**七个列里没有一列存字**。字在 `segments.lyrics_json` 里，要按下标取就得先过 `library_service._normalize_lyrics`（`:149`）。

这一点决定了本接口与 C4 的**根本差别**：C4 面向单个唱段，标注页那一刻已经加载了该唱段的 `lyrics`，所以 `char` 由前端从 `lyrics[word_index]` 取即可（C4 spec 3.2）。C7 面向全库，前端**没有**其它唱段的 `lyrics`，`char` 只能由后端算——`word=` 筛选同理，它就是在筛这个字。

> C4 spec 3.2 曾以「会踩归一函数的丢弃错位」为由拒绝让后端读 `lyrics_json`。那个理由在 C4 成立（后端算一份、前端算一份，两份可能不一致），但**在 C7 不成立**：C7 只有后端算这一份，不存在第二个坐标系。而且 `_normalize_lyrics` 是 C3 出参、C5 写入校验、这里三处共用的**同一个函数**，坐标系本来就该是它。

### 2.2.1 真库基线（2026-09-30 实测，**与 C4/C5/C6 spec 写的 0 行已不同**）

```
annotations      3 行
segments        16 行
teacher_demos    6 行
segments.lyrics_json 非 NULL  16 行（全部有歌词）
```

三条标注**全部挂在 seg 110**，`teacher_id` 都是 **2**（`teacher01`）：

| id | segment_id | word_index | tag | tolerance | created_at |
|---|---|---|---|---|---|
| 109 | 110 | 3 | 归韵 | 30 | 2026-09-30 09:00:15.033074 |
| 110 | 110 | 7 | 拖腔 | 30 | 2026-09-30 09:00:32.246823 |
| 111 | 110 | 9 | 强音 | 37 | 2026-09-30 09:01:09.529824 |

seg 110 属 **demo 16**、`seq = 1`、标题「**辕门外三声炮如同雷震**」、歌词 10 字（`word_index` 0–9）：

```
下标 0 1 2 3 4 5 6 7 8 9
字   辕 门 外 三 声 炮 如 同 雷 震
```

所以三条标注对应的字是 **3→三、7→同、9→震**。

**这改变了验证方式**：C4/C5/C6 那几轮 `annotations` 是 0 行，一切靠临时插行；本轮的读路径**有真数据可验**，临时插行只用于验「筛选出多行」与「越界行」这类真数据覆盖不到的分支。

`users.id`：`teacher01` = **2**，`stu001` = **3**。临时插行必须用真实存在的 id，编一个会当场撞外键。

### 2.3 没有调用方

全项目搜 `annotations/rules` 只有两处命中，都在 `app/api/demos_segments_annotations.py`：一处是 C6 的 docstring（说明两条路由不冲突），另一处是占位路由本身。

`annotation.html` 有「曲目选择器 + 唱段选择器 + 歌词网格 + 该唱段标注列表」四层，**没有**任何「全库规则」视图。所以本接口落地后前端仍是零调用方——这与 C4/C5/C6 不同，那三个都有页面在用。这是有意为之：《功能清单》9.6 是独立功能点，接口先落地，页面另行排期。

## 3. 接口契约

```
GET /api/annotations/rules?tag=<str>&word=<单字>        权限：教师
```

统一信封，`data` 是**数组**：

```json
{"code":0,"message":"ok","data":[
  {"id":109,"word_index":3,"char":"三","tag":"归韵","tolerance":30,
   "created_at":"2026-09-30T09:00:15.033074",
   "demo_id":16,"demo_title":"《穆桂英挂帅》· 辕门外三声炮",
   "segment_id":110,"segment_title":"辕门外三声炮如同雷震"}
]}
```

### 3.1 出参字段

| 字段 | 来源 | 可空 | 说明 |
|---|---|---|---|
| `id` | `annotations.id` | 否 | 将来加「就地删」入口时用它调 C6 |
| `word_index` | `annotations.word_index` | 否 | 指向 C3 出参 `lyrics[]` 的下标 |
| `char` | `_normalize_lyrics(segments.lyrics_json)[word_index]` 的 `char` | **是** | 见 3.4 |
| `tag` | `annotations.tag` | 否 | 出参**不校验取值**（同 C4） |
| `tolerance` | `annotations.tolerance` | **是** | |
| `created_at` | `annotations.created_at` | **是** | 不做时区换算，见 3.6 |
| `segment_id` | `annotations.segment_id` | **是** | |
| `segment_title` | `segments.title` | **是** | |
| `demo_id` | `segments.demo_id` | **是** | |
| `demo_title` | `teacher_demos.title` | **是** | |

`tolerance` / `created_at` 一律 `| None`：两列在 DDL 上可空，库里只要有一行空值，写成非空就整片 500（同 C1/C2/C3/C4 的理由）。四个归属字段同样可空，理由见 3.4。

**`segment_id` 在这里必须返回**——与 C4 的口径相反（C4 spec 3.1：「不返回 `segment_id`，它是入参，调用方本来就知道」）。C7 没有路径参数，`segment_id` 不是入参而是**归属信息**：前端要靠它渲染「这条规则属于哪个唱段」，也要靠它跳转到标注页。`demo_id` 同理。

**不返回 `teacher_id`**（同 C4：不按教师隔离，返回只会让人误以为有归属过滤）。

**不返回 `seq`**：唱段标题的信息量大于「第 N 段」，且库里 `segments.title` 解析时必填。后加字段不是破坏性变更，真需要时再加。

**不返回原始 `lyrics_json`**：那是 JSONB 列的内部表示，且形状有三种互不兼容的版本（DOC_ISSUES 第 27 条）。

### 3.2 筛选

| 参数 | 匹配方式 | 在哪一层做 | 缺省 / 空串 |
|---|---|---|---|
| `tag` | **精确相等** | **SQL**（repo 的 `where`） | 当「不筛」 |
| `word` | **与出参 `char` 精确相等**（单字，非模糊、非子串） | **Python**（service） | 当「不筛」 |

**为什么两个参数不在同一层**：`word` 筛的字不存在于表里，得先归一 `lyrics_json` 才算得出来，SQL 层拿不到。这个不对称是本质的，不是随手分的。`tag` 能下推到 SQL 就下推，少捞一批行。

**空串与缺省一视同仁**：`?tag=`（空串）与不带 `tag` 都是「不筛」，由 `request.args.get("tag") or None` 一次收敛。不做 `strip()`——`?word=%20三` 这种畸形输入原样匹配、匹配不上回空列表，比替调用方猜意图更可预期。

**`tag=` 不校验词表**（`ANNOTATION_TAGS` 那六个值）：筛一个词表外的值是**合法查询**，结果为空是正确回答，不是参数错误。词表只为**写入端**把关（C5 spec 的理由是「将来按 tag 派发评测规则时，词表外的值无法处理」——那是写入方的事）。读取端宽容同 C4 出参的不校验口径：库里可能有历史脏数据，接口不能假装它不存在。

出参 `tag` 同样不校验，脏值原样返回。

### 3.3 排序

```
ORDER BY segments.demo_id, annotations.segment_id, annotations.word_index, annotations.id   全升序
```

- 先按**曲目**分组：同一首曲子的规则聚在一起，「集中展示」才读得下去
- 再按**唱段**、再按**字序**：与 C4 的字序一致，在唱段内部读起来与歌词网格同序
- 末位 `id` 保证**稳定**：同一个字可以挂多个 tag（`UNIQUE` 是三列），只按 `word_index` 排的话这两条谁先谁后由 PG 自由决定，同一次查询跑两次可能顺序不同

`demo_id` 为 NULL（`segment_id` 为空的行）在 PG 的 `ORDER BY ... ASC` 下默认**排最后**（`NULLS LAST`），无需显式 `nulls_last()`。这是 PG 的既定行为，不是本接口的额外约定。

### 3.4 `char` 取不到时：回 `null`，**行保留**

`char` 为 `null` 有三种来源，**都不剔除该行**：

| 来源 | 说明 |
|---|---|
| `annotations.segment_id` 为 NULL | DDL 上该列可空 |
| `segments.lyrics_json` 为 NULL | 解析产出的新段落就是这样（DOC_ISSUES 第 20 条）；当前真库 16 行全部非 NULL，但这是常态不是边角 |
| `word_index` 越界 | 歌词在该标注写入后被重新解析过（重跑解析会 `replace_segments` 整批替换） |

同 C4 spec 5.5 的口径：「不做越界过滤——保留在列表里，让已有的脏数据**可见**」。集中展示的价值就在于「全库有多少条规则」这个数字是对的；悄悄少几行等于谎报。

四个归属字段（`segment_id` / `segment_title` / `demo_id` / `demo_title`）在 `segment_id` 为 NULL 时一并是 `null`。

### 3.5 边界

| 情况 | 响应 |
|---|---|
| 有匹配 | `200` + 数组 |
| 无匹配 / 筛词表外的 `tag` / 筛没人标过的字 | `200` + `[]` |
| 学生登录 | `403` + 「需要教师权限」 |
| 未登录 | `401` + 「未登录」 |

**没有 404**：本接口没有路径参数，没有「资源不存在」这一说。`tag=滑音x`（词表外的值）也是 `200 + []` 而不是 404 或 422——见 3.2。

**没有 422**：入参只有两个查询串，都不校验取值。本接口不读 body（`_payload()` 不参与）。

**没有 400**：`?tag=a&tag=b` 这种重复参数 Flask 取**第一个**，不报错。同既有接口。

### 3.6 `created_at` 不做时区换算

同 C4 spec 3.5、`practice_records_repo.py:53`：容器实测 `timezone = Asia/Shanghai`，`annotations.created_at` 落库的**就是北京时间**，直接返回。做 `AT TIME ZONE` 换算会把时间整体推后 8 小时。

> `CLAUDE.md`「数据库接入层」写的 `Etc/UTC` 与实测不符，已登记在 `DOC_ISSUES.md` 第 28.2 条。

## 4. 分层落点

| 层 | 文件 | 改动 |
|---|---|---|
| repo | `app/repositories/annotations_repo.py` | **新增** `list_rules(db, tag)` |
| service | `app/services/library_service.py` | **新增** `annotation_rules(db, tag, word)` |
| schema | `app/schemas/demo.py` | **新增** `AnnotationRuleOut` |
| api | `app/api/demos_segments_annotations.py:147-153` | 占位换实现 |

### 4.1 repo：`list_rules(db, tag) -> list[tuple[Annotation, Segment | None, TeacherDemo | None]]`

```python
select(Annotation, Segment, TeacherDemo)
  .outerjoin(Segment, Annotation.segment_id == Segment.id)
  .outerjoin(TeacherDemo, Segment.demo_id == TeacherDemo.id)
  .where(Annotation.tag == tag)          # tag 为 None 时不加这个条件
  .order_by(Segment.demo_id, Annotation.segment_id, Annotation.word_index, Annotation.id)
```

**一条 SQL 查完，不做 N+1**（同 `get_demo_list` 的取舍；曲目数是个位数、标注数是十位数，`joinedload` 不必上）。

**`outerjoin` 而非 `join`**：`annotations.segment_id` 在 DDL 上可空，内连接会把这类行整条丢掉——集中展示少几行且毫无提示，与 3.4 的口径直接打架。第二个 `outerjoin` 同理：`segments.demo_id` 也可空。

返回**三元组**而不是往模型上挂临时属性：同 `get_demo_list` 返回 `(TeacherDemo, 分段数)` 的理由——「哪些字段来自库、哪些是算出来的」要看得出来。service 层再把三个对象摊平成 dict，api 层直接喂 pydantic。

`tag` 条件用**链式条件构造**（`select(...).where(Annotation.tag == tag if tag is not None else true())` 一类的写法，或先建 `stmt` 再 `stmt = stmt.where(...)`），**不要**写成两层嵌套的 `if`。本文件既有写法是链式一次写完（`list_by_segment`）。

### 4.2 service：`annotation_rules(db, tag, word) -> list[dict]`

```python
def annotation_rules(db, tag, word):
    rows = []
    for ann, seg, demo in annotations_repo.list_rules(db, tag):
        lyric = _lyric_at(seg, ann.word_index)      # 见下
        char = lyric["char"] if lyric else None
        if word is not None and char != word:       # word 筛选在这里
            continue
        rows.append({...})
    return rows
```

- **`char` 必须复用 `_normalize_lyrics`**（不是自己按 `lyrics_json[word_index]` 直接取）：归一函数会**丢弃**非法条目（非对象、`word` 非字符串），直接下标取会拿到错位的字。三处（C3 出参 / C5 写入校验 / 这里）必须同源，否则会出现「C5 说这个下标合法、C7 却取到别的字」
- **`word` 筛选是 `char != word` 跳过**，不是过滤后再拼：一次遍历同时干完归一出参与筛选，少一遍数组
- 唱段被重解析过、`word_index` 越界时 `_lyric_at` 返回 `None` → `char` 为 `null`，**行保留**（3.4）
- `seg` 为 `None`（`segment_id` 空）时同样返回 `None`，四个归属字段一并 `null`
- 不抛任何 `BusinessError`：本接口没有 404 场景

`_lyric_at` 是 service 内的私有小函数（`_lyric_at(seg, index) -> dict | None`），**新增**，`segment_detail` 不动——它要把整份 `lyrics` 给出去，取单个字是另一个需求。

> **不做按 segment 缓存归一结果**：同一唱段的多条标注会重复归一同一份 `lyrics_json`。当前量级是「一个唱段几条标注、歌词十几字」，重复归一的代价远小于多一张缓存表的复杂度。真到几百条再说。

### 4.3 schema：`AnnotationRuleOut`

放在 `AnnotationOut`（`:93`）**之后**，docstring 里写清三件事：

1. 它是 `AnnotationOut` 的**超集**（多 5 个字段：`char` + 4 个归属），**不是**替换关系——C4/C5 仍用 `AnnotationOut`，两者的差别是「面向单个唱段」与「面向全库」
2. `char` 可空的原因（3.4 三种来源）
3. 为什么不返回 `teacher_id` / `seq`

四个归属字段全部 `| None = None`，理由同 `AnnotationOut` 的 `tolerance` / `created_at`（行里只要有一个空值就整片 500）。

### 4.4 api：替换占位

```python
@api_bp.route("/annotations/rules", methods=["GET"])
@login_required
@teacher_required
def annotations_rules():
    tag = request.args.get("tag") or None
    word = request.args.get("word") or None
    rows = library_service.annotation_rules(get_db(), tag=tag, word=word)
    return ok([AnnotationRuleOut.model_validate(r).model_dump(mode="json") for r in rows])
```

**路由路径与装饰器不动**，只换函数体。已有的 `@login_required` 在外层、`@teacher_required` 在内层与 C4/C5/C6 一致（文档 C7 的权限列就是「教师」）。

**`/annotations/rules` 与 C6 的 `/annotations/<int:annotation_id>` 不冲突，且不依赖注册顺序**：`rules` 不是整数，永远匹配不上 `IntegerConverter`（正则 `\d+`）。C6 的 docstring 已经记过这条。

docstring 要写：契约未在文档中定义（指向 `DOC_ISSUES.md` 第 32 条）、`tag` 在 SQL/`word` 在 Python 的分工及其理由、无 404 与 422 的原因。

## 5. 页面调用

**无**。本轮不改任何 `.html`（见 2.3）。前端接入是后续独立任务。

## 6. 验证

项目**没有测试框架**（无 pytest、无 `tests/`），按仓库既有做法手工验证。种子账号 `teacher01` / `stu001`，密码 `xiyun@2026`。

### 6.1 真数据路径（`annotations` 现有 3 行，无需插行）

1. 未登录 → `401`
2. `stu001` → `403`「需要教师权限」（**C7 权限列是教师，必须单独验**）
3. `teacher01` 不带参数 → `200`，正好 **3 条**，每条**恰好 10 个键**：`id / word_index / char / tag / tolerance / created_at / segment_id / segment_title / demo_id / demo_title`
4. 三条的 `char` 依次是 **三 / 同 / 震**，`word_index` 依次是 **3 / 7 / 9**，`tag` 依次是 **归韵 / 拖腔 / 强音**，`id` 依次是 **109 / 110 / 111**
5. 归属字段：`demo_id`=16、`demo_title`=「**《穆桂英挂帅》· 辕门外三声炮**」（注意 `teacher_demos.title` 带书名号与分隔点，不是「穆桂英挂帅」）、`segment_id`=110、`segment_title`=「辕门外三声炮如同雷震」
6. `?tag=拖腔` → **1 条**（id 110）；`?tag=滑音` → `[]`；`?tag=` （空串）→ **3 条**（等同不筛）
7. `?word=三` → **1 条**（id 109）；`?word=同` → 1 条（id 110）；`?word=炮` → `[]`（「炮」是歌词里的字但**没人标注**——这一条用来证明 `word` 筛的是**标注**不是歌词）；`?word=` → 3 条
8. `?tag=拖腔&word=同` → 1 条；`?tag=拖腔&word=三` → `[]`（**两个条件是与关系**，不是或）
9. `?tag=随便`（词表外的值）→ `200` + `[]`，**不是 422**
10. 出参**没有** `teacher_id`、**没有** `seq`、**没有** `lyrics_json`

### 6.2 排序

11. 3 条按 `word_index` 升序：**3, 7, 9**（同一唱段内按字序）
12. **跨唱段排序**要临时插行才验得到（现有 3 条全在 seg 110）。用 `RETURNING id` 抓住 id、**验完按 id 删**，不要按 `segment_id` 一把删：

    ```sql
    INSERT INTO annotations (segment_id, word_index, tag, tolerance, teacher_id)
    VALUES (1, 0, '滑音', 20, 2) RETURNING id;
    ```

    seg 1 属 **demo 1**（「贵妃醉酒·选段」），而 seg 110 属 **demo 16** → 排序应把 **demo_id 小的排前面**（seg 1 那条在最前），证明排序第一关键字真是 `demo_id` 而不是 `id`。**验完按 RETURNING 拿到的 id 删除**，回到 3 条再往下走

### 6.3 脏数据分支（需临时插行）

13. **`word_index` 越界**（seg 110 只有 10 个字，插 `word_index=99`）→ 该行**仍在列表里**、`char` 是 `null`（**不是缺键、不是空串**）、其余字段正常
14. **`segment_id` 为 NULL**（`INSERT ... (word_index, tag, tolerance) VALUES (0,'换气',10)`）→ 该行**仍在列表里**，`char` 与四个归属字段全是 `null`，且排在**最后**（`demo_id` 为 NULL）
15. 插完 13/14 后不带参数 → **5 条**（基线 3 条 + 本轮 2 条；6.2 的临时行此时应已删，若没删就是 6 条，先删掉再验）。5 条这个数证明 `outerjoin` 没把脏行丢掉；`?tag=换气` → 能筛到 seg 为 NULL 的那条

### 6.4 收尾检查

16. `SELECT count(*) FROM annotations` **回到 3**（6.2/6.3 插的临时行全删）
17. 代码里无残留的调试 `console.log`/`print`、无未使用变量
18. `python scripts/check_db.py` 应只剩既有漂移（`demo_versions` + `teacher_demos` 三列）——本轮不改模型与 `schema.sql`

## 7. 收尾

- **`DOC_ISSUES.md` 新增第 32 条**（插在「待核实」之前）：C7 响应契约文档未定义（同 26–28、30、31 条同源），写清本轮采用的口径——字段集与理由、`tag` 在 SQL / `word` 在 Python 的分工、排序四关键字、`char` 为 null 的三种来源、不校验 `tag` 取值、无 404/422——以及待文档方确认项
- 第 32 条里要单独点出**「`word` 筛选被迫读 `lyrics_json`」这条与 C4 spec 3.2 的表面冲突**及其为何不冲突（C7 只有后端一个坐标系；`_normalize_lyrics` 是三处共用的同一函数）
- 第 28 条「待确认」里第 1 问「C7 是否需要更多字段（如教师名、创建时间）」本轮给出回答：**要曲目/唱段/字，不要教师名**
- 三条**待文档方确认**写进第 32 条：
  1. `word=` 是精确等一个字，还是期望模糊/包含匹配？（本轮按精确）
  2. 全库列表不分页是否可行？标注量大起来之后会不会拖垮页面？（本轮不分页）
  3. `?tag=词表外的值` 回 `200 + []` 是否可行，还是期望 `422`？（本轮回空列表）
