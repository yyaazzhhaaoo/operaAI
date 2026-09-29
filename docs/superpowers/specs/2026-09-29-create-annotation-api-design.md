# 新增标注接口（C5 `POST /api/annotations`）实现设计

日期：2026-09-29 ｜ 状态：已评审待实现 ｜ 关联：《5-接口清单》2.3 节 C5；`DOC_ISSUES.md` 第 30 条

## 1. 背景与目标

C1 → C2 → C3 → C4 已落地：标注页的曲目选择器、唱段选择器、歌词网格、标注列表四层都是真数据。C4 那轮把增删改成了「只提示、不改状态」（C4 spec 5.4），标注页因此是**只读**的。

本轮做 C5：把「添加标注」按钮接上真写入链路，让老师标的东西真落 `annotations` 表。

**目标**：

1. `POST /api/annotations` 写一行标注并返回新建行
2. `annotation.html` 的「添加标注」改调真接口，成功后列表与歌词 ✓ 标记同步更新

**非目标（明确不做）**：

- **不实现 C6（DELETE）/ C7（`/annotations/rules`）**。两个占位路由原样保留，`deleteAnnotation` 维持「删除接口未实现」的提示不动
- 不做批量新增、不做修改已有标注（改 tag / 改 tolerance 都得删了重标，C6 落地后才有意义）
- `TECHNIQUE_DEPS` / `RULE_IMPACT` 两张 mock 表与 `renderDeps()` 不动
- 不改 `schema.sql` / `app/models/*`，不引 Alembic，不引新依赖
- **不按教师隔离**：同 C4 spec 3.4，表的设计前提是「一个唱段一套全局唯一的规则集」

## 2. 文档给的 vs 库里有的

### 2.1 文档只有一行

| 编号 | 接口 | 权限 | 说明 |
|---|---|---|---|
| C5 | `POST /api/annotations` | **教师** | 新增标注（`segment_id`, `word_index`, `tag`, `tolerance`） |

括号里那四个字段名是**唯一的入参依据**，请求体形态、响应体、错误码文档一概未定义。

### 2.2 库里的 `annotations` 表

`schema.sql:76-85`（同 C4 spec 2.2，此处只列本轮新增用到的约束）：

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

本轮直接相关的三条：

| 约束 | 对 C5 的意义 |
|---|---|
| `UNIQUE(segment_id, word_index, tag)` | 重复新增**必然撞约束**，不是一个理论上可能的分支。处理方式见 3.4；也因此**不含 `teacher_id`**，换个教师再标同字同 tag 一样撞 |
| `CHECK (tolerance BETWEEN 0 AND 100)` | 越界会以 `IntegrityError` 冒出来变成 500。必须在入参层挡下（3.3） |
| `tag VARCHAR(10)` | 超长同样 500。词表最长 2 字，限制取值后这条自动满足（3.3） |

**表当前 0 行**（同 C4 spec 2.2，`seed.sql` 无标注 INSERT）。含义与 C4 一样：验证真数据路径必须临时插行，验完按 id 删除。

`teacher_id` 的外键指向 `users`，`teacher01` 的 id 是 **2**（id 1 已删除，序列从 2 起）——写断言时照这个来。

### 2.3 前端已有的东西

`annotation.html` 的写入面板（`:478-514`）已经齐全，本轮**不动 DOM**：

- 六个类型按钮 `data-tag` / `data-cat`（`:492-497`），点击写进 `selectedTag = { tag, cat }`（`:656`）
- 容忍度滑块 `#toleranceSlider`，`min=0 max=100 value=30`（`:502`）
- 「添加标注」按钮 `#saveAnnotate`，`onclick="saveAnnotation()"`（`:513`）

`saveAnnotation()`（`:691`）当前是占位：校验通过后弹「写入接口未实现」。`selectedIndex`（点的第几个字）与 `selectedTag.tag` 正好就是 `word_index` 与 `tag` 两个入参，滑块值就是 `tolerance`。

## 3. 接口契约

```
POST /api/annotations        权限：教师
```

### 3.1 入参

JSON body：

| 字段 | 类型 | 必填 | 约束 | 校验落点 |
|---|---|---|---|---|
| `segment_id` | int | 是 | 必须存在于 `segments` | service（404 判定复用 `library_repo.get_segment`） |
| `word_index` | int | 是 | `0 <= word_index < 归一后歌词长度` | pydantic 只判 `>= 0`，上界在 service |
| `tag` | str | 是 | 六个值之一：滑音 / 归韵 / 换气 / 强音 / 拖腔 / 擞音 | pydantic |
| `tolerance` | int \| null | 否，缺省 `null` | `0 <= tolerance <= 100` | pydantic |

