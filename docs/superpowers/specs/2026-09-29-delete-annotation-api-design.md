# 删除标注接口（C6 `DELETE /api/annotations/<id>`）实现设计

**状态**：设计已与用户确认（2026-09-29），待写实施计划
**前置**：C5 已完成并提交（`c9fb17f` / `ece9216` / `44e0df8` / `4a7c58d`），spec 见 `docs/superpowers/specs/2026-09-29-create-annotation-api-design.md`

## 1. 背景与目标

`app/api/demos_segments_annotations.py` 里 C6 是一个占位路由（`return ok(id)`），`annotation.html` 的 ✕ 按钮点了只弹一句「C6 尚未实现」。本设计把这条链路接通。

C6 是**唯一**能撤回一条错标规则的手段（DOC_ISSUES 第 30 条「待确认」第 4 点已预告）。在它实现之前，标注页标错一个 tag 只能靠直接改库。

目标：

1. `DELETE /api/annotations/<id>` 真删库，成功回统一信封
2. `annotation.html` 的 ✕ 接真删除，删除前有确认，失败不改本地列表
3. 契约中所有文档未定义的部分，登记进 `DOC_ISSUES.md` 第 31 条

## 2. 文档给的 vs 库里有的

### 2.1 文档只有一行

《5-接口清单-V1.0》2.3 节里 C6 的全部内容：

```
C6 | DELETE /api/annotations/<id> | 教师 | 删除标注（功能 9.7）
```

《3-功能清单V1.0》9.7 的全文是「删除标注 / 移除规则」。

**请求体、响应体、状态码、删不存在的 id 回什么，全未定义**——与 C4（第 28 条）、C5（第 30 条）同源。

### 2.2 库里没有牵连

`schema.sql` 里 `annotations` 的 DDL：

```sql
CREATE TABLE annotations (
  id SERIAL PRIMARY KEY,
  segment_id INT REFERENCES segments(id),
  word_index INT NOT NULL,
  tag VARCHAR(10) NOT NULL,
  tolerance INT CHECK (tolerance BETWEEN 0 AND 100),
  teacher_id INT REFERENCES users(id),
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(segment_id, word_index, tag)
);
```

`grep -n "REFERENCES annotations" schema.sql` **无结果**：没有任何外键指向 `annotations.id`，删一行不会级联、不会让其它表出现悬空引用。这是本接口能做「真删」而不是「软删」的前提（若将来有表引用它，要回头重看这一条）。

`existing` 代码里也没有任何删除先例：`grep -rn "def delete\|\.delete(" app/repositories/ app/services/ app/api/` 无结果。本接口是第一个，仓储层的删除形状由它定下。

### 2.3 前端已有的东西

- `annotation.html:808`：`<div class="ann-del" onclick="deleteAnnotation()">✕</div>`，在 `renderAnnotations()` 的 `annotations.map` 里渲染。**不传 id**——这是页面侧要改的第一处。
- `annotation.html:813`：`deleteAnnotation()` 是占位，只弹 toast。
- 本地 `annotations` 数组的元素形状（`fetchAnnotations` 与 `saveAnnotation` 两处同源）：

  ```js
  { id, index, tag, tolerance, createdAt }
  ```

  `id` 是库里的自增主键，`index` 是 `word_index` 映射来的。**删除要的是 `id`，不是 `index`**。
- `annNote(ann)`（`:786`）拼「谁字拖腔标注」，`annChar(ann)`（`:779`）按下标取字、越界兜底 `?`。确认弹窗的文案复用它俩。
- 项目里唯一的删除确认先例是 `cdm_report.html:1504` 的原生 `confirm(...)`。

## 3. 接口契约

### 3.1 路径与权限

| 项 | 口径 |
|---|---|
| 方法 / 路径 | `DELETE /api/annotations/<int:annotation_id>` |
| 请求体 | 无 |
| 装饰器 | `@login_required` 外层 + `@teacher_required` 内层（与 C4/C5/C7 同组，权限列都是「教师」） |
| 未登录 | `401` +「未登录」 |
| 非教师 | `403` +「需要教师权限」 |
| 成功 | `200` + `{"code":0,"message":"ok","data":null}` |
| 不存在 | `404` +「标注不存在」 |
| 路径非整数 | `404` +「接口不存在」，**路由层拦下，不进视图** |

### 3.2 为什么改成 `<int:annotation_id>`

原占位是 `@api_bp.route("/annotations/<id>")`，用的是**默认字符串转换器**。改为 `<int:annotation_id>` 有两个收益：

