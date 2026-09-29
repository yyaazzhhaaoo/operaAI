# 标注列表接口（C4 `GET /api/segments/<id>/annotations`）实现设计

日期：2026-09-29 ｜ 状态：已评审待实现 ｜ 关联：《5-接口清单》2.3 节 C4；`DOC_ISSUES.md` 第 27 条

## 1. 背景与目标

C1 → C2 → C3 这条链已落地，`annotation.html` 的曲目选择器、唱段选择器、歌词网格三层都是真数据。本轮做 C4：取单个唱段的标注规则列表，把标注页的**歌词格子 ✓ 标记**与**「已添加标注规则」列表**接上真数据。

这是《5-接口清单》2.3 节「曲目 / 分段 / 标注」这组的最后一个**读**接口。C5–C7（新增、删除、规则列表管理）本轮不做。

**目标**：

1. `GET /api/segments/<int:segment_id>/annotations` 返回该唱段的标注列表
2. `annotation.html` 的标注列表与歌词格子 ✓ 标记改读真数据
3. 增删改为**明确提示未实现**，不再做本地假增删

**非目标（明确不做）**：

- **不实现 C5 / C6 / C7**。三个占位路由原样保留
- **不做本地假增删**（理由见 5.4）——`annotations` 数组只装真数据
- `TECHNIQUE_DEPS` / `RULE_IMPACT` 两张 mock 表与 `renderDeps()` 不动
- 不改 `schema.sql` / `app/models/*`，不引 Alembic，不引新依赖
- **不按教师隔离**（理由见 3.4）

## 2. 文档给的 vs 库里有的

### 2.1 文档只有一行

| 编号 | 接口 | 权限 | 说明 |
|---|---|---|---|
| C4 | `GET /api/segments/<id>/annotations` | **教师** | 标注规则列表 |

注意权限列是**教师**，与 C1/C2/C3 的「登录」不同——学生端陪练不看标注规则。

同组 C5 的说明里给出了入参字段名：「新增标注（`segment_id`, `word_index`, `tag`, `tolerance`）」。**这行是 C4 出参字段名的唯一依据**（见 3.1）。

### 2.2 库里的 `annotations` 表（当前 **0 行**）

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

**实测真库 0 行，`seed.sql` 里也没有标注的 INSERT**（`grep -n "INSERT INTO annotations" seed.sql` 无输出）。后果有两个：

- 本接口在真实数据上**恒定返回 `[]`**，页面标注列表恒定走空态
- 验证真数据路径**必须临时插行**（见 6.2），验完删除

可空列：`segment_id` / `tolerance` / `teacher_id` / `created_at`；非空列：`id` / `word_index` / `tag`。

两个外键**都在**（实测 `pg_constraint`）：`segment_id → segments(id)`、`teacher_id → users(id)`。**临时插行必须用真实存在的 id**，编一个会当场撞外键：

- `teacher01` 的 `users.id` 是 **2**（不是 1——id 1 已被删除，序列从 2 起）
- 唱段 id 见 6.2 的基线表

### 2.2.1 真库基线（2026-09-29 实测，**与 C3 spec 写的已不同**）

C3 那轮（2026-09-28）记的是 11 个唱段：`1, 78, 79, 80, 102–108`。**现在库里是 16 个**：

| segment.id | 所属 demo | 字数 |
|---|---|---|
| 1 | 1 | 2 |
| 79 | 17 | 28 |
| 80 | 18 | 14 |
| 106 / 107 / 108 | 17 / 17 / 18 | 4 / 3 / 6 |
| **110–119** | **16** | 10 / 11 / 7 / 11 / 6 / 8 / 5 / 5 / 4 / 12 |

**demo 16 被重跑过解析**：旧的 `78`、`102–105` 已删，换成 `110–119`（10 段）。这正是 `library_repo.replace_segments` 的既定行为（先按 `demo_id` DELETE 再 INSERT，重跑不累积脏行）。