**`teacher_id` 不进参**：从会话取（`current_user_id()`）。让客户端指定归属等于开一个「以别人的名义标注」的越权入口，而接口没有任何理由需要它。

**`tolerance` 可选而不是必填**：列在 DDL 上可空，C4 出参也已允许 `null`（`AnnotationOut.tolerance: int | None`）。前端滑块总有值，但接口不必替调用方决定这个值一定存在。

### 3.2 出参

`data` 是**新建的那一行**，形状与 C4 列表行**完全相同**（复用 `AnnotationOut`）：

```json
{"code":0,"message":"ok","data":
  {"id":42,"word_index":3,"tag":"拖腔","tolerance":30,"created_at":"2026-09-29T10:12:03.417"}}
```

**复用 `AnnotationOut` 而不是新建一个 `AnnotationCreatedOut`**：同一个资源的同一形状，分成两个类只会在字段漂移时多一处要改。代价是 `AnnotationOut` 的 docstring 要补一句「C5 的响应也用它」——它现在叫「标注列表行」。

**成功回 200 不回 201**：`ok()` 固定 200（`app/response.py:26`），`auth/login` 等既有 POST 也全走 200。为一个接口单独引入 201 会让「code 与 HTTP 状态码一致」这条约定多一个例外，而前端并不区分。

**为什么返回整行而不是只回 `id`**：前端要拿它直接插进列表（5.3），只回 `id` 就得再拉一次整表才能知道 `created_at`（服务端生成的）与排序位置。

`teacher_id` / `segment_id` 都**不出参**：前者不隔离、返回只会误导（同 C4 spec 3.1）；后者是入参，调用方本来就知道（同 C2/C3/C4）。`char` / `category` / `note` 三个派生字段同样不进（同 C4 spec 3.2：分别由前端从 lyrics、`TAG_CATEGORY`、`annNote()` 得到）。

### 3.3 词表与长度校验

**`tag` 限定为六个已知值**。依据有三条：

1. 前端只有这六个按钮（`:492-497`），页面产不出别的值
2. `app/models/annotation.py:15` 的注释就是「tag 取值：滑音/归韵/换气/强音/拖腔/擞音」——这是模型的既定词表
3. 将来按 tag 派发评测规则时，一个后端词典里不存在的 tag 无法处理。让它静默入库等于把问题推迟到评测链路

顺带解决 `VARCHAR(10)` 超长导致的 500：六个值最长 2 字。

**注意这不与 C4 出参的口径矛盾**：C4 spec 3.1 明确出参「不校验取值」，那是为了让历史脏数据可读；写入端把关、读取端宽容是标准做法，两者针对的是不同的方向。

**`word_index` 上界校验**：按 C3 的 `_normalize_lyrics(seg.lyrics_json)` 长度判越界，超界回 422。

- 用**同一个归一函数**是刻意的：C3 出参的长度、前端歌词网格渲染的字数、C5 的合法下标范围三者必须同源，否则会出现「接口说越界、页面上却有这个字」这种自相矛盾
- 唱段无歌词（`lyrics_json` 为 NULL，解析产出的新段落就是这样）时长度为 0，任何下标都 422 —— 与页面自洽：那时网格里一个字都没有，点不出 `selectedIndex`
- C4 spec 5.5 对出参采取「越界保留、首列显示 `?`」是为了让**已有的**脏数据可见；写入端挡住是为了**不再生产**脏数据。两者不冲突

**词表用显式 `field_validator` 抛中文 `ValueError`，不用 `Literal[...]`**：pydantic 对 `Literal` 的报错 type 是 `literal_error`，`app/common/errors.py` 的 `_MSG_CN` 里没有这个映射，会回退成英文原文 `Input should be '滑音', '归韵', ...`，直接透给中文 UI。`_MSG_CN` 的注释里已经把「自定义 validator 抛的 ValueError 本身就是中文」列为既定的第二种处理路径，本项目正是这么用的。

### 3.4 重复：回 409

同一个 `(segment_id, word_index, tag)` 已存在时回

```
409 + {"code":409,"message":"该字已标注此技法"}
```