1. 与 C2/C3/C4 的 `<int:...>` 一致。全项目只有这一条业务路由用字符串，是占位时随手写的。
2. 非整数的畸形输入在**路由层**就 404，不进视图，也就没有变成 500 的机会。

**已实测**（用 C4 现成的 `<int:segment_id>` 打真库，未带 Cookie）：

```
GET /api/segments/abc/annotations → 404
GET /api/segments/-1/annotations  → 404     # Werkzeug 的 IntegerConverter 正则 \d+，不收负号
GET /api/segments/119/annotations → 401     # 合法整数才轮到 login_required
```

两点要注意：

- **非整数路径即使未登录也回 404，不回 401。** Flask 先做 URL 匹配，匹配不上就在路由层 404，装饰器根本没机会跑。这不是缺陷，是路由分派在视图之前的必然结果，但写前端分支时要知道「404 不一定意味着已登录」。
- **负数 id 不用单独判**：`-1` 被 `<int:...>` 挡在路由层，视图里拿到的 `annotation_id` 一定是非负整数。所以服务层不必写 `if annotation_id < 0`——那是永不可达的死分支。

顺带把参数名 `id` 改成 `annotation_id`：`id` 遮蔽内置函数，且视图里出现 `id` 时读不出是「标注的 id」还是别的东西。

### 3.3 归属：不判

**任何教师都能删任何人的标注**，不校验 `annotation.teacher_id == current_user_id()`。

理由：

1. C4 spec 3.4 已定 `annotations` 是「**一个唱段一套全局唯一的规则集**」，不是每教师一份——`UNIQUE(segment_id, word_index, tag)` 不含 `teacher_id` 就是这条前提的物化。在这个前提下，规则的所有者是「这个唱段」，不是「标它的那位教师」。
2. C4 出参（`AnnotationOut`）**干脆不返回 `teacher_id`**（第 28 条）。前端拿不到归属，也就无从展示「这是谁标的」；此时后端判归属，用户看到的会是「删不掉但不知道为什么」。
3. 判归属会堵死「甲老师标错、乙老师来改」——而 C6 是唯一的撤回手段（第 30 条）。

**这是本次自行采用的口径，已登记待文档方追认**（第 31 条）。若文档方要求按人隔离，改动点在服务层一个 if，但会与 C4 的「全局规则集」前提打架。

### 3.4 出参：`ok(None)`

```json
{"code": 0, "message": "ok", "data": null}
```

`ok()` 的 docstring 明确把 `None` 列为合法形态（`data` 可以是任意可 JSON 化的值）。

**不回被删的行**：行已经没了，「返回刚删掉的那一行」要么多查一次、要么把删前状态随手抛回去，而前端本来就知道自己删的是哪个 id。C5 回整行是因为前端**不知道**新建的 id 是多少（`id` 由数据库生成）；删除没有这个信息缺口，所以不照搬。

**不回 `{"id": id}`**：同理，没有消费方。

**HTTP 200 不是 204**：本项目 `ok()` 固定回 200，且响应体必须带 `{"code","message","data"}` 信封（《5-接口清单》），204 按定义无响应体，会打破信封约定。与既有 POST（`auth/login`、C5）一致，不为一个接口单独破例。

### 3.5 不存在：`404`

删一个不存在的 id（别人刚删了、或前端状态过期）回 `404` +「标注不存在」。

REST 教条会说 DELETE 应当幂等（删不存在的也回 200/204）。本项目不采用：

1. **本项目没有任何幂等先例**。C3/C4/C5 对「资源不存在」一律 `BusinessError(404, ...)`。为 C6 单独引入幂等语义，会让「code 与 HTTP 状态码一致」（第 9 条）之外再多一条要记住的例外。
2. **幂等在这里没有实际收益**：前端点 ✕ 时那一行确实在屏幕上，404 只会在「另一个教师刚删了同一行」的并发下出现。此时回 404 并弹「标注不存在」，比静默成功更有用——用户立刻知道「这条已经没了」，而不是以为自己删成功了一次不存在的操作。

### 3.6 边界小结

| 输入 | 结果 |
|---|---|
| 存在且属于任意唱段 | `200` + `data: null`，行被删除 |
| 不存在的正整数 | `404`「标注不存在」 |
| `0` | `404`「标注不存在」（`SERIAL` 从 1 起，0 永不命中） |
| 负数 | 路由层 `404`「接口不存在」 |
| `abc` / `1.5` / 空 | 路由层 `404`「接口不存在」 |
| 未登录 | `401`「未登录」（仅对合法整数路径） |
| 学生登录 | `403`「需要教师权限」 |
| 无 `Content-Type` / 无 body | 无所谓——本接口不读请求体，`_payload()` 不参与 |

