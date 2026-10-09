# 音频存储分层（`uploads/` + `uploads/demos/`）设计

**关联**：`DOC_ISSUES.md` 第 40 条（本设计修的就是它）；前一轮 `docs/superpowers/specs/2026-10-09-sing-along-list-and-demo-playback-design.md` 的 §2.5 已被本设计推翻。

## 1. 背景与目标

产品口径（2026-10-09 确认）：**`uploads/` 下平铺的 wav 是学生练习录音，`uploads/demos/` 下的是示范库音频，两者要有意分开。**

而 `app/common/storage.py` 是单目录模型：`save()` 没有目录参数、只能落 `uploads/` 根；`resolve()` 的守卫 `path.parent != root` 让**任何子目录都不合法**。于是：

- 示范音频无处可存（上传会落到根目录，与学生录音混在一起）；
- 库里那些按 `uploads/demos/…` 手工插入的值**一条都解不出来**，B5 播放、解析、分析三条链路全断。

**目标**：让 `storage` 能表达这两层，示范音频上传落 `demos/`、学生录音仍落根目录；令 `teacher_demos` 关联的音频全部可解析。**修完 demo 16 一首应能真正出声**。

## 2. 现状（实测）

### 2.1 两个函数的契约

```python
# save()：一律写到 uploads/ 根，文件名是 uuid——没有任何目录参数
dest = settings.upload_dir / stored_name

# resolve()：守卫要求父目录「正好」是 uploads/
root = settings.upload_dir.resolve()
path = (root / stored_name).resolve()
if path.parent != root:
    raise BusinessError(400, "非法的音频文件名")
```

### 2.2 写入面很窄（这是本设计能小改的前提）

`storage.save()` 全项目**只有一个调用点**：`app/services/audio_service.py:53`（`save_upload`）。`save_upload` 又有两个调用方：

| 调用方 | 场景 | 期望落点 |
|---|---|---|
| `app/api/audio_analyze.py:43`（B1） | 学生录音上传 | `uploads/` 根（不动） |
| `app/api/demo_library.py:41` | 示范库上传 | `uploads/demos/` |

### 2.3 `access` 不能拿来推目录

两个调用点传的都是 `request.form.get("access", "private")`——**客户端可控，且默认 `private`**。示范库那个自己不传就是 private。拿 `access` 推目录会在「教师上传示范但没显式传 public」时把示范音频存进学生录音目录。

**结论：落点必须由调用方显式给，与 `access` 解耦。**

### 2.4 读取面把 `file_path` 当不透明值

三处 `storage.resolve(audio.file_path)`：`audio_service.py:97`（B5 播放）、`parse_service.py:246`（Demucs 解析）、`analyze_service.py:178`（分析）。**全部经由 `resolve`，没有一处假设它是裸名**（无字符串拼接、无取后缀、无二次存盘）。

所以「让 `file_path` 可以含一层 `demos/`」这一个动作，三条链路一起修好。

另有 `audio_analyze.py:58` 与 `demo_library.py:108` 两处**刻意不把 `file_path` 回给客户端**，子目录名不会泄漏到接口响应里。

## 3. 设计

### 3.1 `resolve()`：守卫放宽到「落在 root 之内」

```python
def resolve(stored_name: str) -> Path:
    root = settings.upload_dir.resolve()
    path = (root / stored_name).resolve()
    if root not in path.parents:
        raise BusinessError(400, "非法的音频文件名")
    return path
```

判定改为「root 必须是 path 的祖先目录」。仍然拒绝（并有实测覆盖，见 §5）：

| 输入 | 结果 | 为什么 |
|---|---|---|
| `abc.wav` | 通过 → `uploads/abc.wav` | parents 含 root |
| `demos/abc.wav` | 通过 → `uploads/demos/abc.wav` | parents 含 root |
| `../etc/passwd` | 400 | 解析到 root 之外 |
| `/etc/passwd` | 400 | 绝对路径在 root 之外 |
| `""` / `"."` | 400 | 解析结果就是 root 本身，不是文件 |
| 指向 root 外的软链 | 400 | `.resolve()` 跟随软链后落在 root 外 |

**这是本次唯一的安全相关改动**：放宽的是「允许多深」，没有放宽「允不允许出界」。`..` 逃逸与软链逃逸仍然被挡——写实现时别顺手把 `.resolve()` 去掉。