**为什么不是幂等覆盖 `tolerance`**：「新增」接口带上更新语义，会让调用方无法从响应判断这一次到底新建了还是改了（两者都回 200 + 一行）。而且 tag 仍然改不了（换个 tag 是新行、撞不到约束），覆盖式语义只能覆盖一半，反而更难理解。

**为什么不是 400**：`400` 在本项目表示「参数本身不合法」，而重复的入参是完全合法的，只是与已有数据冲突。`409` 表达冲突，且项目里已有先例（`analyze_service.py:156,158` 用 409 表示与当前任务状态的冲突）。

**判定用「前置查询 + 兜底 catch `IntegrityError`」两步**：

```python
existing = annotations_repo.get_one(db, segment_id, word_index, tag)
if existing is not None:
    raise BusinessError(409, "该字已标注此技法")
try:
    ann = annotations_repo.add(db, ...)
except IntegrityError:
    db.rollback()
    raise BusinessError(409, "该字已标注此技法") from None
db.commit()
```

- 前置查询负责常见路径，逻辑直白、不依赖异常控制流
- `IntegrityError` 兜底只处理两个请求同时插入的窗口。没有它，这个窗口会漏成 500
- 两者消息完全相同（入参已知，不需要从异常里反推是哪个字），所以兜底不会给出更差的信息
- `db.rollback()` 是必需的：flush 失败后会话处于不可用状态，不回滚就不能再执行任何语句（而 `get_db()` 只负责在 teardown 时 `close()`，不会替这里回滚）

`IntegrityError` 能安全地一律解释为「唯一约束冲突」，是因为其余约束都已在前面挡下：`segment_id` 的外键由 404 判定保证、`teacher_id` 来自有效会话、`tolerance` 的 CHECK 由 pydantic 保证、`word_index` / `tag` 的 NOT NULL 由 pydantic 必填保证。这一点要写进代码注释——将来加了新约束就得回头重看这个假设。

**已知影响：C6 未实现时标错了没法撤。** 标错 tag 只能等 C6（本轮明示不做）。这不是 C5 引入的问题，但要在页面提示里说清楚（5.4）。

### 3.5 边界

| 情况 | 响应 |
|---|---|
| 成功 | `200` + 新建行 |
| 同字同 tag 已存在 | `409` +「该字已标注此技法」 |
| `segment_id` 不存在 | `404` +「唱段不存在」 |
| `word_index` 越界 | `422` + 中文说明 |
| `tag` 不在词表 | `422` + 中文说明 |
| `tolerance` 越界 | `422` + 中文说明 |
| 缺必填字段 / 类型不对 | `422` + 中文说明（`_MSG_CN` 的既有映射） |
| 请求体不是 JSON / 无 `Content-Type` | `422`（`_payload()` 把 415 压成 `{}`，再由 pydantic 报「必填」，同 `auth.py:27-34`） |
| 学生登录 | `403` +「需要教师权限」 |
| 未登录 | `401` +「未登录」 |

**校验顺序**：pydantic（API 层）先于 service 跑。所以「`segment_id` 不存在 **且** `tag` 非法」回的是 422 而不是 404。参数合法性优先于资源存在性是常规做法，但要说清楚——调用方如果按「先 404 后 422」写分支会踩到。

### 3.6 `created_at` 不做时区换算

同 C4 spec 3.5：容器 `timezone` 实测是 `Asia/Shanghai`，`created_at` 列里存的就是北京时间，直接返回。换算会整体推后 8 小时。

## 4. 分层落点

| 层 | 文件 | 改动 |
|---|---|---|
| repo | `app/repositories/annotations_repo.py` | **新增** `get_one(db, segment_id, word_index, tag)`、`add(db, *, segment_id, word_index, tag, tolerance, teacher_id)` |
| schema | `app/schemas/demo.py` | **新增** `AnnotationIn` 与模块级 `ANNOTATION_TAGS`；`AnnotationOut` docstring 补 C5 |
| service | `app/services/library_service.py` | **新增** `create_annotation(db, *, segment_id, word_index, tag, tolerance, teacher_id) -> dict` |
| api | `app/api/demos_segments_annotations.py:72-76` | 占位改实现；形参从无到无（入参在 body 里），加 `_payload()` 助手 |

**repo 层**：