**写断言照这张表来；实测对不上就停下来核对，不要改断言去迁就结果。** 本轮验证固定用 **seg 119**（12 字，`word_index` 0–11，首字「谁」，末字「军」）。

### 2.3 前端要的

`renderAnnotations()`（`annotation.html:716`）渲染一行需要五样：`char`（字）、`category`（CSS 类名）、`tag`、`note`（说明文字）、`tolerance`。

`renderLyrics()`（`:602`）用 `annotations.find(a => a.index === idx)` 决定歌词格子要不要标 ✓，其中 `a.index` 是 **`lyrics[]` 数组的下标**。

**库里只有 `tag` 与 `tolerance` 两项**，`char` / `category` / `note` 三样都没有——归属见 3.2。

## 3. 接口契约

```
GET /api/segments/<int:segment_id>/annotations        权限：教师
```

统一信封，`data` 是**数组**：

```json
{"code":0,"message":"ok","data":[
  {"id":7,"word_index":0,"tag":"拖腔","tolerance":30,"created_at":"2026-09-29T10:12:03.417"}
]}
```

### 3.1 出参字段

| 字段 | 来源 | 可空 | 说明 |
|---|---|---|---|
| `id` | `annotations.id` | 否 | C6 删除要用 |
| `word_index` | `annotations.word_index` | 否 | 指向 C3 出参 `lyrics[]` 的下标 |
| `tag` | `annotations.tag` | 否 | 出参**不校验取值**（DDL 上也没有约束） |
| `tolerance` | `annotations.tolerance` | **是** | |
| `created_at` | `annotations.created_at` | **是** | |

`tolerance` / `created_at` 一律 `| None`：两列在 DDL 上可空，库里只要有一行空值，写成非空就整片 500（同 C1/C2/C3 的理由）。

**字段名用 `word_index` 而不是 `index`**：文档给 C5 的入参名就是 `word_index`，出参与它对齐。前端多写一行映射（本来就要把 API 形状转成内部形状，见 5.1），代价为零。`index` 这个词本身也太泛，读不出是「第几个字」。

**不返回** `teacher_id`（不隔离，见 3.4，返回只会误导）、`segment_id`（入参，调用方本来就知道，同 C2/C3 的理由）。

### 3.2 三个前端派生字段不进接口

`char` / `category` / `note` 都不由后端返回，三个理由各不相同：

| 字段 | 谁派生 | 理由 |
|---|---|---|
| `char` | 前端 `lyrics[word_index]?.char` | 后端要返回它就得读 `lyrics_json` 按下标取字。而 C3 的 `_normalize_lyrics`（`library_service.py:148`）会**丢弃**非法条目（非对象、`word` 非字符串），一丢弃就发生**下标错位**，取到的是别的字。库内 142 条当前都合法所以看不出问题——这是个潜伏的错，不引入 |
| `category` | 前端 `TAG_CATEGORY[tag]` | CSS 类名是 UI 措辞。同 C3 对 `note` 词表的口径（C3 spec 3.4）：`NOTE_8` 是领域取值、「1/8 拍」是显示词，后端不发明 UI 语言 |
| `note` | 前端 `annNote(ann)` 现拼 | 它本来就是 mock 拼出来的显示串（旧代码是 `char + "字" + tag + "标注"`），不是数据 |

### 3.3 排序

`ORDER BY word_index, id`——按字序读起来与歌词网格顺序一致；同字挂多个 tag 时按创建序，保证**稳定**（同一次查询跑两次，结果顺序一致）。

### 3.4 不按教师隔离

返回该唱段的**全部**标注，不按 `teacher_id` 过滤。

依据是表自己的约束：`UNIQUE(segment_id, word_index, tag)` **不含 `teacher_id`**——同一唱段的同一个字、同一个 tag 只能存一条，换个教师再标会直接撞唯一约束。这说明这张表的设计前提就是「一个唱段一套全局唯一的标注规则集」，不是每教师一份。