### 3.2 `save()`：加可选子目录

```python
def save(file: FileStorage, *, subdir: str | None = None) -> tuple[str, int]:
    ...
    root = settings.upload_dir.resolve()
    dest_dir = (root / subdir).resolve() if subdir else root
    # subdir 由本仓库的代码常量传入，理论上干净；但这里与 resolve() 同源，
    # 一并挡住，免得将来有人把它接到请求参数上
    if dest_dir != root and root not in dest_dir.parents:
        raise BusinessError(400, "非法的存储子目录")

    dest = dest_dir / stored_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    file.save(dest)
    ...
    return dest.relative_to(root).as_posix(), size   # "demos/<hex>.wav" 或 "<hex>.wav"
```

返回值就是写进 `file_path` 的值，用 `relative_to(root).as_posix()` 生成——**列里存的仍是「相对 `uploads/` 的路径」，不含 `uploads/` 前缀**，与 §3.4 的列约定一致，也与现有裸名数据向前兼容。

`VARCHAR(255)` 够用：`demos/` + 32 位 hex + 后缀 ≈ 42 字符。

### 3.3 `save_upload()`：透传

`audio_service.save_upload` 加 `subdir: str | None = None`，原样传给 `storage.save`。不在此层做任何目录推断。

### 3.4 列约定在 `schema.sql` 里写明确

`schema.sql:48` 现在是：

```sql
file_path VARCHAR(255) NOT NULL,       -- uploads/ 相对路径
```

「uploads/ 相对路径」两种读法都成立（相对 `uploads/`、还是有一层 `uploads/` 的相对路径），第 40 条那批脏值正是这么进来的。改成：

```sql
file_path VARCHAR(255) NOT NULL,       -- 相对 uploads/ 的路径，可含一层目录（如 demos/<uuid>.wav），不带 uploads/ 前缀
```

### 3.5 `analyze_service` 的 404 文案

`analyze_service.py:180` 把 `audio.file_path` 拼进用户可见的错误消息（`音频文件已丢失：{file_path}`）。现在 `file_path` 可能带 `demos/`，会把服务端目录结构透给前端。改成只报 id 或固定文案。

> 注：这条是顺手修的信息泄漏，不改变任何判定逻辑。

### 3.6 数据修复脚本 `scripts/fix_demo_audio_paths.py`

规则：**`teacher_demos.audio_id` 关联的每一行 `audio_files`，其 `file_path` 都应是 `demos/<basename>`。**

- 幂等：已经是 `demos/…` 形态的跳过。
- 默认 `--dry-run` 行为？**不**——默认执行，`--dry-run` 显式传。脚本要打印 before/after 与「文件在不在」，让人当场看见结果。
- 不用 `seed.sql` 承载：这 4 条从来不在 `seed.sql` 里（是手工插的），而 `seed.sql` 是「从零建库」用的；这里是「给已存在的库补一次数据修正」，属两个场景。放 `scripts/` 与 `check_db.py` 同一套习惯，换机器重建库后可以重放。
- 用 `session_scope()`（脚本不跑在请求里），对齐 `CLAUDE.md` 的约定。

实测后会变成：

| audio id | 原 `file_path` | 新 `file_path` | 文件 | B5 |
|---|---|---|---|---|
| 75 | `uploads/demos/muguaying_yuanmenwai.wav` | `demos/muguaying_yuanmenwai.wav` | 有 | **200** |
| 76 | `uploads/demos/guifeizuijiu_haidaobinglun.wav` | `demos/guifeizuijiu_haidaobinglun.wav` | 无 | 404 |
| 77 | `uploads/demos/bawangbieji_kandawang.wav` | `demos/bawangbieji_kandawang.wav` | 无 | 404 |
| 78 | `uploads/demos/hongniang_jiaozhangsheng.wav` | `demos/hongniang_jiaozhangsheng.wav` | 无 | 404 |
| 74 | `090e52c9fb8642ab95d3c7e431e0e2b5.wav` | `demos/090e52c9fb8642ab95d3c7e431e0e2b5.wav` | 无 | 404 |