- `get_one` 用 `select(...).where(三个条件)` + `db.scalar()`，与 `list_by_segment` 同一写法
- `add` 只 `db.add()` + `db.flush()`，**不 commit**（`app/repositories/__init__.py:5` 的既定约定：写操作只 flush 拿 id、触发约束检查，事务边界在 service）。flush 后 `ann.id` 与 `ann.created_at` 都已由 RETURNING 填好，可以立刻组装响应

**service 层**：

- 签名用**关键字参数**（`*`）：四五个字段的位置参数调用方一眼看不出谁是谁，`create_annotation(db, 119, 3, "拖腔", 30, 2)` 里 `3` 和 `30` 极易写反
- 顺序：查 segment（404）→ 归一歌词判越界（422）→ 查重复（409）→ 插入
- 事务边界在这层：`db.commit()`，同 `auth_service.change_password:48`、`library_service.py:115`
- 返回 `dict` 而不是 ORM 对象：同 `segment_annotations` / `demo_list` 的风格，API 层直接喂给 pydantic

**api 层**：

- 加一个本文件的 `_payload()`，与 `auth.py:27` / `audio_analyze.py:28` 同一个实现（`request.get_json(silent=True) or {}`）——API 层只做「校验入参 → 调 service → 组装响应」，不写业务规则
- `AnnotationIn.model_validate(_payload())` → `library_service.create_annotation(...)` → `ok(AnnotationOut.model_validate(row).model_dump(mode="json"))`
- 沿用既有的 `@login_required` + `@teacher_required` 叠放（`login_required` 在外），与本文件 C4/C6/C7 三个路由一致

**`ANNOTATION_TAGS` 放在 schema 层**（`app/schemas/demo.py`）：它是入参的合法取值域，属于接口契约的一部分，不是业务规则。放 service 会让 API 层的校验反过来依赖业务层。

## 5. 页面调用（`annotation.html`）

### 5.1 `saveAnnotation` 改真写入

```js
async function saveAnnotation() {
  if (selectedIndex < 0 || !selectedTag) { alert("请先选择一个字和标注类型"); return; }
  const seg = segments[currentSegIdx];
  if (!seg) return;
  const btn = document.getElementById("saveAnnotate");
  if (btn.disabled) return;              // 防连点：第二次请求必然撞 409
  btn.disabled = true;
  btn.textContent = "添加中…";
  let row;
  try {
    const r = await fetch('/api/annotations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        segment_id: seg.id, word_index: selectedIndex,
        tag: selectedTag.tag, tolerance: Number(document.getElementById("toleranceSlider").value),
      }),
    });
    const body = await r.json();
    if (!r.ok || body.code !== 0) throw new Error(body.message || String(r.status));
    row = body.data;
  } catch (e) {
    showToast("error", "添加失败", e.message);
    return;
  } finally {
    btn.disabled = false;
    btn.textContent = "添加标注";
  }
  ...
}
```

几条约束：

- **`segments[currentSegIdx]` 取 `segment_id`**，不用闭包变量另存一份——`currentSegIdx` 是当前渲染的那个唱段，两者不会不同步
- **`credentials: 'same-origin'` + 同源相对路径**：与 C1–C4 同一个坑，写成跨源地址时 Cookie 不带、后端只看到空 session 并回 401
- **按钮防连点**：连点两次会发两个相同请求，第二个必然 409，而用户看到的是自己造成的报错。`disabled` 期间按钮文案改「添加中…」，`finally` 里恢复
- **失败只弹 toast、不改本地状态**：`annotations` 数组只装服务端确认过的行（C4 spec 5.4 的既定口径）。失败时列表保持原样，不会出现「看着加上了、刷新就没了」

### 5.2 成功后的本地更新

```js
  annotations.push({
    id: row.id, index: row.word_index, tag: row.tag,
    tolerance: row.tolerance, createdAt: row.created_at,
  });
  // 排序按 (index, id)，与 C4 的 ORDER BY word_index, id 一致——本地插完
  // 仍与「重新拉一次」的结果相同，不然新条目会跳到最后一行
  annotations.sort((a, b) => (a.index - b.index) || (a.id - b.id));
  annEmptyMsg = "暂无标注规则";
  annEmptyIcon = "📝";
  renderAnnotations();
  renderLyrics();          // 歌词格子的 ✓ 由 renderLyrics 画，必须重画
  clearTagSelection();     // 见 5.3
  showToast("success", "已添加标注", annNote(annotations.find(a => a.id === row.id)));
```