## 4. 分层落点

沿用 C5 的四层，各层职责不变。

### 4.1 仓储层 `app/repositories/annotations_repo.py`

新增两个函数：

```python
def get_by_id(db: Session, annotation_id: int) -> Annotation | None:
    """按主键取一条标注（C6 的存在性判定）。取不到返回 None。"""
    return db.get(Annotation, annotation_id)


def remove(db: Session, ann: Annotation) -> None:
    """删除一条标注。只标脏，提交交给 service 层（同 add 只 flush 的约定）。"""
    db.delete(ann)
```

**为什么先查再删，不用 `DELETE ... WHERE id = ?` 拿 rowcount**：

- rowcount 只有 0/1。拿到 0 时，要区分「不存在」与「并发被删」，还得再 SELECT 一次——省下的那次 SELECT 又还回去了。
- 本仓储层一律以 **ORM 对象**为出入口（`add` 返回 `Annotation`、`get_one`/`list_by_segment` 返回 ORM 行），提交只由 service 层做。`Session.delete(obj)` 正是这个形状；写原生 `delete()` 语句会让这一层出现两种风格。
- 这条接口的量级是「一次一行」，多一次 SELECT 不值得为它优化。真到需要批量删除时再换写法。

`db.get(Annotation, id)` 而不是 `db.scalar(select(...).where(id == ...))`：前者直接走 identity map / 主键查询，是本层已有的写法里最短的一个。

### 4.2 服务层 `app/services/library_service.py`

新增：

```python
def delete_annotation(db: Session, annotation_id: int) -> None:
    """C6 删除标注。不存在抛 404。

    **不判归属**：任何教师可删任何人的标注（spec 3.3）。
    """
    ann = annotations_repo.get_by_id(db, annotation_id)
    if ann is None:
        raise BusinessError(404, "标注不存在")
    annotations_repo.remove(db, ann)
    db.commit()
```

**只有一条判定**，没有 C5 那样的 404/422/409 三级：路径参数已由 `<int:...>` 保证是非负整数，没有请求体也就没有入参校验，重复删除在第一步就撞 404。

返回 `None` 而不是 dict：删除没有「新状态」可返回（spec 3.4）。这与其他 service 函数一律返回 dict/ORM 的风格不同，但那些函数的出参都有内容，这里没有。

**参数名用 `annotation_id`**（不是 `id`）。

### 4.3 接口层 `app/api/demos_segments_annotations.py`

把占位路由替换为：

```python
@api_bp.route("/annotations/<int:annotation_id>", methods=["DELETE"])
@login_required
@teacher_required
def del_annotations(annotation_id):
    """C6 删除标注。

    路径参数用 `<int:annotation_id>`：非整数在**路由层**就 404，不进视图
    （同 C2/C3/C4）。所以本层与 service 层都不必判负数或非数字。

    **权限是教师**（文档 C6 的权限列就是「教师」），与同组 C4/C5/C7 一致。

    回 `ok(None)`：删除没有新状态可回（spec 3.4）。**不是 204**——本项目
    统一信封（《5-接口清单》），204 按定义无响应体，会打破它。
    """
    library_service.delete_annotation(get_db(), annotation_id)
    return ok(None)
```

**C7（`GET /api/annotations/rules`）的占位路由不动**，仍保持 `return ok({"tag":tag,"word":word})`。

**C6 与 C7 的路由不冲突，且不依赖注册顺序**：C7 是 `/annotations/rules`，其中 `rules` 不是整数，永远匹配不上 C6 的 `<int:annotation_id>`。

反过来说，若 C6 保持字符串转换器 `<annotation_id>`，`/api/annotations/rules` **会**命中它——今天因为方法不同（C7 是 GET、C6 是 DELETE）侥幸不撞，但那时 C7 能不能用就取决于「两条路由谁先注册」，是个不该留的脆弱依赖。`<int:...>` 把这个隐患从根上消掉。

### 4.4 页面 `annotation.html`

本层做的事情比 C5 那一轮少：C5 要引入 `annLoaded` 降级分支与排序，C6 只是「把 id 传进 `deleteAnnotation`，成功后 `splice` 掉本地那一行」。改动落在两个地方——`renderAnnotations()` 里的 ✕（第 5.1 节）与 `deleteAnnotation()` 本体（第 5.2 节）。详细代码见第 5 节。

## 5. 页面调用（`annotation.html`）

### 5.1 ✕ 传 id