补充理由：同一唱段对学生的评测本就应该用同一套规则；两个教师对同一唱段标注互相看不见会导致重复劳动，而前端页面上也没有「我的标注 / 全部标注」的切换入口。

`teacher_id` 仍照常写入（C5 的事），只是不参与 C4 的过滤。

### 3.5 `created_at` 不做时区换算

`annotations.created_at` 是 `timestamp without time zone`，列默认 `NOW()` 按 server 的 `timezone` 设置落库。**实测容器是 `Asia/Shanghai`**：

```
SHOW timezone;                                → Asia/Shanghai
SELECT now(), now() AT TIME ZONE 'Asia/Shanghai';
  → 2026-09-29 08:58:49.787046+08 | 2026-09-29 08:58:49.787046    （两者相等）
```

即**列里存的就是北京时间**，直接返回、不做 `AT TIME ZONE` 换算——换算会把时间整体推后 8 小时。同 `practice_records_repo.py:53` 已记录的口径。

> `CLAUDE.md`「数据库接入层」一节写的是「容器内 PostgreSQL 的时区是 `Etc/UTC`」，**与实测不符**。登记进 `DOC_ISSUES.md` 第 28 条。`practice_records_repo.py` 的注释才是对的。

### 3.6 边界

| 情况 | 响应 |
|---|---|
| 唱段存在，有标注 | `200` + 数组 |
| 唱段存在，无标注 | `200` + `[]`——**这是当前真库的唯一情况**，不是 404 |
| 唱段不存在 | `404` + `{"code":404,"message":"唱段不存在"}` |
| 路径不是整数（`/api/segments/abc/annotations`） | `404`，**在路由层**由 `<int:segment_id>` 挡下，不进视图 |
| 学生登录 | `403` + 「需要教师权限」 |
| 未登录 | `401` + 「未登录」 |

**404 判定必须显式查 `segments` 表**（复用 `library_repo.get_segment`），不能拿 `annotations` 的查询结果反推：唱段不存在时查标注同样是空数组，若不查 `segments` 就会把「唱段不存在」错答成 `200 + []`，与 C3 的口径当场打架。

## 4. 分层落点

| 层 | 文件 | 改动 |
|---|---|---|
| repo | `app/repositories/annotations_repo.py` | **新增** `list_by_segment(db, segment_id)`：`select(Annotation).where(...).order_by(...)` |
| service | `app/services/library_service.py` | **新增** `segment_annotations(db, segment_id) -> list[dict]` |
| schema | `app/schemas/demo.py` | **新增** `AnnotationOut` |
| api | `app/api/demos_segments_annotations.py:55-59` | 占位改实现；路径 `<id>` → `<int:segment_id>`，形参 `id` → `segment_id` |

**`get_annotations_list` 保留不动**——`dashboard_service.py:79` 在看板汇总里用它算 `annotations_count` / `new_annotations_count`，不是死代码。两个函数查询目的不同（全表计数 vs 按唱段取行），不合并。

service 放 `library_service.py` 而不是新建 `annotation_service.py`：C4 与 C1/C2/C3 同属 2.3 节这一组，且 404 判定要复用同文件的 `library_repo.get_segment`。

service 返回 `list[dict]` 而不是 ORM 对象：同 `demo_list` / `demo_library_list` 的风格，API 层直接喂给 pydantic。

## 5. 页面调用（`annotation.html`）

### 5.1 内部形状统一

`annotations` 数组在 fetch 之后**立刻**映射成内部形状，`renderLyrics` / `renderAnnotations` 只认这一种：

```js
annotations = (data || []).map(r => ({
  id: r.id, index: r.word_index, tag: r.tag,
  tolerance: r.tolerance, createdAt: r.created_at,
}));
```