**为什么本地插入而不是重新拉列表**：写入已经成功了，若紧接着的 GET 失败（网络抖动、后端重启），页面会显示「标注加载失败」——那是在说一件没发生的事。用返回值插入，成功就是成功。排序规则只有一条（`word_index, id`），本地复现的代价可忽略。

**为什么不用 fetch 后的那套映射函数**：C4 spec 5.1 的映射写在 `fetchAnnotations` 内部。这里也就三行，不为了复用而抽函数——抽出来会多一个「只有两个调用方、字段还一模一样」的间接层。

**唯一例外：上一次列表没加载成功时，改用重新拉取。** 若 C4 那次 GET 失败过（列表停在「标注加载失败」），本地插入会让页面只剩刚写的这一条——看起来像「这个唱段只有一条标注」，与 C4 反复强调的「看起来像真数据」是同一个毛病。加一个模块级 `annLoaded` 标志解决：

- `fetchAnnotations` 成功时置 `true`、失败与 `switchSegment` 清空时置 `false`
- 写入成功后：`annLoaded` 为 `true` → 走本地插入（5.2 的主路径）；为 `false` → 调 `fetchAnnotations(seg.id)` 让服务端给权威结果

这样「本地插入」只在**已知本地列表是完整的**时候发生。分支只有两行，且两种情况都不会让列表说谎。

### 5.3 成功后清 tag、不清字

成功之后：

- `selectedTag = null`、六个类型按钮全部去掉 `active`、`depsPanel` 收起（`renderDeps` 面板是跟着 tag 走的，tag 清空了面板还开着就是自相矛盾）
- **`selectedIndex` 保持不动**，字仍然选中、`lyric-cell` 的 `selected` 高亮保留

理由：`UNIQUE(segment_id, word_index, tag)` 是三列的，**同一个字挂多个 tag 是合法的**。保留选中字，老师可以接着给同一个字标下一个技法，不用重新点一次格子。清 tag 是因为手滑连点同一个类型才是最常见的误操作，而它恰好会撞 409。

抽一个 `clearTagSelection()` 小函数：`selectChar()`（`:633-635`）里已经有同样三行（清 `selectedTag`、去 active、收面板），两处调用同一个函数，不必写两遍。

### 5.4 提示文案与已知限制

失败 toast 直接显示后端 `message`，不自己编文案：

- 409 →「该字已标注此技法」
- 422 → 后端的中文说明。注意两种 422 的消息**形态不同**：pydantic 抛的带字段名前缀（`tag: 取值必须是 …`），service 抛的 `BusinessError` 不带（`该唱段的字数为 12，word_index 超出范围`）——`_MSG_CN` 那套前缀是 pydantic 的 `loc` 拼的，`BusinessError` 走的是另一条 handler。要带字段名的场合得自己在消息里写全，别指望 handler 补
- 401 →「未登录」（页面右上角登录条已在会话过期时兜底跳转，这里只是把它显示出来）

**`showToast` 需要支持 `error` 类型**：现有实现（`:745`）只有 `type === "success"` 走 ✅、其余一律 ℹ️。错误提示配 ℹ️ 不合适。改法：把图标改成一张小映射表，未知 type 回退 ℹ️。`.toast.error` 若无专用样式则落到 `.toast` 基础外观，与 C4 对 `.toast.info` 的处理一致——不新增 CSS。

**「标错了撤不掉」要在页面上说清楚**：C6 未实现，标错 tag 只能等 C6。这与 C4 那轮 `deleteAnnotation` 弹「删除接口未实现」是同一个口径——把限制摆出来，不藏。

### 5.5 注释与样式

- `annotation.html:554` 的「当前唱段的标注（C4 出参，已映射成内部形状）」要改成「C4 列表 + C5 返回值」——内部形状现在有两个来源
- `:693-695` 那段「C5 未实现」的注释连同提示一起删掉
- **不需要新增 CSS**：`.btn-primary:disabled`（`:170`，`opacity:0.5; cursor:not-allowed; transform:none; box-shadow:none`）与 `.toast` 基础样式都已存在，禁用态与 `error` toast 直接落上去即可。`.toast.error` 没有专用配色规则，落到 `.toast` 基础外观——与 C4 对 `.toast.info` 的处置一致

## 6. 验证

项目**没有测试框架**（无 pytest、无 `tests/`），按仓库既有做法手工验证。种子账号 `teacher01` / `stu001`，密码 `xiyun@2026`。

### 6.1 接口（`annotations` 表仍是 0 行时）