`renderAnnotations()` 里那一行（`:808`）：

```js
<div class="ann-del" onclick="deleteAnnotation(${ann.id})">✕</div>
```

传的是 `ann.id`（库里的自增主键），**不是 `ann.index`**。同名不同义：`index` 是「第几个字」，删错维度会删掉另一条标注，且不报错（那个 id 很可能是存在的）。

### 5.2 `deleteAnnotation(id)` 改真删除

```js
async function deleteAnnotation(id) {
  const ann = annotations.find((a) => a.id === id);
  if (!ann) return;                       // 行已被别处删掉，本地也找不到了
  // 删错一个 tag 是 C6 之前唯一撤不回的操作，误点又只需一次轻触——先确认。
  // 文案带上字与 tag（annNote 拼「谁字拖腔标注」），否则用户对着「确定删除吗？」
  // 无从判断删的是哪一条
  if (!confirm(`确定删除「${annNote(ann)}」吗？`)) return;

  try {
    const r = await fetch(`/api/annotations/${id}`, {
      method: 'DELETE',
      // 同源相对路径 + same-origin：同 C5，跨源地址会让 fetch 不带 Cookie，
      // 后端 login_required 只会看到空 session 并回 401
      credentials: 'same-origin',
    });
    const body = await r.json();
    if (!r.ok || body.code !== 0) throw new Error(body.message || String(r.status));
  } catch (e) {
    // 只弹 toast、不改本地列表：列表只装服务端确认过的状态（同 saveAnnotation）
    showToast("error", "删除失败", e.message);
    return;
  }

  // 文案在 splice 之前算：ann 对象 splice 后仍在（只是不在数组里），
  // 但把「用到本地状态的东西」放在改动本地状态之前，读起来不必回头确认
  showToast("success", "已删除标注", annNote(ann));
  const i = annotations.findIndex((a) => a.id === id);
  if (i >= 0) annotations.splice(i, 1);
  renderAnnotations();
  renderLyrics();          // 格子上的 ✓ 由 renderLyrics 画，删了要重画一次
}
```

要点：

- **`confirm` 在 `fetch` 之前、且在 `await` 之前**：`confirm()` 是同步阻塞的，用户点「取消」时一个请求都不该发出去。
- **失败路径 `return` 在 `splice` 之前**：`annotations` 只装服务端确认过的行。若删除请求失败（网络断、404、403），屏幕上的行必须原样留着——否则用户会以为删掉了，刷新才发现还在。
- **成功后才 `splice`**：与 C5「等响应再改本地」一致。删除等待服务端确认的代价比插入更小（一行消失 vs 一行出现），但没有理由两处用不同的时序。
- **成功路径不设标志位**：`try` 块里没有「成功才置位」的变量——`catch` 直接 `return`，能走到 `try` 之后就是成功了。多一个 `okFlag` 是赋值后从不读的死变量。

### 5.3 为什么不需要 C5 那套 `annLoaded` 降级分支

C5 里 `if (!annLoaded) { await fetchAnnotations(seg.id); return; }` 是为了处理「本地列表不完整时插入一条，会让页面显得『这个唱段只有刚写的这一条』」。

**删除不需要这个分支**，两条理由：

1. **`annLoaded === false` ⟹ 列表为空 ⟹ 没有 ✕ 可点**。`annLoaded` 的两个置 false 点（`switchSegment`、`fetchAnnotations` 的失败分支）都紧跟在 `annotations = []` 之后，中间没有任何插入。所以 `annLoaded` 为 false 时页面显示的是空态，用户无从触发删除。
2. **语义不同**。插入是在断言「这就是全部」，所以本地列表不完整时会说错话；删除只是拿掉**一个确定存在的行**——哪怕服务端还有本地不知道的行，删掉已知的这一条依然正确。

所以删除路径既不需要 `annLoaded` 判定，也不需要删除后重新拉列表。

### 5.4 提示文案

| 场景 | 类型 | 标题 | 正文 |
|---|---|---|---|
| 成功 | success | 已删除标注 | `annNote(ann)`，如「谁字拖腔标注」 |
| 失败（404） | error | 删除失败 | 后端 message，即「标注不存在」 |
| 失败（403） | error | 删除失败 | 「需要教师权限」 |
| 失败（网络） | error | 删除失败 | fetch 抛出的 message，如 `Failed to fetch` |
| 取消确认 | — | — | 不出提示。用户主动取消不是「失败」，弹 toast 是在报告一件没发生的事 |