`index` 是内部名（`renderLyrics:602` 与 `renderAnnotations` 都用它），`word_index` 只出现在网络边界上。映射在 fetch 里一次做完，渲染函数不必知道网络字段名。

**没有 `local` 字段**——不再有本地新增的条目（5.4）。

### 5.2 状态与请求

```js
let annReqToken = 0;   // 竞态守卫，同 lyricReqToken / segReqToken
```

`fetchAnnotations(segmentId)` 照抄 `fetchLyrics`（`:917`）的结构：

- `fetch(\`/api/segments/${segmentId}/annotations\`, { credentials: 'same-origin' })`——同源相对路径，理由同 C1/C2/C3
- 领号在 `await` **之前**，判定在 `await` **之后**（切唱段会连点，先发的慢响应不能覆盖后发的）
- 成功 → 映射进 `annotations`（并把空态文案复位），`renderAnnotations()` + `renderLyrics()`（后者要用新的 ✓ 状态重画格子）
- 失败 → 空态显示 ⚠️ +「标注加载失败」，**不弹 toast、不打断歌词**（标注挂了不该让整个页面不可用，同 C1 的降级口径）
- **不 await**：`switchSegment` 里调它时，高亮与 toast 不等它

**三种空态**与 `lyricsEmptyMsg`（`:914`）同一套做法——两个模块级变量 `annEmptyMsg` / `annEmptyIcon`，`renderAnnotations` 渲染空态时读它们。三种取值：

| 时机 | 图标 | 文案 |
|---|---|---|
| 初始 / 成功但无标注 | 📝 | 暂无标注规则 |
| `switchSegment` 清空后、请求返回前 | 📝 | 标注加载中… |
| 请求失败 | ⚠️ | 标注加载失败 |

布局复用既有的 `.empty-state`（`:720`），只换图标与文案——同一个容器里几种空态外观一致，不新造样式。

**成功与失败都必须复位**这两个变量（成功路径无条件写回默认值），否则「先失败、再切到有数据的唱段」会把上一次的失败文案带过去。

`annCount` 在失败时显示 `(0条)`：`switchSegment` 已经把它清空，失败时不该回填旧数字。

### 5.3 `switchSegment` 扩展（`:887`）

现在只有 `annotations = []; renderAnnotations();`（`:896`）。改成：

1. `annotations = []`，空态文案置成「标注加载中…」，`renderAnnotations()`——旧唱段的标注立刻消失，不能在新数据到达前留在屏幕上
2. `fetchAnnotations(s.id)`，不 await

歌词格子上的 ✓ **不需要额外清理**：`switchSegment` 紧接着会把 `lyrics` 置空并渲染「歌词加载中…」，✓ 随之消失。

### 5.4 增删不再做假动作

`saveAnnotation`（`:692`）与 `deleteAnnotation`（`:734`）改为**只提示、不改状态**。

**`saveAnnotation`**：保留前置校验（没选字 / 没选类型 → `alert`，这是真前置条件）。校验通过后**不 push**，改弹

```js
showToast("info", "写入接口未实现", "C5（POST /api/annotations）尚未实现，本条标注未落库");
```

一并删掉：绿色「✓ 已添加」按钮动画（`:711-713`）——本轮之后它是假话；`RULE_IMPACT` 那句「该技法将影响 N 个唱句」的成功文案——它描述的是一个没发生的动作。`item` / `tolerance` / `existingIdx` / `newAnn` / `impactCount` 随之变成未使用变量，全部删掉。

**`deleteAnnotation`**：`✕` 仍然渲染（同 `fetchDemos` 对无分段曲目「置灰而不隐藏」的口径，把限制摆出来而不是藏起来），点了弹

```js
showToast("info", "删除接口未实现", "C6（DELETE /api/annotations/<id>）尚未实现，标注仍在库中");
```

并且**不从列表移除**。形参 `idx` 随之无用，连同 `:729` 的 `deleteAnnotation(${i})` 与 `:723` 的 `map((ann, i)` 里的 `i` 一起去掉。