**74 这条要单独说明**：它是 demo 15 的音频，却用了学生录音那套裸名写法。按 §3.6 的规则它也应归 `demos/`。改与不改都是 404（文件根本不存在），但**不改就留下一条与规则相悖的数据**，下次看库的人还得再判一次。倾向改。

### 3.7 `parse_service` 自动受益

`parse_service.py:246` 用的是同一个 `resolve()`，§3.1 一改它就通。**示范库上传后解析跑不通这件事随之解决**（第 40 条第 40.3 节）。

## 4. 关键决策与理由

1. **不让 `resolve()` 兼容带 `uploads/` 前缀的旧值**。那是给脏数据开口子：一旦允许「有时带前缀、有时不带」，`uploads/uploads/x.wav` 这类值会永远存在，且没有任何机制能发现它们。宁可数据一次性改干净。
2. **不把目录写进新列**。加一列 `subdir` 会让三处 `resolve` 调用点都要拆两列拼路径——改动面反而大，且「路径」本来就是一件事，拆成两列只会制造「两列不一致」的新坏法。
3. **`subdir` 由调用方显式给，不由 `access` 推**（§2.3）。
4. **守卫按「祖先判定」而非白名单**。白名单每加一层目录都要回来改代码；祖先判定把「允许的深度」放开、把「出界」挡住，安全边界不变。用户已确认取此方案。

## 5. 容错口径

- `resolve()` 的拒绝清单见 §3.1 表格，实现后要逐条实测（含软链那条）。
- `file_path` 为 `NULL`？列是 `NOT NULL`，不处理。
- `demos/` 目录不存在时：`save()` 里 `dest.parent.mkdir(parents=True, exist_ok=True)` 会建；`resolve()` 只做字符串解析与守卫，不碰磁盘。
- 现有学生录音（`uploads/` 根下的 uuid 文件）**不动**。
- 现有 `uploads/demos/muguaying_yuanmenwai.wav` **不动**——它就在该在的位置，改完 `resolve()` 与数据后自然可达。

## 6. 非目标

- **不补 76/77/78 的音频源文件**。改完 1–4 它们仍是 404，需要仓库里没有的素材。
- 不改 `access` 语义（public/private 的可听范围判定不动）。
- 不动 `uploads/` 下现有的学生录音文件。
- 不做存量数据的一致性巡检工具（`check_db.py` 管模型与真库的结构比对，不管 `file_path` 取值）。
- 不动 `parse_service` 的 `TOP_DB` 等算法参数。

## 7. 验证方式

本仓库无测试框架，沿用既有做法：临时脚本 + `curl` + `psql` + 浏览器。

1. **守卫单测（临时脚本）**：直接调 `storage.resolve()`，逐条跑 §3.1 表格里的输入，确认 6 种形态的通过/拒绝与预期一致——**尤其`../` 与软链两条**。
2. **`save()` 落点**：临时脚本调 `storage.save()`（`subdir=None` / `"demos"` / `"../evil"`），确认前两者落在预期目录、第三者抛 400，并检查磁盘。
3. **B5 端到端**：`curl` 带 stu001 的 Cookie 取 `/api/audio/75` → **200** 且是音频字节；`/api/audio/76` → 404「音频文件已丢失」。
4. **浏览器**：`sing_along.html` 选 demo 16 点「播放示范」→ 日志不再出现失败提示、进度条与时间随真实音频走。**这是本轮第一次真的能听到声音。**
5. **`check_db.py`**：确认本次改动没引入模型/库结构差异（注意它本就有既有漂移，见 `DOC_ISSUES` 相关登记，别把既有差异当自己改坏）。
6. **回归**：B1 上传一首学生录音，确认它仍落在 `uploads/` 根、`file_path` 仍是裸名、B5 能取回。

## 8. 风险与遗留

- **安全边界是本设计的核心风险**：放宽守卫时最容易顺手弄坏的就是路径穿越防护。§7 第 1 条必须实测，不能只靠读代码。
- 改完仍只有 demo 16 一首能出声（76/77/78 缺文件）。**「播放示范能听」在演示时只对 demo 16 成立**，其余仍走失败降级——这一点要在演示口径里说清，别让人以为是随机偶发。
- `file_path` 里从此可以有目录层级，未来若有人写「按 `file_path` 取后缀」「按名字排序」之类的代码，要意识到它是相对路径而非裸名。