`deleteAnnotation` 里原来那段「C6 尚未实现」的 toast 连同它的 HTML 实体注释（`&lt;id&gt;`）一起删掉——实体转义是为了让 `showToast` 的 innerHTML 不吞掉 `<id>`，占位没了这个理由也就没了。

## 6. 验证

无测试框架（仓库没有 `tests/`、没装 pytest），沿用 C5 的做法：后端用 curl、前端用 `/browse` 技能。

### 6.1 接口

先写一条标注拿 id（借 C5 的接口），再打 C6：

| 用例 | 期望 |
|---|---|
| 正常删除 | `200`，`data` 是 `null`（**不是 `{}` 也不是被删的行**） |
| 库里确认 | 该 id 的行没了，其余行不动 |
| 再删同一个 id | `404`「标注不存在」 |
| 删 id `0` | `404`「标注不存在」 |
| 删 id `999999` | `404`「标注不存在」 |
| `/api/annotations/-1` | `404`「接口不存在」（路由层） |
| `/api/annotations/abc` | `404`「接口不存在」（路由层） |
| 未带 Cookie + 合法 id | `401`「未登录」 |
| 学生账号 + 合法 id | `403`「需要教师权限」 |
| `GET /api/annotations/1` | `405`「请求方法不允许」（只注册了 DELETE） |
| 删完后 `GET /api/segments/<seg>/annotations` | 该条不在列表里 |

**清理纪律**：每条用例产生的行都要在验证结束时删干净，最后确认 `SELECT count(*) FROM annotations` 是 `0`。C5 那一轮就是这么做的。

### 6.2 页面（`/browse`）

后端已重启的话旧会话会失效，先重新登录 `teacher01`。

1. **取消确认不删**：点 ✕ → 弹确认框 → 点「取消」→ 列表条数不变，**Network 里没有 `DELETE` 请求**
2. **确认后删掉**：点 ✕ → 确认 → 列表少一条、`(N条)` 减一、该字的 ✓ 从歌词格上消失
3. **真落库**：刷新页面 → 那条**仍然不在**（这是「真删除」的唯一证明）
4. **删最后一条回空态**：把某唱段的标注删到一个不剩 → 列表显示「📝 暂无标注规则」、`(0条)`
5. **确认框文案**：弹窗里带字与 tag（「确定删除『谁字拖腔标注』吗？」），不是干巴巴的「确定删除吗？」
6. **失败路径不动列表**：把 `fetch(\`/api/annotations/${id}\`` 临时改成坏 URL（或用坏 fetch 补丁）→ 确认 → 弹 ⚠️「删除失败」、**列表条数不变** → 验完复原，确认文件里无残留
7. **删完不串段**：删 A 唱段的一条 → 切到 B 段 → B 段的列表与 ✓ 不受影响

### 6.3 收尾检查

- `annotation.html` 里不再有「C6」字样的占位提示（`grep -n "C6" annotation.html`）
- `app/api/demos_segments_annotations.py` 里 C7 的占位仍是 `return ok({"tag":tag,"word":word})`
- `python scripts/check_db.py` 无**新增**差异（既有的 `demo_versions` + `teacher_demos` 三列漂移不算）
- `SELECT count(*) FROM annotations` = `0`

## 7. 收尾

**登记 `DOC_ISSUES.md` 第 31 条**，内容与第 30 条（C5）同构：C6 在文档里只有一行，请求/响应/状态码/不存在语义/归属规则全未定义，本次采用的口径逐项列出并请文档方追认。至少包括：

1. 成功回 `200` + `data: null`，不是 `204`
2. 删不存在的 id 回 `404`，不是幂等 `200`——文档方若要求幂等需明确
3. **不判归属**：任何教师可删任何人的标注，与 C4「一个唱段一套全局唯一的规则集」的前提绑定
4. 路径参数用 `<int:...>`，非整数在路由层 404

第 30 条「待确认」里关于 C6 的两点（「标错了撤不掉」与「是否需要更新接口」）在本条落地后应当更新：前者解除，后者仍待文档方回答。

## 8. 不做的事（YAGNI）

- **不做批量删除**：文档没有这个接口，页面也没有多选 UI
- **不做软删 / 回收站**：`deleted_at` 列不存在，文档没要求
- **不做撤销（undo）**：删除后弹一个「撤销」按钮需要「重新插入同一行」的接口（`id` 会变），而 C5 的 `POST` 做不到按原 id 恢复。没有需求，不做
- **不动 C7**：规则列表管理的过滤/分页是另一个接口的事
- **不重构 `app-d.py` 的 `demo_bp` 死代码**：与本次无关（DOC_ISSUES 第 11 条）