**为什么不保留本地假增删**：本地 push 的条目刷新即消失、本地 splice 的条目刷新即回来，而列表里真假混着、外观完全一样。这正是 C3 spec 批评过的「看起来像真数据」。列表只装真数据，代价是标注页本轮的主操作是只读的——这是诚实反映 C5/C6 未实现。

`showToast("info", ...)` 的类型是既有用法（`switchPiece` / `switchSegment` 都这么调），`.toast` 有基础样式、无 `.toast.info` 专用规则，落到默认外观，不需要新增 CSS。

### 5.5 渲染

`renderAnnotations`（`:716`）改四处：

| 位置 | 现状 | 改为 |
|---|---|---|
| `ann.char`（`:725`） | mock 自带 | `annChar(ann)` |
| `tag-${ann.category}`（`:726`） | mock 自带 | `tag-${TAG_CATEGORY[ann.tag] \|\| ""}` |
| `${ann.note \|\| ""}`（`:727`） | mock 自带 | `annNote(ann)` |
| `±${ann.tolerance}c`（`:728`） | 直接拼 | `tolerance` 为 `null` 时**不渲染这一格**（现状会显示「±nullc」） |

新增两个纯函数 + 一张映射表：

```js
// tag → CSS 类名。与 DOM 上按钮的 data-cat 同源（:492-497）
const TAG_CATEGORY = {
  "滑音":"articulation", "归韵":"articulation", "擞音":"articulation",
  "换气":"breath", "强音":"pitch", "拖腔":"rhythm",
};

function annChar(ann) {
  // 兜底 "?" 而不是隐藏：word_index 越界说明库里的标注指向一个不存在的字，
  // 是数据有问题，要让人看见（同 fetchDemos 置灰而不隐藏的口径）
  const item = lyrics[ann.index];
  return item ? item.char : "?";
}

function annNote(ann) { return `${annChar(ann)}字${ann.tag}标注`; }
```

**tag 未知时 `TAG_CATEGORY[tag]` 是 `undefined`，会拼出 `tag-undefined` 类**，落到 `.ann-tag`（`:340`）的基础样式（只有 padding 与字号，无配色）。不兜底成某个已知类——那是给一个不认识的 tag 硬安一个语义配色。

**不做越界过滤**：`word_index` 越界的标注**保留在列表里**、`char` 显示 `?`，不隐藏也不剔除。库里现在 0 行，这个分支只在数据出问题时才命中——那时正需要它可见。

`renderLyrics`（`:602`）的 `hasAnn` 判定**不用改**——`a.index === idx` 对内部形状仍然成立。只改 `:610` 的 title：

```js
if (hasAnn) html += `<div class="ann-indicator" title="${annNote(hasAnn)}">✓</div>`;
```

现状读的是 `hasAnn.note`，真数据没有这个字段，会渲染成「拖腔: undefined」。

## 6. 验证

项目**没有测试框架**（无 pytest、无 `tests/`），按仓库既有做法手工验证。种子账号 `teacher01` / `stu001`，密码 `xiyun@2026`。

### 6.1 接口（`annotations` 表仍是 0 行时）

1. 未登录 → `401`
2. `stu001` → `403`「需要教师权限」（**权限列是教师，与 C1/C2/C3 不同，必须单独验**）
3. `teacher01` + 任意唱段 → `200` + `[]`（不是 404）
4. `segment_id=99999` → `404`「唱段不存在」
5. `/api/segments/abc/annotations` → `404`（路由层，不进视图）
6. 信封是 `{"code":0,"message":"ok","data":[]}`

### 6.2 接口（临时插行）

固定用 **seg 119**（12 字，`word_index` 0–11）。临时插入，**验完必须按 id 删除并确认表回到 0 行**——用 `RETURNING id` 抓住 id 再删，不要按 `segment_id` 一把删（那会连真数据一起删掉）：