固定用 **seg 119**（12 字，`word_index` 0–11，末字「军」；C4 spec 2.2.1 的基线表）。

1. 未登录 → `401`
2. `stu001` → `403`「需要教师权限」
3. `segment_id=99999` → `404`「唱段不存在」
4. `word_index=12`（seg 119 只有 0–11）→ `422`，且**库里没有新增行**
5. `word_index=-1` → `422`（pydantic 的 `ge=0`）
6. `tag="乱写"` → `422`，消息是**中文**（不是 `Input should be ...`）
7. `tolerance=101` 与 `tolerance=-1` → `422`
8. 缺 `tag` → `422`「必填」
9. 无 `Content-Type: application/json` → `422`（不是 415）
10. 非法 body + `segment_id=99999` → `422`（**不是 404**，验 3.5 的校验顺序）
11. 合法入参（`segment_id=119, word_index=0, tag=拖腔, tolerance=30`）→ `200`，`data` **恰好 5 个键**：`id / word_index / tag / tolerance / created_at`，**没有** `teacher_id` / `segment_id` / `char` / `category` / `note`
12. 同一条**原样重发** → `409`「该字已标注此技法」，且库里仍只有一行
13. `tolerance` 缺省（不传该字段）→ `200`，`data.tolerance` 是 `null`（不是 0）
14. `tolerance=0` 与 `tolerance=100` → `200`（边界值收，DDL 的 CHECK 是闭区间）
15. 同字换 tag（`word_index=0, tag=滑音`）→ `200`，库里两行（验唯一约束是三列）
16. 数据库核对：`teacher_id` 落的是 **2**、`created_at` 非空且是北京时间
17. **验完按 id 删除**（`DELETE FROM annotations WHERE id IN (...)`，用 `RETURNING id` 抓住），确认 `SELECT count(*)` **回到 0**

临时插入的这几行正好可以顺带回归 C4：seg 119 的列表长度、排序、`tolerance: null` 那条。

### 6.2 页面（用 `/browse` 技能）

18. 登录 `teacher01` → 标注页 → demo 16（《穆桂英挂帅》· 辕门外三声炮，10 段）→ 第 10 段（seg 119）
19. 点一个字 → 选一个类型 → 点「添加标注」→ **列表立刻多一条**、条数 +1、该字格子出现 ✓ 且 title 是「X字Y标注」
20. **刷新页面** → 那条**仍在**（这一条是「真落库」的唯一证明）
21. 同一个字、同一个类型再点一次 → **列表条数不变**、弹「添加失败 / 该字已标注此技法」
22. 同一个字、**换一个类型** → 成功，列表多一条，同字两行
23. 成功后：类型按钮全部取消高亮、deps 面板收起，**字仍然选中**（同一个字可以接着标下一个）
24. **连点按钮**：观察 Network，只发出**一次**请求；按钮期间显示「添加中…」
25. 失败路径：临时把 URL 改错 → 弹「添加失败」、**列表条数不变**、页面其余部分可用；**验证完改回并确认无残留**
26. **降级后的写入**（验 5.2 的 `annLoaded` 分支）：用第 25 条那个坏 URL 让列表停在「标注加载失败」，改回后**不刷新页面**直接添加一条 → 列表显示的是**服务端返回的完整列表**（含此前已有的标注），不是只有新写的那一条
27. 竞态回归：写成功之后快速切唱段 → 最终列表属于后点的那个唱段（本地插入没有破坏 `annReqToken` 的守卫）

### 6.3 收尾检查

28. `SELECT count(*) FROM annotations` 回到 **0**（临时行全删）
29. 代码里无残留的调试 `console.log`、无被改错的 URL、无未使用变量
30. `python scripts/check_db.py` 只剩既有漂移（`demo_versions` + `teacher_demos` 三列）——本轮不改模型与 `schema.sql`

## 7. 收尾

- **`DOC_ISSUES.md` 新增第 30 条**（插在「待核实」之前）：C5 只有一行描述、请求与响应契约全未定义（同 26/27/28 条同源）。写清本轮采用的口径——入参四字段与各自约束、`teacher_id` 取自会话不进参、出参复用 C4 列表行形状、重复回 409、成功回 200 而非 201、参数校验先于资源存在性判定——以及待文档方确认项
- `annotation.html` 里 `:554` / `:693-695` 两处注释按 5.5 更新
- C6 / C7 的两个占位路由**原样保留**，它们的「未实现」提示不动