```sql
INSERT INTO annotations (segment_id, word_index, tag, tolerance, teacher_id) VALUES
  (119, 0,  '拖腔', 30,   2),
  (119, 5,  '滑音', NULL, 2),   -- tolerance 为 NULL
  (119, 2,  '换气', 0,    2),   -- tolerance 边界下限
  (119, 2,  '强音', 100,  2),   -- 同字不同 tag（验排序稳定性）
  (119, 11, '归韵', 60,   2);   -- 末字「军」（seg 119 的 lyrics 长 12，末下标 11）
```

7. seg 119 → 5 条，每条**恰好 5 个键**：`id / word_index / tag / tolerance / created_at`
8. 排序是 `word_index` 升序：`0, 2, 2, 5, 11`；两条 `word_index=2` 的按 `id` 升序
9. `tolerance` 为 `NULL` 的那条出参是 `null`（不是 `0`，也不是缺键）
10. seg 1（无标注）→ `[]`——确认过滤真按 `segment_id` 生效，不是全表返回
11. seg 110（同在 demo 16，但无标注）→ `[]`
12. 出参**没有** `teacher_id`、**没有** `segment_id`、**没有** `char` / `category` / `note`

### 6.3 页面（用 `/browse` 技能）

13. 登录 `teacher01` → 标注页 → 默认落在 demo 1 → seg 1：列表「暂无标注规则」，歌词格子无 ✓
14. 切到 **demo 16**（《穆桂英挂帅》· 辕门外三声炮，**10 段**）→ 切到**第 10 段**「谁料想我五十三岁又管三军」（seg 119，6.2 插了标注的那个）→ 列表 5 条，每条显示 字 + tag 色块 + 「N字X标注」，末列是 `±Nc`（`tolerance` 为 `NULL` 的那条除外，见 16）；`annCount` 是 `(5条)`
15. **歌词格子 ✓**：`word_index` 为 0 / 2 / 5 / 11 四个格子有 ✓（对应「谁」「想」「十」「军」），hover 的 title 是「谁字拖腔标注」这类（**不是 `undefined`**）
16. `tolerance` 为 `NULL` 那条**不显示** `±Nc`（不是「±nullc」）
17. 列表里 5 条全是真数据：刷新页面后仍是这 5 条，没有任何只存在于内存的条目
18. 点「添加标注」→ 选字 + 选类型 → **列表条数不变**，弹「写入接口未实现」toast，按钮没有绿色「✓ 已添加」动画
19. 点某条 ✕ → **该条仍在列表里**，弹「删除接口未实现」toast
20. **竞态**：快速连点两个唱段 → 最终列表属于**后点**的那个
21. **降级**：临时把 URL 改错 → 列表显示 ⚠️ +「标注加载失败」、`annCount` 是 `(0条)`，**歌词网格不受影响**、页面其余部分可用；**验证完改回并确认无残留**

### 6.4 收尾检查

22. `SELECT count(*) FROM annotations` **回到 0**（临时行全删）
23. 代码里无残留的调试 `console.log`、无被改错的 URL、无未使用变量

## 7. 收尾

- **`DOC_ISSUES.md` 新增第 28 条**（插在「待核实」之前）：C4 响应契约文档未定义（同 26/27 条同源），写清本轮采用的口径——字段集、`word_index` 沿用 C5 入参名、三个派生字段不进接口的理由、不按教师隔离、`created_at` 不换算时区——以及待文档方确认项
- 同一条内登记 **`CLAUDE.md` 的时区记载与实测不符**（`Etc/UTC` vs 实测 `Asia/Shanghai`），附实测命令
- `annotation.html:538` 与 `:555` 两句「待 C4」的注释本轮之后是假话，一并更新
- `python scripts/check_db.py` 应只剩既有漂移（`demo_versions` + `teacher_demos` 三列）——本轮不改模型与 `schema.sql`
