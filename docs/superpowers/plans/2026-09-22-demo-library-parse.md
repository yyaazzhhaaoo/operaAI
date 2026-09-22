# 示范库解析链路（Demucs + 唱段切分）开发计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** 把 `demo_library.html` 的「上传示范音频 → Demucs 分离人声 → 按停顿切分唱段 → 落库」链路做成真的：上传即自动排队，前端轮询到终态，详情页显示真实分段。

**Architecture:** 新增 `app/services/parse_service.py`（任务生命周期 + 管线编排 + Celery 任务），与既有的 `analyze_service.py` 同构但**只传 `demo_id`**（路径、时长由任务自己查库）。分离引擎复用已写好但未提交的 `app/services/vocal_service.py`（Demucs htdemucs）。任务路由到**专用 `demucs` 队列**，与秒级的 B 组分析分开。状态存 redis（键 `parse:demo:<demo_id>`，TTL 3600 并续期），词表按前端用 `parsing`/`parsed`/`error`。

**Tech Stack:** Flask 3.1.3 · Celery 5.6.3 + redis · PostgreSQL 15.7 · Demucs 4.1.0 (htdemucs) · PyTorch CPU · librosa 0.11.0 · pydantic v2

**Spec:** `docs/superpowers/specs/2026-09-21-demo-library-parse-design.md`

## 执行口径（重要）

**本计划不含测试脚本，也不含验证步骤。** 所有冒烟脚本、内联断言、回归闸门、手工验证都不做——开发完成后由**用户**验证。

因此每个任务只有两步：**写代码 → 提交**。子代理不要自行发明测试、不要跑 `scripts/smoke_*.sh`、不要跑 `scripts/check_db.py`、不要起 Flask/worker/浏览器。**但代码必须写对**：没有测试兜底，正确性全靠照着下面的代码与注释写到位。

唯一的例外是 Task 1 的依赖安装与取数路径探查——那不是验证，是「不装上就没法确定代码里该设哪个环境变量」。

## Global Constraints

- **不新建 `tests/` 目录、不引入 pytest / jq / 任何测试框架。**
- **不引入 `pyproject.toml`。** 依赖清单只有 `requirements.txt`（+ 本次新增的 `requirements-demucs.txt`）。部署手册 2.3 节的流程是 `pip install -r requirements.txt`。
- **新增依赖只有三个**：`torch` / `torchaudio` / `demucs`，全部走 `requirements-demucs.txt`，且都带 `; sys_platform == "linux"` 标记。**不得装 `nvidia-*`**（必须用 CPU-only 轮子）。
- **分层铁律**：`app/api/` 只做「校验入参 → 调 service → 组装响应」，不写 SQL、不写业务规则、**不写 try/except**（全局 handler 兜，见 `app/common/errors.py`）；`app/services/` 管业务规则与**事务边界**；`app/repositories/` 只写 SQL 且**只 flush 不 commit**。
- **统一响应信封**：一律 `ok(data)` / `fail(code, message)`（`app/response.py`），`code` 与 HTTP 状态码一致。
- **`/api` 前缀只在 `app/api/__init__.py` 的 `url_prefix` 写一次**，路由写相对路径。
- **`created_at` 存的是 UTC**（容器内 PostgreSQL 时区 `Etc/UTC`），展示要换算，不要当北京时间。
- **表结构唯一真源是 `schema.sql`；本次不改表**（不加 `start_sec` 列）。
- **状态词表按前端**：`parsing` / `parsed` / `error`（+ 仅派生路径出现的 `unparsed`）。
- **不写 `lyrics_json`**（恒 NULL）、**不写 `elo_difficulty`**（保持库默认 1000）。
- **`segments` 只有 `seq` / `title` / `duration`**，没有起止时间。
- **不动 B 组任何代码路径**：`analyze_service.py` / `audio_analyze.py` / `audio_service.py` 的既有函数一行不改；`vocal_service.py` 只在 Task 1 明确指定的位置改。
- **所有注释、文档、commit message 用简体中文**；标识符用英文；文件编码 UTF-8。
- **Git 作者已在本仓库本地配好**为 `梅雅朝 <meiyazhao0920@163.com>`，commit 沿用，不要动全局配置。
- **每个任务结束后提交**，commit message 用中文。

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `requirements-demucs.txt` | 新建 | CPU-only 的 torch/torchaudio/demucs 三行 + 索引 URL |
| `requirements.txt` | 改（加 1 行） | `-r requirements-demucs.txt` |
| `scripts/fetch_demucs_weights.sh` | 新建 | 取 htdemucs 权重到 `models/demucs/` 并校验 sha256 |
| `app/services/vocal_service.py` | 改（`_prepare_runtime`） | 设权重目录环境变量 |
| `app/repositories/parse_task_repo.py` | 改 | redis 键由 `task_id` 改为 `demo_id` |
| `app/services/parse_service.py` | 新建 | 任务生命周期 + 唱段切分 + 管线 + Celery 任务 |
| `app/repositories/library_repo.py` | 扩 | `get_demo` / `list_segments` / `replace_segments` / `update_audio_duration` |
| `app/services/library_service.py` | 扩 | 列表行组装、详情查询 |
| `app/schemas/demo_library.py` | 重写 | 可空字段修复 + 列表/详情/分段三个模型 |
| `app/api/demo_library.py` | 重写 | 4 条接口 |
| `app/worker.py` | 改（docstring） | 补 `-Q demucs` 启动命令 |
| `demo_library.html` | 改 | 轮询/详情接真接口、分段列表、文案 |
| `CLAUDE.md` / `DOC_ISSUES.md` | 改 | 文档同步 |
| `app/api/uploads/`（空目录） | 删 | 上一轮的遗留 |
| `app-d.py` / `static/echarts.min.js` | 还原 | CRLF 噪音，**不是本次改动** |

---

### Task 1: 依赖与权重落地（真装 Demucs）

**Files:**
- Create: `requirements-demucs.txt`
- Create: `scripts/fetch_demucs_weights.sh`
- Modify: `requirements.txt`（末尾加一行）
- Modify: `app/services/vocal_service.py:41-75`（`_prepare_runtime`）
- 删除: `app/api/uploads/`（空目录）

**Interfaces:**
- Produces: 一个装好 torch/torchaudio/demucs 的 venv；`models/demucs/` 下的权重；`scripts/fetch_demucs_weights.sh`（`DEST` / `URL` 可用环境变量覆盖）

**背景（已实测，2026-09-21）：** 国际源全部超时，可用的是 SJTU 的 PyTorch CPU 轮子索引 + 清华 PyPI + ModelScope 的权重副本。权重已经手工下到 `models/955717e8-8726e21a.th`（84,141,911 字节），但**位置不对**：`settings.demucs_model_dir` 是 `BASE_DIR/models/demucs`，得挪进它认的位置。当前 venv **没有** torch/torchaudio/demucs。

- [ ] **Step 1: 写 `requirements-demucs.txt`**

```text
# 示范库解析链路的三个依赖（Demucs 4.1.0 + CPU-only PyTorch）。
#
# 为什么单独一个文件而不是并进 requirements.txt：**不是**为了「避免全局改道」
# —— pip 对 -r 引入的文件里的 --index-url / --extra-index-url 是**整次会话全局**
# 生效的，所以主文件一旦 `-r` 了本文件，整次 `pip install -r requirements.txt`
# 都会先走 SJTU、再走清华兜底；而且这两个选项行不带 sys_platform 标记，Mac 上
# 同样生效（清华是 PyPI 全量镜像，Mac 因此也装得通）。真实的收益只有一条：
# 主清单里不嵌入镜像 URL，换源或上内网时不必动主文件内容。
# 另外部署手册 2.3 节的流程是 `pip install -r requirements.txt`，主文件必须
# 保持「一条命令装完其余全部」——所以改成主文件里一行 `-r`。
#
# 为什么必须用 CPU 轮子：PyPI 上 linux 的 torch 默认是 CUDA 版，会拖进约 2.5GB
# 的 nvidia-* 依赖。本项目部署目标是 4 核无 GPU 的机器，装它纯属浪费磁盘和内存。
#
# 为什么带 sys_platform 标记：PyTorch 自 2.2.2 起不再发布 macOS x86_64 轮子
# （DOC_ISSUES 第 16 条），Mac 上必须整段跳过，否则 `pip install -r requirements.txt`
# 在 Mac 上会直接失败——而现在 Mac 上应用是能正常启动的（vocal_service 惰性 import）。
--index-url https://mirror.sjtu.edu.cn/pytorch-wheels/cpu/
--extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 实测版本组合（2026-09-22 本机装通，若某个组合装不上就顺延到最近可用组合，
# 并把最终组合写在这里）
torch==2.14.0+cpu ; sys_platform == "linux"
torchaudio==2.11.0+cpu ; sys_platform == "linux"
demucs==4.1.0 ; sys_platform == "linux"
```

- [ ] **Step 2: 主清单加一行**

在 `requirements.txt` **末尾**追加：

```text

# 示范库解析链路（Demucs）的 CPU-only 依赖。单独成文件的原因见该文件头部注释。
-r requirements-demucs.txt
```

- [ ] **Step 3: 安装（约 200MB 下载，几分钟）**

```bash
.venv/bin/pip install -r requirements-demucs.txt
```

**若版本组合失败**（torch 与 torchaudio 不保证任意组合可搭配）：顺延到最近可用组合重试，直到 `import` 三者同时成功。把最终组合写回 `requirements-demucs.txt` 的文件头注释。

- [ ] **Step 4: 探明 `get_model` 的真实取数路径**

spec §6.4 明确要求先确认再放权重——不探明就没法确定 `_prepare_runtime()` 里该设哪个环境变量、注释该怎么写。跑：

```bash
.venv/bin/python -c "import demucs.pretrained as p; print(p.__file__)"
grep -n "load_state_dict_from_url\|hub\|hf_hub\|HUGGINGFACE\|_ROOT\|files.txt" \
    "$(.venv/bin/python -c 'import demucs.pretrained as p; print(p.__file__)')" | head -30
echo "--- remote/files.txt 里的 htdemucs 条目 ---"
grep -n "955717e8" "$(.venv/bin/python -c 'import demucs.pretrained as p, os; print(os.path.dirname(p.__file__))')/remote/files.txt"
```

**结论怎么用**：`955717e8-8726e21a.th` 这个「哈希前缀-哈希前缀」的命名是 `torch.hub.load_state_dict_from_url(check_hash=True)` 的习惯，所以**最可能**是 torch.hub；但也可能是 HuggingFace Hub（现有 `vocal_service` 的注释是这么写的，且那条注释没被验证过）。**两种都设上**——见 Step 6，`TORCH_HOME` 与 `HF_HOME` 都指向 `models/demucs`，这样无论走哪条，缓存根目录都是对的，代码不依赖这次探查的结论。探查的产物只用来把 Step 6 的注释写准。

- [ ] **Step 5: 写 `scripts/fetch_demucs_weights.sh`**

```bash
#!/usr/bin/env bash
# 戏韵AI — 取 htdemucs 权重到 models/demucs/（示范库解析链路用）
#
# 用法（项目根目录）：scripts/fetch_demucs_weights.sh
#     DEST=<目录> scripts/fetch_demucs_weights.sh    # 覆盖落盘位置
#
# 为什么不用官方地址：本机实测 dl.fbaipublicfiles.com 与 huggingface.co 均超时，
# 而 ModelScope 上的 pengzhendong/uvr-demucs 有同一份文件（同名、同字节数、
# sha256 前 8 位与文件名末段一致）。见 spec 6.1 的可达性实测表。
#
# 离线部署可跳过本脚本，改由人工拷贝——与 .gitignore 里那句注释一致
# （models/ 不进版本库：权重约 80MB 且随模型换代而变）。
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 落盘位置。torch.hub 认 $TORCH_HOME/hub/checkpoints/<文件名>，HF Hub 认
# $HF_HOME/hub/...；vocal_service._prepare_runtime() 把这两个环境变量都指向
# models/demucs，所以这里放在 torch.hub 的布局下（最可能的取数路径）。
DEST="${DEST:-$ROOT/models/demucs/hub/checkpoints}"
FILE="955717e8-8726e21a.th"
SIZE=84141911
SHA256_PREFIX=8726e21a
URL="${URL:-https://www.modelscope.cn/api/v1/models/pengzhendong/uvr-demucs/repo?Revision=master&FilePath=v3_v4_repo%2F${FILE}}"

mkdir -p "$DEST"
echo "→ $URL"
# -L 必须有：ModelScope 先回 302，不加 -L 会得到一个 350 字节的重定向正文
# 而不是 84MB 的权重，且 curl 退出码仍是 0——静默坏掉。
curl -sSL --fail -o "$DEST/$FILE" "$URL" || { echo "下载失败：$URL" >&2; exit 1; }

got_size=$(wc -c < "$DEST/$FILE" | tr -d ' ')
if [ "$got_size" != "$SIZE" ]; then
  echo "字节数不符：期望 $SIZE，实际 $got_size —— 多半是被重定向骗了或源换了" >&2
  rm -f "$DEST/$FILE"; exit 1
fi

# 闸门：文件名末段就是哈希前缀，对不上说明拿到的是同名替换件而不是官方权重
got_hash=$(sha256sum "$DEST/$FILE" | cut -c1-8)
if [ "$got_hash" != "$SHA256_PREFIX" ]; then
  echo "sha256 前缀不符：期望 $SHA256_PREFIX，实际 $got_hash" >&2
  rm -f "$DEST/$FILE"; exit 1
fi

echo "✓ $DEST/$FILE  ($got_size 字节, sha256:$got_hash)"
```

- [ ] **Step 6: 落位权重 + 改 `_prepare_runtime()`**

先把已下好的文件挪到位：

```bash
mkdir -p models/demucs/hub/checkpoints
mv models/955717e8-8726e21a.th models/demucs/hub/checkpoints/
ls -l models/demucs/hub/checkpoints/
```

再改 `app/services/vocal_service.py` 的 `_prepare_runtime()`。**现有 docstring 说的是 HF Hub 而且从未被验证过，Step 4 探到的是什么就按什么写**——留一句与实际代码路径不符的注释比没有注释更坏：

```python
    model_dir = Path(settings.demucs_model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)

    # 权重目录。**两个环境变量都设**：Step 4 探明 demucs 4.1.0 的 get_model 是
    # **两级**路径——先试 HF Hub（huggingface_hub.hf_hub_download，缓存受
    # HF_HOME 控制），失败才回退 legacy 的 torch.hub.load_state_dict_from_url
    # （受 TORCH_HOME 控制）。两条路径的缓存根都得受控，所以两个都设：联网机器
    # 命中 HF 那级，离线机器命中回退那级；预置权重
    # （scripts/fetch_demucs_weights.sh）按 torch.hub 的布局放。
    #
    # 两级的**求值时机不一样**（已核 torch 2.14 与 huggingface_hub 源码）：
    #   HF_HOME    → huggingface_hub/constants.py 在 **import 期**就把它读成模块级
    #                常量，之后不再看环境变量 → 必须早于 `import huggingface_hub`
    #   TORCH_HOME → torch/hub.py 只在**首次下载时**才读环境变量（模块级只有个
    #                惰性占位 `_hub_dir = None`）→ 早设是为了统一，不是因为晚了会失效
    # 两级都受控，理由分别是：`huggingface_hub` 的首次 import 与任何下载动作都晚于
    # 本函数（`demucs.pretrained` 要到 `_get_model()` 里才导入）；而本模块那句
    # 模块级的 `import torch`（在 `_prepare_runtime()` 里也有一句，那一次在赋值之后）
    # 虽然早于本函数调用，但 torch 2.14 不在 import 期读 TORCH_HOME，故无影响。
    os.environ.setdefault("TORCH_HOME", str(model_dir))
    os.environ.setdefault("HF_HOME", str(model_dir))
```

（原 `os.environ.setdefault("HF_HOME", ...)` 那一行与它上面那段只讲 HF 的注释整体替换为上面这段。`import torch` / 线程数那部分不动。）

**同时必须改掉 `_prepare_runtime()` docstring 第 1 条里同样的机理错误**：现文写的「两个库都在 **import 期**就把缓存目录求值成了模块级常量，之后再改这个变量不会生效，权重仍会落到 ~/.cache」对 `TORCH_HOME` 不成立（torch 2.14 是首次下载时才读）。**这句是硬伤**：本仓的注释是承载「为什么」的主要文档，一句与钉版依赖的实际行为相反的机理说明会误导后来的人按错误前提改代码。docstring 与上面的行内注释必须给出一致的说法。

**另外**：`import demucs` 那句（`from demucs.apply import apply_model`）在文件里位于 `_prepare_runtime()` 调用**之前**，所以注释**不要**写成「必须在本模块 import demucs 之前设好」——字面不成立（已核：`demucs/__init__.py` 零导入、`apply.py` 只引架构模块，无实际后果）。准确的表述是「必须早于**首次下载**；HF 那一级还要求早于 `import huggingface_hub`」，这也是上面新注释的写法。

- [ ] **Step 7: 删遗留空目录**

```bash
rmdir app/api/uploads && echo "已删除 app/api/uploads（上一轮模块级 os.makedirs 的遗留）"
```

- [ ] **Step 8: 提交**

```bash
git add requirements-demucs.txt requirements.txt scripts/fetch_demucs_weights.sh \
        app/services/vocal_service.py
git status --short          # 确认没有把 models/ 下的权重加进来（.gitignore 已排除 models/）
git commit -m "feat: 引入 CPU-only Demucs 依赖与权重获取脚本"
```

---

### Task 2: `parse_task_repo` 的键由 `task_id` 改为 `demo_id`

**Files:**
- Modify: `app/repositories/parse_task_repo.py`（参数名与 `_key`）

**Interfaces:**
- Produces: `create(demo_id: int, ttl: int = 3600, **fields) -> None`、`update(demo_id: int, ttl: int = 3600, **fields) -> None`、`get(demo_id: int) -> dict | None`；redis 键 `parse:demo:<demo_id>`

**为什么改**：一个 demo 同一时刻只有一个解析任务，前端也是按 `demo_id` 轮询；重跑即覆盖。用 `task_id` 做键的话，重跑会产生第二条记录，前端按 `demo_id` 根本查不到新的那条。Celery 的 `task_id` 仍生成（`uuid4().hex[:12]`，与 B2 一致），只存进 hash 供日志追踪。

- [ ] **Step 1: 改 `_key`**

`app/repositories/parse_task_repo.py` 里把 `_key` 整体替换为：

```python
def _key(demo_id: int) -> str:
    """键用 demo_id 而**不是** Celery 的 task_id。

    一个 demo 同一时刻只有一个解析任务，前端也是按 demo_id 轮询；用 task_id
    做键的话「重跑」会产生第二条记录，前端拿 demo_id 根本查不到新的那条。
    task_id 仍然生成，只存进 hash 供日志追踪（与 B2 的 uuid4().hex[:12] 一致）。
    """
    return f"{TASK_PREFIX}{demo_id}"
```

（原来的 `def _key(task_id: str) -> str: return f"{TASK_PREFIX}{task_id}"` 整体被上面替换。）

- [ ] **Step 2: 三个函数的参数改名**

`create` / `update` / `get` 的第一个参数由 `task_id: str` 改为 `demo_id: int`，函数体内所有 `_key(task_id)` 改为 `_key(demo_id)`。

**其余逻辑一行不改**：`_encode()` 原样保留；`update` 的续期行为与那段「解析要跑 8–15 分钟」的注释保留；`get` 里 `progress`/`demo_id` 的 int 还原逻辑与注释全部保留（`get` 里那段「demo_id 要转回 int」的说明仍然成立）。

**同时补一段模块级说明**（放在模块 docstring 的 `TASK_PREFIX` 附近或 docstring 末尾都可以）：这个前缀后面跟的是 **demo_id**，不是 task_id。

- [ ] **Step 3: 确认没打破 B 组**

```bash
grep -rn "analyze_task_repo" app/ | grep -v "app/repositories/analyze_task_repo.py"
```

预期：只有 `analyze_service.py` 一处 import，且本任务没碰过 `analyze_task_repo.py`。

- [ ] **Step 4: 提交**

```bash
git add app/repositories/parse_task_repo.py
git commit -m "refactor: 解析任务状态改用 demo_id 作 redis 键"
```

---

### Task 3: `parse_service` 的唱段切分算法（纯函数）

**Files:**
- Create: `app/services/parse_service.py`（本任务只写模块头 + 阶段常量 + 切分算法）

**Interfaces:**
- Produces:
  - 常量 `STAGE_SEPARATE="人声分离"` / `STAGE_SEGMENT="唱段切分"` / `STAGE_SAVE="结果入库"`、`STAGES`、`STAGE_RANGE`
  - 常量 `STATUS_PARSING` / `STATUS_PARSED` / `STATUS_ERROR` / `STATUS_UNPARSED`
  - `_split_segments(y: np.ndarray, sr: int) -> list[dict]` → `[{"seq": 1, "title": "第 1 段", "duration": 6.6}, ...]`
  - `_merge_intervals(intervals, min_gap: int) -> list[tuple[int, int]]`

**为什么切分算法留在 `parse_service` 里而不是单开 `segment_service.py`**：与 `analyze_service.py` 把 DSP 辅助函数内联在同一文件的做法一致（那个文件里 `_load_vocal` / `_detect_onset` 都在本文件）。本仓的分层是按「api / service / repo」切的，不是按「每个算法一个文件」切的。

- [ ] **Step 1: 新建 `app/services/parse_service.py`**

本任务只写这些内容（Task 4 会往同一文件末尾追加）：

```python
# -*- coding: utf-8 -*-
"""示范库解析任务的业务逻辑（DOC_ISSUES 第 16–20 条）。

异步模型：上传接口建任务后立刻返回 task_id，真正的 Demucs 分离交给 Celery
worker 在**另一个进程**里跑，进度落在 redis（parse_task_repo），
前端 `GET /api/demo/library/<id>/parse/status` 每 3 秒轮询。

与 analyze_service 有三处**刻意**不一致：

1. 任务只收 demo_id，不收磁盘路径——路径、上传者、原有时长都由任务自己查库取。
   示范库这条链路从头到尾都在跟数据库打交道，把路径塞进消息只会多一处状态不一致。
2. 状态词表按**前端**（parsing/parsed/error，第 18 条），不是 B 组的 queued/done/failed。
3. 解析走**专用 demucs 队列**（一次 8–15 分钟，与秒级的 B 组同队列会把
   pitch_comparison.html 拖住）。代价是 worker 必须带 -Q demucs，见 app/worker.py。

本层不引用 flask.session / flask.request：Celery 任务跑在另一个进程里，
请求上下文和会话都不会跟过去。
"""

import logging

import librosa
import numpy as np

logger = logging.getLogger(__name__)

# ===== 状态词表（第 18 条：按前端，不是 B 组的 queued/done/failed）=====
#
# demo_library.html 的 startPolling 判的是 `st.status === "parsed" || "error"`，
# 所以这两个值不能改。unparsed 是本设计新增的第四个取值，**只可能出现在
# status() 的派生路径上**（redis 里那条 TTL 过期之后）。
STATUS_PARSING = "parsing"
STATUS_PARSED = "parsed"
STATUS_ERROR = "error"
STATUS_UNPARSED = "unparsed"

# ===== 阶段与进度 =====
#
# 区间刻意对齐前端 renderParseFlow 的完成阈值「progress >= t + 15」——t 是前端每个
# 步骤自己的阈值，progress 到 t 时该步显示 🔄、到 t + 15 时变 ✅。三个阶段上报的
# 都是下界（20 / 50 / 80），效果是「上一步恰好变 ✅、本步变 🔄」，步骤条会一步步往下走。
#
# **但别指望所有步骤都亮成 ✅**：本管线只有这三次阶段上报（外加终态的 100），而最后
# 一步的阈值是 100、要 115 才变 ✅，它在整个任务生命周期里都不会变 ✅——终态一到前端
# 就切到结果视图，看不到那一步，不必为此补一次多余的上报。
#
# 上面这几个 STAGE_* 是**本层内部**的阶段名（写进 redis 的 stage 字段），不是前端步骤
# 条上的文案，两者不必逐字对应。前端步骤的条数与名称见 demo_library.html 的
# renderParseFlow，这里不复制那份清单，免得两处各写一份、改一处漏一处。
#
# 上界（45 / 75 / 95）只是文档性的：_enter_stage 取的是 [0]，没有阶段内插值。
# 分离阶段不插值是有意的——apply_model 不提供分片回调，要细粒度进度只能自己
# 按 30 秒切片循环调用，代价是段边界丢掉跨片上下文、分离质量下降。取舍是**不切**，
# 改用 message 说清耗时预期（见 _parse）。
STAGE_SEPARATE = "人声分离"
STAGE_SEGMENT = "唱段切分"
STAGE_SAVE = "结果入库"
STAGES = [STAGE_SEPARATE, STAGE_SEGMENT, STAGE_SAVE]
STAGE_RANGE = {
    STAGE_SEPARATE: (20, 45),
    STAGE_SEGMENT: (50, 75),
    STAGE_SAVE: (80, 95),
}

# ===== 唱段切分参数 =====
#
# TOP_DB 是「多低算静音」的阈值（dB，相对**峰值**帧），librosa.effects.split 的默认值是 60。
# 判据是 `db > -top_db`（见 librosa.effects._signal_to_frame_nonsilent），所以这个数
# **越小、被判成静音的帧越多、切出来的段越多**；越大越容易把相邻唱句并成一段。
#
# 取 30（比默认的 60 小）就是主动往「多判静音」这一侧压：比峰值低 30~60dB 的内容
# ——换气声、拖腔的尾音——会被判成静音，从而成为切分点。这正是「按停顿切段」要的，
# 停顿本来就包含换气。敢压这么低的前提是**输入已经过 Demucs 分离**：伴奏残留少、
# 噪声底低，压低阈值也不会把背景噪声误判成停顿。反过来若用默认的 60，换气会留在
# 「有声」一侧，相邻唱句会粘成一段。
#
# ⚠️ 30 是**未经真实素材标定**的初始值（本轮开发不含验证环节）。调参时只改这一个数。
TOP_DB = 30.0
MIN_GAP_SEC = 0.35   # 间隙短于这个就当同一段（字与字之间本就有停顿）
MIN_SEG_SEC = 1.0    # 短于这个的碎段直接丢（多是分离残留的爆破音）
FRAME_LENGTH = 2048  # 与 analyze_service 的 FRAME_LENGTH 一致
HOP_LENGTH = 512     # 16000/512 ≈ 32ms 一帧，比 analyze 的 HOP 细，切分要的是位置精度

# ===== 时长回填 =====

TRUNCATE_NOTE = "音频超过 3 分钟，仅解析了前 3 分钟"


# ===== 唱段切分（纯函数，不碰 redis / 不碰数据库，可单独调）=====

def _split_segments(y: np.ndarray, sr: int) -> list[dict]:
    """把 16k 单声道人声轨按停顿切成唱段，返回 [{seq, title, duration}]。

    四步（spec 4.3）：取有声区间 → 合并近邻 → 丢弃碎段 → 空结果回退成整条一段。

    最后那步回退是刻意的：任何输入都要有分段、都要能走到 `parsed` 终态。
    没有它，一段全静音的人声轨（分离失败、纯伴奏）会让 segments 一行不落，
    而前端还在轮询一个永远不会到来的 `parsed`。

    duration 只落时长、不落起止时间（第 2 节已定：不加 start_sec 列），
    所以前端只能显示「第 N 段 · 6.6s」，做不了「点击定位到该段」。
    """
    intervals = librosa.effects.split(
        y, top_db=TOP_DB, frame_length=FRAME_LENGTH, hop_length=HOP_LENGTH
    )
    merged = _merge_intervals(intervals, int(MIN_GAP_SEC * sr))
    kept = [(int(s), int(e)) for s, e in merged if (e - s) >= MIN_SEG_SEC * sr]
    if not kept:
        kept = [(0, len(y))]

    return [
        {"seq": i, "title": f"第 {i} 段", "duration": round((e - s) / sr, 3)}
        for i, (s, e) in enumerate(kept, start=1)
    ]


def _merge_intervals(intervals, min_gap: int) -> list[tuple[int, int]]:
    """把间隙小于 min_gap（单位：采样点）的相邻区间并成一段。

    intervals 是 librosa.effects.split 的产物，已按起点升序、互不相交，
    所以一趟线性扫描就够，不需要排序。
    """
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if merged and start - merged[-1][1] < min_gap:
            merged[-1] = (merged[-1][0], int(end))
        else:
            merged.append((int(start), int(end)))
    return merged
```

- [ ] **Step 2: 提交**

```bash
git add app/services/parse_service.py
git commit -m "feat: 唱段切分算法（按停顿切分 + 合并 + 过滤 + 全静音回退）"
```

---

### Task 4: `parse_service` 的任务生命周期与解析管线

**Files:**
- Modify: `app/services/parse_service.py`（在 Task 3 的文件末尾追加）

**Interfaces:**
- Consumes（Task 2/3 的产物）：`task_repo.create/update/get(demo_id, ...)`；`STAGE_*` / `STAGE_RANGE` / `_split_segments`；`app.services.vocal_service.separate_vocal(path: Path, *, max_sec=180) -> np.ndarray`（16k 单声道 float32）；`app.services.vocal_service.SR=16000` / `MAX_AUDIO_SEC=180`
- Consumes（**Task 5 的产物，本任务假设它们已存在**）：`library_repo.get_demo(db, demo_id)`、`library_repo.list_segments(db, demo_id)`、`library_repo.replace_segments(db, demo_id, segments)`、`library_repo.update_audio_duration(db, demo_id, duration_sec)`

> **执行顺序说明**：本任务与 Task 5 互相引用（`parse_service` 用 `library_repo` 的新函数，`library_service` 用 `parse_service.status`）。两个任务**必须在同一次提交前都写完**，否则 import 会失败。若按子代理逐任务执行：**Task 4 的子代理只写代码、不运行任何东西**（本计划无验证环节），提交放在 Task 5 之后由主代理统一做；或者干脆把 Task 4 与 Task 5 派给同一个子代理。**Task 4 与 Task 5 之间不要插入任何需要 import 这两个模块的步骤。**

- [ ] **Step 1: 补齐文件头的 import**

`app/services/parse_service.py` 的 import 段从

```python
import logging

import librosa
import numpy as np

logger = logging.getLogger(__name__)
```

改为

```python
import logging
import uuid
from pathlib import Path

import librosa
import numpy as np
from celery import shared_task
from sqlalchemy.orm import Session

from app.common import storage
from app.common.errors import BusinessError
from app.db import session_scope
from app.models.demo import TeacherDemo
from app.repositories import audio_repo
from app.repositories import library_repo
from app.repositories import parse_task_repo as task_repo
from app.services import vocal_service

logger = logging.getLogger(__name__)
```

- [ ] **Step 2: 在文件末尾追加**

```python
# ===== 提交 =====

def submit(db: Session, demo: TeacherDemo) -> str:
    """上传之后建任务并投进 demucs 队列，立即返回 task_id。

    只收一个已经落库的 demo。**不在这里校验音频文件在不在磁盘上**——B 组
    （analyze_service.submit）会提前查，是因为它的失败要当场回 4xx 给用户；
    这条链路的形态是「上传返回 200 → 前端轮询」，文件丢失的合理表达是任务
    落成 error（前端弹「解析失败」），而不是上传接口报一个跟上传无关的错。
    """
    task_id = uuid.uuid4().hex[:12]
    task_repo.create(
        demo.id,
        status=STATUS_PARSING,
        progress=0,
        # 排队阶段没有对应的 stage（前端的第 1 步「音频上传」在提交前就完成了），
        # 留空而不是硬塞一个 STAGE_*，否则 stage 与 progress 会互相矛盾。
        stage="",
        message="任务已创建，排队中",
        demo_id=demo.id,
        task_id=task_id,
    )
    _dispatch(demo.id, task_id)
    return task_id


def status(db: Session, demo_id: int) -> dict:
    """解析进度快照。redis 里有任务就用它的；没有则按 segments 派生。

    派生这条路径是为 TTL 过期（1 小时）之后兜底：否则详情页会在上传 1 小时后
    显示成「没解析过」，而库里明明躺着分段。派生只可能给出 parsed / unparsed
    两种，且**不带真实的进度**——已经没有任务在跑了，这里给的 0 / 100 只是
    让前端的进度条有个确定形状。

    demo 不存在时抛 404：这条接口是按 demo_id 查的，调用方拿一个不存在的 id
    来问，答案是「没有这条示范曲目」而不是「它没解析过」。
    """
    if library_repo.get_demo(db, demo_id) is None:
        raise BusinessError(404, "示范曲目不存在")

    task = task_repo.get(demo_id)
    if task is None:
        parsed = bool(library_repo.list_segments(db, demo_id))
        return {
            "status": STATUS_PARSED if parsed else STATUS_UNPARSED,
            "progress": 100 if parsed else 0,
            "stage": "",
            "message": "解析完成" if parsed else "尚未解析",
        }

    return {
        "status": task.get("status") or STATUS_UNPARSED,
        "progress": task.get("progress", 0),
        "stage": task.get("stage") or "",
        "message": task.get("message") or "",
    }


# ===== 内部：阶段上报 =====

def _enter_stage(demo_id: int, stage: str, message: str) -> None:
    """上报「进入某阶段」，供前端轮询。

    progress 取该阶段区间的**下界**，语义是「当前正在这个阶段」，
    理由与 analyze_service._enter_stage 相同（那边有完整推导）：
    用完整个区间会让进度条在阶段内部空转，下一个阶段才跳。

    写 redis 失败不在这里兜：任务状态写不进去是致命问题（前端将永远查不到
    这个任务），应该让异常冒到 run_parse 去记日志并落成 error。
    """
    task_repo.update(
        demo_id,
        status=STATUS_PARSING,
        progress=STAGE_RANGE[stage][0],
        stage=stage,
        message=message,
    )


# ===== 内部：入参解析 =====

def _require_demo(db: Session, demo_id: int) -> tuple[TeacherDemo, Path]:
    """取示范曲目并还原出磁盘路径，确认文件真的还在。

    库里登记过、磁盘上却没有，通常是被手工清过 uploads/ 或换了挂载点。
    这种要当 BusinessError 报出来（任务落 error 时 message 直接给用户看），
    而不是让后面 Demucs 抛一个读文件的原生异常。
    """
    demo = library_repo.get_demo(db, demo_id)
    if demo is None:
        raise BusinessError(404, f"示范曲目不存在（teacher_demos.id={demo_id}）")
    if demo.audio_id is None:
        raise BusinessError(400, "该示范曲目没有绑定音频，无法解析")

    audio = audio_repo.get_by_id(db, demo.audio_id)
    if audio is None:
        raise BusinessError(404, "示范曲目绑定的音频记录不存在")

    path = storage.resolve(audio.file_path)
    if not path.is_file():
        raise BusinessError(404, f"音频文件已丢失：{audio.file_path}")
    return demo, path


def _master_duration(path: Path) -> float | None:
    """音频文件的真实全长（秒）。读文件头，不解码。

    读不出来返回 None 而不是 0.0：0 是个会写进 audio_files.duration_sec 的
    「合法」值，列表页会如实显示成 0.0 秒，等于用一个假数据掩盖了读取失败。
    返回 None 时调用方跳过回填，列保持 NULL（前端显示「—」）。

    这个值是**文件真实时长**，不是 MAX_AUDIO_SEC 截断后的长度——列表页显示的
    时长必须如实（spec 4.3），分段只覆盖前 3 分钟这件事由任务完成消息另行说明。
    """
    try:
        return float(librosa.get_duration(path=str(path)))
    except Exception:
        logger.exception("读取音频时长失败：%s", path)
        return None


# ===== 内部：后台执行（Celery）=====

def _dispatch(demo_id: int, task_id: str) -> None:
    """把解析任务投进 **demucs 队列**，立即返回。

    queue="demucs" 是必须的：一条解析占 8–15 分钟，与秒级的 B 组分析同队列
    会把 pitch_comparison.html 拖住。**代价是 worker 必须带 -Q demucs**，
    否则这个队列没人消费、解析永远停在 parsing（CLAUDE.md 与 app/worker.py
    两处都记了这个坑）。

    消息里只传 demo_id：路径、原有时长都由任务自己查库取，理由见模块文档。

    task_id 显式指定成我们自己的 id，不让 Celery 另生成一个——日志里两者对得上号。
    broker 连不上时这里会抛（kombu 的 OperationalError），由全局错误处理器转成
    500；此时 redis 里那条 parsing 记录没人会改，1 小时后随 TTL 过期，前端
    详情页会走 status() 的派生路径显示成 unparsed，不会卡在「解析中」。
    """
    run_parse.apply_async(args=(demo_id,), task_id=task_id, queue="demucs")


@shared_task(name="parse.run")
def run_parse(demo_id: int) -> None:
    """Celery 任务体，worker 进程里的入口。

    **任何异常都必须落成 error 状态**（与 analyze_service.run_analysis 同构）：
    任务抛出的异常若不在这里兜住，前端会一直轮询一个不会到终态的任务——比报错
    更难排查。Celery 自己也会记一份失败，但那份在 worker 日志里，前端看不到。
    """
    try:
        _parse(demo_id)
    except Exception as exc:
        logger.exception("示范库解析任务 %s 失败", demo_id)
        # 可以透给用户的两种文案：BusinessError 的 message 本来就是写给用户看的
        # （见 common/errors.py，全局 handler 也原样返回），NotImplementedError
        # 是开发期的占位说明。其余异常一概不泄漏内部细节——路径、连接串、
        # torch 的报错都不该出现在前端。
        if isinstance(exc, (BusinessError, NotImplementedError)):
            message = str(exc)
        else:
            message = "解析失败，请稍后重试"
        try:
            task_repo.update(demo_id, status=STATUS_ERROR, message=message)
        except Exception:
            # 连状态都写不进去（redis 挂了），只能记日志。**不能让异常逃逸**：
            # 逃出去 Celery 会把这条消息当失败重投，无限重试。
            logger.exception("解析任务 %s 的失败状态写入 redis 也失败了", demo_id)


def _parse(demo_id: int) -> None:
    """解析管线主体：人声分离 → 唱段切分 → 结果入库。

    跑在 worker 进程里，没有请求上下文，所以自己开 session_scope()，不走 get_db()。
    会话**分两段开、中间不留连接**：Demucs 要跑 8–15 分钟，攥着连接不放会把
    连接池（pool_size=5）白占一个。中间那段纯计算不碰数据库。
    """
    # --- 取路径（短会话）---
    with session_scope() as db:
        _, path = _require_demo(db, demo_id)

    # 时长在读文件头这一步拿，与后面的分离无关，先取好省得回填时再开一次会话
    duration = _master_duration(path)

    # --- 人声分离（8–15 分钟，进度停在 20%）---
    _enter_stage(demo_id, STAGE_SEPARATE, "正在分离人声，单条约需 8–15 分钟，请勿关闭页面…")
    y = vocal_service.separate_vocal(path)

    # --- 唱段切分（秒级，进度 50%）---
    _enter_stage(demo_id, STAGE_SEGMENT, "正在按停顿切分唱段…")
    segments = _split_segments(y, vocal_service.SR)

    # --- 结果入库（毫秒级，进度 80%）---
    _enter_stage(demo_id, STAGE_SAVE, "正在写入分段与时长…")
    with session_scope() as db:
        library_repo.replace_segments(db, demo_id, segments)
        if duration is not None:
            library_repo.update_audio_duration(db, demo_id, duration)

    # --- 终态 ---
    #
    # 处理被 MAX_AUDIO_SEC 截断时把话说清楚，而不是让「只有前 3 分钟的分段」
    # 这件事藏在库里。message 会原样显示在前端的处理中弹窗与 toast 上。
    note = f" · {TRUNCATE_NOTE}" if duration and duration > vocal_service.MAX_AUDIO_SEC else ""
    task_repo.update(
        demo_id,
        status=STATUS_PARSED,
        progress=100,
        stage=STAGE_SAVE,
        message=f"解析完成，共 {len(segments)} 段{note}",
    )
```

- [ ] **Step 3: 提交（与 Task 5 合并提交）**

见 Task 4 开头的执行顺序说明。若 Task 4 与 Task 5 由同一个子代理完成，提交放在 Task 5 的 Step 之后，message 用：

```bash
git commit -m "feat: 示范库解析任务的提交/轮询/派生状态与 Demucs 管线"
```

---

### Task 5: `library_repo` 与 `library_service` 扩展

**Files:**
- Modify: `app/repositories/library_repo.py`（追加 4 个函数，现有 2 个不动）
- Modify: `app/services/library_service.py`（改 `demo_library_list` 的返回、新增 `demo_library_get`）

**Interfaces:**
- Consumes: `app.models.demo.TeacherDemo` / `Segment`、`app.models.audio.AudioFile`、Task 4 的 `_split_segments` 产物形状 `[{"seq","title","duration"}]`
- Produces:
  - `library_repo.get_demo(db, demo_id) -> TeacherDemo | None`
  - `library_repo.list_segments(db, demo_id) -> list[Segment]`（按 `seq` 升序）
  - `library_repo.replace_segments(db, demo_id, segments: list[dict]) -> None`（先 DELETE 再 INSERT，只 flush）
  - `library_repo.update_audio_duration(db, demo_id, duration_sec: float) -> None`（只 flush）
  - `library_service.demo_library_get(db, demo_id) -> tuple[TeacherDemo, list[Segment]]`（不存在抛 404）
  - `library_service.demo_library_list(db) -> list[dict]`（行含 `duration` 与 `status`）

- [ ] **Step 1: 重写 `app/repositories/library_repo.py`**

现有文件连文件头都没有（首行直接是 import）。整文件替换为：

```python
# -*- coding: utf-8 -*-
"""teacher_demos / segments 表的数据访问。

写操作只 flush()、不 commit——事务边界在 service 层，理由见 CLAUDE.md。
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import TeacherDemo
from app.models.audio import AudioFile
from app.models.demo import Segment


def get_library_list(db: Session) -> list[TeacherDemo] | None:
    return list(db.scalars(select(TeacherDemo)).all())


def add_library(db: Session, teacher_demo: TeacherDemo) -> TeacherDemo:
    """新增一条示范曲目。只 flush 拿自增 id，提交交给 service 层。"""
    db.add(teacher_demo)
    db.flush()
    return teacher_demo


def get_demo(db: Session, demo_id: int) -> TeacherDemo | None:
    return db.get(TeacherDemo, demo_id)


def list_segments(db: Session, demo_id: int) -> list[Segment]:
    """按 seq 升序取某 demo 的分段。前端就按这个顺序显示「第 N 段」。"""
    return list(db.scalars(
        select(Segment).where(Segment.demo_id == demo_id).order_by(Segment.seq)
    ).all())


def replace_segments(db: Session, demo_id: int, segments: list[dict]) -> None:
    """整批替换某 demo 的分段：先按 demo_id DELETE，再 INSERT。

    幂等的关键：同一 demo 重跑解析不会累积脏行（解析任务整体可重入）。
    不用「按 seq upsert」是因为段数可能变少（阈值调过、素材换过），
    upsert 会留下上一轮多出来的尾巴。

    参数是纯 dict（[{seq,title,duration}]）而不是 ORM 对象：分段在 worker
    进程里用 numpy 算出来，那边根本没有 Session。

    lyrics_json 一律 NULL——第 20 条：没有 ASR 组件，音频给不出汉字。
    segments 表也没有 start/end 列（本次不加），所以位置信息只有 seq 与 duration。

    只 flush 不 commit；DELETE 由 Core 语句当场发出，必然排在 flush 的
    INSERT 之前，不会出现「新行插进去又被删掉」。
    """
    db.execute(delete(Segment).where(Segment.demo_id == demo_id))
    db.add_all([
        Segment(
            demo_id=demo_id,
            seq=s["seq"],
            title=s["title"],
            lyrics_json=None,
            duration=s["duration"],
        )
        for s in segments
    ])
    db.flush()


def update_audio_duration(db: Session, demo_id: int, duration_sec: float) -> None:
    """把音频的真实全长回填到 audio_files.duration_sec。

    回填的是**文件真实时长**，不是 MAX_AUDIO_SEC 截断后的长度——列表页显示的
    时长必须如实（spec 4.3）。demo 或 audio 缺失时静默返回：回填是锦上添花，
    不该因为它失败而让整轮解析落成 error。
    """
    demo = db.get(TeacherDemo, demo_id)
    if demo is None or demo.audio_id is None:
        return
    audio = db.get(AudioFile, demo.audio_id)
    if audio is None:
        return
    audio.duration_sec = duration_sec
    db.flush()
```

- [ ] **Step 2: 重写 `app/services/library_service.py`**

整文件替换为：

```python
# -*- coding: utf-8 -*-
"""示范库（teacher_demos / segments）的业务逻辑。

事务边界在本层：写操作显式 commit。
"""

from sqlalchemy.orm import Session

from app.common.errors import BusinessError
from app.models import TeacherDemo
from app.models.demo import Segment
from app.repositories import library_repo
from app.services import parse_service


def demo_library_list(db: Session) -> list[dict]:
    """列表用的行：把 audio_files.duration_sec 与解析状态摊平进来。

    status 逐行查一次 redis（parse_service.status 的派生路径还要查一次库）。
    示范曲目是「剧目级」的量（演示数据 4 条，真实使用量级是几十），不值得为它
    做批量 pipeline 或 join；真到几百条再优化，这条注释留在这里当锚点。

    返回 dict 而不是 ORM 对象：这里已经要摊平两个来源（audio 关系 + redis），
    再让 api 层去 ORM 上拼一遍等于把同一件事写两处。
    """
    rows = []
    for demo in library_repo.get_library_list(db) or []:
        rows.append({
            "id": demo.id,
            "title": demo.title,
            "role": demo.role,
            "banshi": demo.banshi,
            "duration": demo.audio.duration_sec if demo.audio else None,
            "elo_difficulty": demo.elo_difficulty,
            "created_at": demo.created_at,
            "status": parse_service.status(db, demo.id)["status"],
        })
    return rows


def demo_library_get(db: Session, demo_id: int) -> tuple[TeacherDemo, list[Segment]]:
    """取一条示范曲目及其分段。不存在抛 404。

    同时返回 demo 与 segments（而不是让调用方再查一次分段）：详情接口两个都要，
    分两次查会在「demo 存在但分段刚好被重跑清空」的瞬间读到不一致的组合。
    """
    demo = library_repo.get_demo(db, demo_id)
    if demo is None:
        raise BusinessError(404, "示范曲目不存在")
    return demo, library_repo.list_segments(db, demo_id)


def demo_library_add(
    db: Session,
    *,
    title: str,
    role: str | None = None,
    banshi: str | None = None,
    audio_id: int | None = None,
) -> TeacherDemo:
    """新增示范曲目。事务边界在本层，写操作显式 commit。

    audio_id 由调用方传入（audio_files flush 出来的自增主键），本层只负责把
    外键写进去，不反查、不补建。

    下面这次 commit 同时提交前一步 save_upload(commit=False) 留在同一会话里的
    audio_files 行——示范曲目上传要的就是「两行一次提交」：任何一边失败，
    两边都留不下半条记录。

    **解析任务的投递不在这里做**：submit() 需要 demo.id，而这条 commit 之后
    才轮到 api 层调 parse_service.submit()。若 redis 挂了导致 submit 失败，
    上传接口会回 500，但 teacher_demos 那行已经落库、segments 为空——此时
    详情页的派生状态恰好是 unparsed（「没解析过」），是一句实话，用户可以
    重新上传。这个顺序是刻意选的：先落库、后投任务。
    """
    demo = TeacherDemo(
        title=title,
        # 表单下拉框未选时提交的是空串，落库统一成 NULL：
        # 空串会让「按行当筛选」之类的查询多出一个无意义的取值。
        role=role or None,
        banshi=banshi or None,
        audio_id=audio_id,
    )
    library_repo.add_library(db, demo)
    db.commit()
    return demo
```

- [ ] **Step 3: 提交**

若 Task 4 由别的子代理完成，把两个文件一起提交：

```bash
git add app/repositories/library_repo.py app/services/library_service.py \
        app/services/parse_service.py
git commit -m "feat: 分段读写、详情查询、列表行组装与解析任务生命周期"
```

---

### Task 6: 接口层重写 + schema 修复 + `worker.py` 文档

**Files:**
- Rewrite: `app/schemas/demo_library.py`
- Rewrite: `app/api/demo_library.py`
- Modify: `app/worker.py`（docstring）

**Interfaces:**
- Consumes: Task 4 的 `parse_service.submit/status`；Task 5 的 `library_service.demo_library_list/demo_library_get`；`audio_service.save_upload(..., commit=False)`
- Produces: 4 条 HTTP 接口 — `POST /api/demo/library/upload`（登录）→ `{demo_id, task_id}`；`GET /api/demo/library/list`（登录+教师）→ 数组；`GET /api/demo/library/<int:demo_id>`（登录）→ 详情；`GET /api/demo/library/<int:demo_id>/parse/status`（登录）→ `{status,progress,message,stage}`

**关于 `list` 保留 `@teacher_required`**：本轮「权限先不管」的口径是**不新增限制，也不移除已有校验**。它目前只被后端调用（前端仍走 `DEMO_DATA`）。

- [ ] **Step 1: 重写 `app/schemas/demo_library.py`**

```python
# -*- coding: utf-8 -*-
"""示范库接口的出参模型。

**role / banshi / elo_difficulty / created_at / duration 一律可空**，因为
teacher_demos 与 audio_files 里这几列在 DDL 上都可空（见 schema.sql）：
写成非空的话，库里只要有一行空值，列表接口就整片 500。上一版的
`role: str` / `banshi: str` 正是这个错。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DemoLibraryListOut(BaseModel):
    """列表行。status 由 parse_service 逐行算出（redis 或派生）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    role: str | None = None
    banshi: str | None = None
    duration: float | None = None
    elo_difficulty: float | None = None
    created_at: datetime | None = None
    status: str


class SegmentOut(BaseModel):
    """一个唱段。**没有起止时间**——segments 表没有 start/end 列（本次不加），

    位置信息只有 seq；前端显示「第 N 段 · 6.6s」。逐字歌词（lyrics_json）
    按第 20 条一律不写，所以这里也不暴露这个字段。
    """

    seq: int | None = None
    title: str | None = None
    duration: float | None = None


class DemoLibraryDetailOut(BaseModel):
    """详情。url 由 api 层的 url_for 生成，指向 B5。

    `elo_difficulty` 与列表模型同字段同语义——详情页的难度条要读它，所以这里也必须有；
    库里是默认值 1000 时前端按「取不到有效值」显示「待校准」，不在本层过滤。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    role: str | None = None
    banshi: str | None = None
    duration: float | None = None
    elo_difficulty: float | None = None
    created_at: datetime | None = None
    status: str
    segments: list[SegmentOut] = []
    url: str | None = None
```

- [ ] **Step 2: 重写 `app/api/demo_library.py`**

```python
# -*- coding: utf-8 -*-
"""示范库接口（`DOC_ISSUES.md` 第 16–20 条 / spec `2026-09-21-demo-library-parse-design.md`）。

    POST /api/demo/library/upload                     登录  上传示范音频，落库并自动投解析任务
    GET  /api/demo/library/list                       登录+教师  示范曲目列表（带解析状态）
    GET  /api/demo/library/<int:demo_id>              登录  详情（含分段列表与音频 url）
    GET  /api/demo/library/<int:demo_id>/parse/status 登录  解析进度（前端每 3 秒轮询）

本层只做三件事：校验入参 → 调 service → 组装响应。不写 SQL、不写业务规则、
不写 try/except（错误由 app/common/errors.py 的全局 handler 兜）。
"""

from pathlib import Path

from flask import request, session, url_for

from app.api import api_bp
from app.common.decorators import current_user_id, login_required, teacher_required
from app.common.errors import BusinessError
from app.db import get_db
from app.response import ok
from app.schemas.demo_library import DemoLibraryDetailOut, DemoLibraryListOut
from app.services import audio_service, library_service, parse_service


@api_bp.route("/demo/library/upload", methods=["POST"])
@login_required
def demo_library_upload():
    """上传示范音频：落盘 + 建两行 + 投解析任务，返回 {demo_id, task_id}。

    鉴权只要求登录（本轮「权限先不管」的决策，见 spec 第 2 节）。`access`
    仍按角色取值——`audio_service.save_upload` 只允许教师设 public。
    """
    file = request.files.get("audio")
    if file is None or not file.filename:
        raise BusinessError(400, "缺少音频文件（multipart 字段名应为 audio）")

    db = get_db()
    # commit=False：这一行先不提交，和下面 teacher_demos 那行合成一次事务，
    # 由 demo_library_add() 末尾统一 commit（提交点见 service 层的说明）。
    audio = audio_service.save_upload(
        db,
        uploader_id=current_user_id(),
        is_teacher=session.get("role") == "teacher",
        access=request.form.get("access", "private"),
        file=file,
        commit=False,
    )

    demo = library_service.demo_library_add(
        db,
        # title 在库里是 NOT NULL，前端没填时退回文件名（不含扩展名）
        title=request.form.get("title") or Path(file.filename).stem,
        role=request.form.get("role"),
        banshi=request.form.get("banshi"),
        audio_id=audio.id,
    )

    # 提交之后才投任务：submit() 需要 demo.id，而 redis 那条记录要在「两行都
    # 落定」之后才存在，否则任务可能先跑起来、查库时 demo 还没提交。
    task_id = parse_service.submit(db, demo)
    return ok({"demo_id": demo.id, "task_id": task_id})


@api_bp.route("/demo/library/list", methods=["GET"])
@login_required
@teacher_required
def demo_library_list():
    """示范曲目列表。

    `@teacher_required` 是工作区里**已有**的校验，本轮口径是「不新增限制，
    也不移除已有校验」，所以保留（spec 4.5）。它目前没有调用方——前端
    `fetchDemos` 仍走 `DEMO_DATA` 演示数据。
    """
    rows = library_service.demo_library_list(get_db())
    return ok([DemoLibraryListOut.model_validate(r).model_dump(mode="json") for r in rows])


@api_bp.route("/demo/library/<int:demo_id>", methods=["GET"])
@login_required
def demo_library_get(demo_id):
    """示范曲目详情。含分段列表与可播放 url。

    `<int:demo_id>` 的转换器与 B5 同理：非数字路径在**路由层**就 404，
    不进视图，畸形输入也就没有变成 500 的机会。
    """
    db = get_db()
    demo, segments = library_service.demo_library_get(db, demo_id)
    return ok(DemoLibraryDetailOut.model_validate({
        "id": demo.id,
        "title": demo.title,
        "role": demo.role,
        "banshi": demo.banshi,
        "duration": demo.audio.duration_sec if demo.audio else None,
        # 手工拼的 dict 必须逐个键写全：`from_attributes=True` 只让 pydantic 能从
        # **对象属性**取值，对 dict 输入不生效——不在 dict 里的键一律落声明的默认值
        # None，不会去 ORM 对象上找。漏掉这行的话详情接口的 elo_difficulty 恒为
        # null，而列表接口（走 service 的行 dict）给的是真值，同一首曲子在两个接口
        # 上会显示成两种难度。
        "elo_difficulty": demo.elo_difficulty,
        "created_at": demo.created_at,
        "status": parse_service.status(db, demo_id)["status"],
        "segments": [
            {"seq": s.seq, "title": s.title, "duration": s.duration} for s in segments
        ],
        # 同 B1：url 由 url_for 生成，前端不必硬编码 /api/audio/<id>——硬编码
        # 路径与后端漂移正是 DOC_ISSUES 第 1 条记的那类问题。
        # **不返回 audio_files.file_path**：那是服务端存储名，common/storage.py
        # 承诺不把服务器目录结构泄漏到接口响应里。
        "url": url_for("api.audio_download", file_id=demo.audio_id) if demo.audio_id else None,
    }).model_dump(mode="json"))


@api_bp.route("/demo/library/<int:demo_id>/parse/status", methods=["GET"])
@login_required
def demo_library_parse_status(demo_id):
    """解析进度。前端 startPolling 每 3 秒调一次，拿到 parsed/error 才停表。

    状态从哪来（redis 还是按 segments 派生）由 service 决定，见
    `parse_service.status` 的 docstring。
    """
    return ok(parse_service.status(get_db(), demo_id))
```

- [ ] **Step 3: 补 `app/worker.py` 的 docstring**

在启动命令那一段后面追加：

```python
另外，**示范库解析任务走的是独立的 `demucs` 队列**（`parse_service._dispatch`
里 `apply_async(queue="demucs")`）。不带 `-Q demucs` 的 worker 不消费这个队列：

    celery -A app.worker:celery_app worker -Q demucs --concurrency=1 --loglevel=info

漏掉的症状是「上传成功但解析永远停在 parsing」——前端一直轮询，没有任何报错。
`--concurrency=1` 而不是 B 组的 2：`torch.set_num_threads(4)`（`demucs_threads`）
已经把 4 个核吃满，再开第二个进程只会互相抢核，两处数值要一起看
（见 `app/config.py` 里 `demucs_threads` 的注释）。
```

- [ ] **Step 4: 清理 `app/api/uploads/`（必须在本任务改写完之后）**

```bash
rmdir app/api/uploads 2>/dev/null && echo "已删除 app/api/uploads" || echo "目录不存在（已是干净的）"
```

**为什么要放在这里**：Task 1 Step 7 删过一次，但**只要 `app/api/demo_library.py` 里那两行模块级 `UPLOAD_DIR = ...` / `os.makedirs(UPLOAD_DIR, exist_ok=True)` 还在，任何 import 到这个模块的动作（起 Flask、跑脚本、甚至 `python -c "import app.api"`）都会把它重新建出来。** 本步骤 2 把这两行删掉了，病根才除——所以清理必须排在改写之后。目录为空时 `rmdir` 才成功；非空就说明里面有真文件，**不要 `rm -rf`**，停下来报告。

- [ ] **Step 5: 提交**

```bash
git add app/schemas/demo_library.py app/api/demo_library.py app/worker.py
git commit -m "feat: 示范库上传/列表/详情/解析状态四条接口"
```

---

### Task 7: 前端 `demo_library.html` 接线

**Files:**
- Modify: `demo_library.html`（多处；行号为改动前的当前值）

**Interfaces:**
- Consumes: Task 6 的 4 条接口

**严格限定范围**：`fetchDemos`（列表继续用 `DEMO_DATA`）、`renderDemoList`、上传入口的角色可见性、`doUpload` 里 `access` 按角色取值的逻辑**都不改**。

- [ ] **Step 1: `fetchStatus` 改调真接口（`:1685-1716`）**

整段替换为：

```javascript
        // 解析进度：真接口 GET /api/demo/library/<id>/parse/status
        // 取不到（404 / 已过期）返回 null，由 startPolling 按超时收尾——
        // 这里不能返回一个假对象，否则轮询永远不会停。
        async function fetchStatus(demoId) {
		  try {
			const res = await fetch(`${API_BASE}/api/demo/library/${demoId}/parse/status`);
			if (!res.ok) return null;
			const body = await res.json();
			return body.data || null;
		  } catch (e) { return null; }
		}
```

- [ ] **Step 2: `fetchDemoDetail` 接真接口（`:1668-1682`）**

整段替换为：

```javascript
        // 详情：DEMO_DATA 命中走原演示分支（4 条演示数据不变）；未命中调真接口，
        // 把响应映射成 renderDetail 认识的对象。
        //
        // versions / techniques / timeline 一律给空数组：renderDetail 已有
        // 「空则不渲染该区块」的分支（见 renderDetail 里三处 length 判断），
        // 所以这三个空值会让「多版本管理」「技法维度」「逐字时间轴」自动隐藏
        // ——这正是本轮要的：真实数据里没有这三样东西（没有 ASR、不写
        // lyrics_json，第 20 条）。
        async function fetchDemoDetail(demoId) {
		  const mock = DEMO_DATA.find(d => d.id === demoId);
		  if (mock) {
			await new Promise(resolve => setTimeout(resolve, 200));
			renderDetail(mock, mock.versions || [], mock.parse_result?.timeline || []);
			return;
		  }
		  try {
			const res = await fetch(`${API_BASE}/api/demo/library/${demoId}`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const body = await res.json();
			const d = body.data;
			renderDetail({
			  id: d.id,
			  title: d.title,
			  role: d.role,
			  banshi: d.banshi,
			  bpm: 0,
			  duration: d.duration,
			  elo_difficulty: d.elo_difficulty,
			  status: d.status,
			  segments: d.segments || [],
			  url: d.url,
			  parse_result: null,
			}, [], []);
		  } catch (e) {
			showToast("error", "加载详情失败", e.message);
		  }
		}
```

- [ ] **Step 3: `startPolling` 加超时上限（`:2056-2074`）**

整段替换为：

```javascript
        // 轮询上限：3 秒 × 600 = 30 分钟。Demucs 全长素材实测 8–15 分钟，
        // 留一倍余量。没有这个上限的话，任务若因为 worker 没带 -Q demucs 而
        // 永远停在 parsing，定时器会一直转下去、弹窗永远关不掉（原来的实现
        // 就是这个毛病：mock 对未知 id 返回 null，而 `if (!st) return;`
        // 让 setInterval 空转到天长地久）。
        const POLL_MAX = 600;
        function startPolling(demoId) {
            if (pollTimer) clearInterval(pollTimer);
            let ticks = 0;
            renderParseFlow("parsing", 0, "等待解析...");
            pollTimer = setInterval(async () => {
                ticks += 1;
                // 上限检查必须放在取状态**之前**、且与 st 取值无关：worker 没带
                // -Q demucs 时每轮都拿到 truthy 的 parsing（redis TTL 过期后又
                // 派生 truthy 的 unparsed），把检查放进 `if (!st)` 里等于在最常见
                // 的卡死场景下完全不生效——表停不下来、弹窗永不自关。
                if (ticks >= POLL_MAX) {
                    clearInterval(pollTimer); pollTimer = null;
                    renderParseFlow("error", 0, "解析超时，请查看服务器日志或重新上传");
                    renderProcessingModal("error", 0, "解析超时，请查看服务器日志或重新上传");
                    showToast("error", "解析超时", "解析超时，请查看服务器日志或重新上传");
                    return;
                }
                const st = await fetchStatus(demoId);
                if (!st) {
                    // 404 / 已过期：这一轮不动作，等下一轮或上面的上限兜底
                    return;
                }
                renderParseFlow(st.status, st.progress, st.message);
                renderProcessingModal(st.status, st.progress, st.message);
                if (st.status === "parsed" || st.status === "error") {
                    clearInterval(pollTimer);
                    pollTimer = null;
                    renderProcessingResult(st.status);
                    await fetchDemos();
                    if (activeDemoId === demoId) await fetchDemoDetail(demoId);
                    showToast(st.status === "parsed" ? "success" : "error",
                        st.status === "parsed" ? "解析完成" : "解析失败", st.message);
                    setTimeout(() => hideProcessingModal(), 3000);
                }
            }, 3000);
        }
```

- [ ] **Step 4: `renderDetail` 的 Elo 容错（`:1801-1807`）**

真数据的 `elo_difficulty` 是库默认 `1000`（第 19 条不写这个字段），原来的 `demo.elo_difficulty.toFixed(2)` 会渲染成 `1000.00` 且恒判「高难度」；`elo_difficulty` 为 null 时还会直接抛异常。整段替换为：

```javascript
            // Elo 容错：真实数据的 elo_difficulty 是库默认值 1000（第 19 条：
            // 文档只给了名称、没有算法与分值域，本轮不实现解析写值）。
            // 原来的 `>= 0.85` / `>= 0.7` 阈值是按 0–1 归一化设计的，喂进 1000
            // 会恒判「高难度」并显示成 1000.00，等于宣称一个算不出来的结论。
            // 取不到有效值（null / 非有限数 / > 1）时显示「待校准」，难度条不渲染。
            const eloRaw = demo.elo_difficulty;
            const eloValid = typeof eloRaw === "number" && isFinite(eloRaw) && eloRaw >= 0 && eloRaw <= 1;
            const eloColor = !eloValid ? "var(--text-muted)"
                : (eloRaw >= 0.85 ? "var(--danger)" : (eloRaw >= 0.7 ? "var(--warning)" : "var(--success)"));
            const eloBorder = !eloValid ? "var(--border-light)"
                : (eloRaw >= 0.85 ? "rgba(184,58,47,0.25)" : (eloRaw >= 0.7 ? "rgba(201,168,76,0.25)" : "rgba(74,143,107,0.25)"));
            if (statsEl) statsEl.innerHTML = `
            <div class="detail-stat"><div class="val">${versions.length}</div><div class="lab">版本数</div></div>
            <div class="detail-stat"><div class="val">${demo.parse_result?.word_count || 0}</div><div class="lab">标注规则</div></div>
            <div class="detail-stat"><div class="val">${demo.parse_result?.word_count || 0}</div><div class="lab">解析字数</div></div>
            <div class="detail-stat"><div class="val">${demo.parse_result?.parse_time_sec || 0}s</div><div class="lab">解析耗时</div></div>
            <div class="detail-stat" style="border-color:${eloBorder}">
              <div class="val" style="color:${eloColor}">${eloValid ? eloRaw.toFixed(2) : "待校准"}</div>
              <div class="lab">动态难度(Elo)</div>
            </div>`;
```

原来那两行 `const eloInfo = getEloLabel(...)` 与 `if (statsEl) statsEl.innerHTML = ...` 整体被上面这段替换。**新代码不声明 `eloInfo`**：上面那段已把这项职责拆成 `eloValid` / `eloColor` / `eloBorder`，再留一个没人读的 `eloInfo` 就是死代码（评审会把它当缺陷提）。替换后 `grep -n "eloInfo" demo_library.html` 应当只剩 `renderDemoList` 里的两处引用（`:1747` / `:1765`，服务于演示数据），`getEloLabel` 因此不会变成孤儿函数。

- [ ] **Step 5: 新增分段列表区块**

a) 在详情区块里、`versionSection` 之前（`:1357` 上方）插入 DOM：

```html
                    <!-- 唱段列表（真实解析产物；无分段时整块隐藏） -->
                    <div style="margin-bottom:16px" id="segmentSection">
                        <div style="font-size:13px;font-weight:700;color:var(--text-primary);margin-bottom:8px">🎼 唱段列表</div>
                        <div class="version-list" id="segmentList"></div>
                    </div>
```

（复用 `version-list` 那套样式，不新增 CSS——本页无共享样式文件，新增类名会在跨页漂移上再加一笔。）

b) 在 `renderDetail` 的 `const timelineSectionEl = ...` 那一行后面补上元素引用：

```javascript
            const segmentListEl = document.getElementById("segmentList");
            const segmentSectionEl = document.getElementById("segmentSection");
```

c) 在 `renderDetail` 的 `if (versionSectionEl) { ... }` 之后插入渲染块：

```javascript
            // 唱段列表：真实解析产物（第 20 条：没有逐字歌词，所以只有序号与时长）。
            // segments 表没有起止时间列，做不了「点击定位到该段」，只显示时长。
            if (segmentSectionEl) {
                const segs = demo.segments || [];
                if (segs.length && segmentListEl) {
                    segmentSectionEl.style.display = "";
                    segmentListEl.innerHTML = segs.map(s => `
                <div class="version-item">
                  <div class="version-name">${esc(s.title || ("第 " + s.seq + " 段"))}</div>
                  <div class="version-meta">时长 ${Number(s.duration || 0).toFixed(1)}s</div>
                </div>`).join("");
                } else { segmentSectionEl.style.display = "none"; }
            }
```

- [ ] **Step 6: 步骤文案（两处数组）**

`:1863` 的 `renderParseFlow` 里：

```javascript
            const steps = [
                { label: "音频上传", t: 0 },
                { label: "Demucs 分离", t: 20 },
                { label: "唱段结构解析", t: 50 },
                { label: "结构化输出", t: 80 },
                { label: "存入基准库", t: 100 },
            ];
```

`:1920` 的 `renderProcessingModal` 里（同步去掉 `elo` 一项、去掉 `vocalparse` 的键名与图标）：

```javascript
            const steps = [
                { key: "upload", label: "音频上传", icon: "📤", t: 0 },
                { key: "demucs", label: "Demucs 人声分离", icon: "🎚️", t: 20 },
                { key: "structure", label: "唱段结构解析", icon: "🎼", t: 50 },
                { key: "output", label: "结构化输出", icon: "📊", t: 80 },
                { key: "save", label: "存入基准库", icon: "💾", t: 100 },
            ];
```

**为什么去掉 VocalParse**：本项目没有 VocalParse 这个组件（第 17 条），留着等于在 UI 上宣称一个不存在的能力。

- [ ] **Step 7: 页头副标题与时间轴标题**

`:1286`：

```html
                    <p>上传示范音频 → 人声分离与唱段切分 → 存入基准库</p>
```

`:1364` 的「🎵 VocalParse 解析结果 · 歌词-音高-时值时间线」改为：

```html
                        <div style="font-size:13px;font-weight:700;color:var(--text-primary);margin-bottom:8px">🎵 逐字歌词 · 音高-时值时间线</div>
```

（这个区块对真实数据本就是隐藏的，标题里的 VocalParse 同样是无实现的宣称。）

- [ ] **Step 8: `doUpload` 解开响应信封（**必改项**）**

`:2041-2046`。**不改这里，整条上传→轮询链路走不起来**：新上传接口回的是统一信封 `{"code":0,"message":"ok","data":{"demo_id":…,"task_id":…}}`，而 `doUpload` 读的是**顶层** `data.demo_id`，拿到的是 `undefined`，于是 `showProcessingModal(name, undefined)`、`fetchDemoDetail(undefined)`、`startPolling(undefined)` 一路带 `undefined` 去请求 `/api/demo/library/undefined/parse/status`——被路由的 `<int:demo_id>` 转换器挡在视图之外直接 404，前端只能靠 Step 3 的 `POLL_MAX` 兜到超时。

把这三行：

```javascript
                const data = await res.json();
                hideUploadModal();
                showToast("success", "上传成功", data.message);
```

改为：

```javascript
                const body = await res.json();
                // 后端是统一信封 {code,message,data}，真正的内容在 data 里。
                // 原来读顶层 data.demo_id 拿到的是 undefined，整条
                // 上传 → 详情 → 轮询的链路会带着 undefined 去请求
                // /api/demo/library/undefined/parse/status（被 <int:demo_id> 挡成 404）。
                const data = body.data || {};
                if (!data.demo_id) throw new Error(body.message || "服务端未返回 demo_id");
                hideUploadModal();
                // body.message 恒为 "ok"（信封顶层的固定文案），说不了任何事；
                // 真正有意义的是 task_id —— 用户报障时能拿去 grep worker 日志。
                showToast("success", "上传成功", `已提交解析任务 ${data.task_id || ""}`.trim());
```

**下面的 `data.demo_id` 三处（`:2046` / `:2048` / `:2050` / `:2051`）不要动**——它们现在读的是已经从信封里取出来的 `data` 对象，改完上面三行就都是对的了。

- [ ] **Step 9: 静态 HTML 里剩下的 VocalParse / Elo 文案**

前面 Step 6/7 改的是 JS 里的数组与标题，但静态 HTML 里还有 5 处同名文案——页面在任何解析发生之前显示的就是它们，不改等于 UI 上照样挂着两个不存在的组件（第 17 条：本项目没有 VocalParse；第 19 条：不写 `elo_difficulty`，谈不上「已校准」）。

a) `:1296` 卡片标题：

```html
                        解析流程
```

b) `:1299-1311` 的静态占位步骤条——现在是**六步含 Elo**，要改成与 Step 6 的五步数组一致的**五步**（t 值 0/20/50/80/100）。整块替换为：

```html
                <div class="parse-flow">
                    <div class="parse-step active">音频上传</div>
                    <span class="parse-arrow">→</span>
                    <div class="parse-step active">Demucs 分离</div>
                    <span class="parse-arrow">→</span>
                    <div class="parse-step active">唱段结构解析</div>
                    <span class="parse-arrow">→</span>
                    <div class="parse-step active">结构化输出</div>
                    <span class="parse-arrow">→</span>
                    <div class="parse-step active">存入基准库</div>
                </div>
```

c) `:1428` 与 `:1961` 的 `VocalParse 智能分析引擎工作中` → （两处同样改）

```html
                <p id="processingSubtitle">人声分离与唱段切分引擎工作中</p>
```

`:1961` 是 JS 里给同一个元素赋同一句话（`if (subtitleEl) subtitleEl.textContent = ...`），改成：

```javascript
                if (subtitleEl) subtitleEl.textContent = "人声分离与唱段切分引擎工作中";
```

d) `:1323` 「已入库示范」的列表头 `共 5 首 · Elo 动态难度已校准` 里的「Elo 动态难度已校准」是一句无实现支撑的宣称（本轮不写 `elo_difficulty`，没有校准这回事），删掉后半句：

```html
                        <span style="font-size:12px;color:var(--text-muted)">共 5 首</span>
```

（`共 5 首` 是演示数据 `DEMO_DATA` 的条数，属列表仍走演示数据这条既有决策，不动。）

- [ ] **Step 10: 静态自查（不是验证，是防止改错行）**

```bash
grep -n "VocalParse" demo_library.html          # 预期：无输出
grep -n "Elo 难度校准" demo_library.html         # 预期：无输出
grep -n "POLL_MAX\|segmentList\|eloValid\|body.data" demo_library.html | head
```

（**注意**：这条 grep 只有在 Step 9 也做完的前提下才为空。`demo_library.html` 里 `Elo` 字样**不会**全清——`getEloLabel`(:1719)、`renderDemoList` 里的 `eloInfo`(:1747)/`diff-badge`(:1765)、以及详情页的「动态难度(Elo)」标签都保留，它们要么服务于演示数据、要么是本轮认可的容错显示。要清的是「Elo 难度校准」这个**步骤名**。）

- [ ] **Step 11: 提交**

```bash
git add demo_library.html
git commit -m "feat: 示范库页面解析链路接真接口，补分段列表与超时收尾"
```

---

### Task 8: 文档同步与噪音还原

**Files:**
- Modify: `CLAUDE.md`
- Modify: `DOC_ISSUES.md`
- Modify: `app/config.py`（Step 4）
- Modify: `app/services/parse_service.py`（Step 5）
- Restore: `app-d.py`、`static/echarts.min.js`（CRLF 噪音）
- Add: `docs/superpowers/plans/2026-09-22-demo-library-parse.md`（Step 6；仓库里前三个功能都把 plan 与 spec 一并入库——`git ls-files docs/superpowers/plans/` 可见 `2026-09-11`/`2026-09-15`/`2026-09-20` 三份——本计划入库后分支才与既有约定一致）

- [ ] **Step 1: 还原两处 CRLF 噪音**

这两处 diff **全部是 LF → CRLF 换行符变更，无任何实质修改**（spec §3）：

```bash
git checkout -- app-d.py static/echarts.min.js
git status --short       # 确认这两个文件不再出现在改动列表里
```

- [ ] **Step 2: `DOC_ISSUES.md` 对齐第 16–20 条**

**不新增条目**（spec §7.2），只把各条「当前处理」里与最终实现不符的措辞改掉：

- 第 16 条：确认记着「实现用 Demucs、B 组 HPSS 不动」——已实现，无需改；补一句权重来源（ModelScope 副本 + sha256 闸门）与 CPU-only 轮子。
- 第 17 条：把自拟的接口形状改成**最终 4 条**（`/api/demo/library/upload`、`/list`、`/<int:demo_id>`、`/<int:demo_id>/parse/status`）。
- 第 18 条：确认状态词表 `parsing`/`parsed`/`error`（+ 派生路径的 `unparsed`）已落地，Elo 步骤已从两处步骤文案里去掉。
- 第 19 条：确认解析**不写** `elo_difficulty`。**另有两句被 Task 7 改成了不实，一并修掉**（都在本条内，且它们与第 18 条的改法直接矛盾，不改就是「文档自己跟自己打架」）：
  - `:404` 现在写「前端 `:1925` 那一步的文案「Elo 难度校准」正是照抄功能清单这句」——`demo_library.html:1925` 那个 `elo` 步骤已被 Task 7 Step 6 删除，这行引文指向一个不存在的行号。改成过去时并交代去向：「改动前前端 `:1925` 那一步的文案「Elo 难度校准」正是照抄这句，本次已随第 18 条一并移除」。它作为「文档原文照抄进了前端」的证据仍然成立，改的只是时态与 `:1925` 这个失效引用。
  - `:406` 现在写「前端详情页的 Elo 展示位**留空**」——Task 7 Step 4 之后详情页显示的是**「待校准」**，且难度条按 `eloValid` 判断不渲染（边框与颜色退到 muted token），不是「留空」。改成「前端详情页的 Elo 位显示为『待校准』、难度条不渲染（`getEloLabel` 仍服务于列表页的演示数据）」。同句里「`getEloLabel` 的阈值按哪套定」保留——该函数还在（`renderDemoList` 用），这个问题依然有效。
- 第 20 条：确认 `lyrics_json` 恒 NULL。

- [ ] **Step 3: `CLAUDE.md` 三处**

a) **运行方式**一节，在 B2 的 worker 说明后面加：

```markdown
- **示范库解析链路（`/api/demo/library/*`）必须另起一个带 `-Q demucs` 的 worker，否则解析任务永远停在 `parsing`。** 解析走的是专用队列（一次 8–15 分钟，与秒级的 B 组分析分开）：
  `celery -A app.worker:celery_app worker -Q demucs --concurrency=1 --loglevel=info`
  **不带 `-Q demucs` 的 worker 不消费这个队列**，症状是「上传成功、前端一直转圈、没有任何报错」。`--concurrency=1` 是因为 `torch.set_num_threads(4)`（`demucs_threads`）已经把 4 个核吃满（见 `app/config.py` 的注释），两处数值要一起看。
```

b) **依赖**一节加：

```markdown
- **`requirements-demucs.txt`** 是示范库解析链路（Demucs）的 CPU-only 依赖，由 `requirements.txt` 末尾一行 `-r` 带进来。单独成文件**不是**为了避免全局改道——pip 对 `-r` 引入文件里的 `--index-url` 是整次会话全局生效的，且那两个选项行不带平台标记，Mac 上一样生效（清华是 PyPI 全量镜像，所以 Mac 也装得通）；真实的收益只是**主清单里不嵌入镜像 URL**，换源或上内网时不必动主文件。三行依赖都带 `; sys_platform == "linux"`——PyTorch 自 2.2.2 起不再发布 macOS x86_64 轮子，Mac 上必须整段跳过。权重（约 84MB，`models/` 已 gitignore）用 `scripts/fetch_demucs_weights.sh` 取，离线部署改为人工拷贝。相关背景见 `DOC_ISSUES.md` 第 16 条。
```

**同节第一句要一并顺掉**：那句现在是「依赖清单是 **`requirements.txt`**（64 个包全部 `==` 钉死：13 个直接依赖 + 51 个传递依赖，在 macOS Intel 上实测通过）」。`requirements.txt:116` 加了 `-r requirements-demucs.txt` 之后，`pip install -r requirements.txt` 在 Linux 上装的已经不止 64 个包——这句再照字面读就不实了，而这正是 Task 8 要清的那类「文档与代码实情不符」。把它限定到「本文件自身」：

```markdown
依赖清单是 **`requirements.txt`**（本文件自身钉死 64 个包，全部 `==`：13 个直接依赖 + 51 个传递依赖，在 macOS Intel 上实测通过；文件末尾一行 `-r` 另把 Demucs 的 CPU-only 三项带进来，见下条）。
```

c) **架构**一节（数据库接入层那段之后）加：

```markdown
### 示范库解析链路（Demucs）

`demo_library.html` 的「上传示范音频 → 解析 → 存入基准库」链路是**真的**在跑算法（`DOC_ISSUES.md` 第 16–20 条）：上传走 `POST /api/demo/library/upload`，任务投进 **`demucs` 专用队列**，worker 里用 Demucs（htdemucs）分离人声、按停顿切成唱段，结果落 `segments`（只有 `seq`/`title`/`duration`，**不写 `lyrics_json`**）、并把真实时长回填到 `audio_files.duration_sec`。前端 `fetchStatus` 每 3 秒轮询 `GET /api/demo/library/<id>/parse/status`。

- 代码在 `app/services/parse_service.py`（任务生命周期 + 切分 + 管线）与 `app/services/vocal_service.py`（Demucs 封装，torch/demucs 全部**函数内惰性 import**，这样 Mac 上装不到 torch 也不影响应用启动）。
- 状态存 redis 的 `parse:demo:<demo_id>`（**键是 demo_id 不是 task_id**，一个 demo 同一时刻只有一个解析任务），TTL 3600 并每次更新续期。TTL 过期后 `parse_service.status` 按「`segments` 有行 → parsed，无行 → unparsed」派生。
- 状态词表是 `parsing`/`parsed`/`error`（按前端，不是 B 组的 `queued`/`done`/`failed`）。
- 详情页的列表（`fetchDemos`）**仍是 `DEMO_DATA` 演示数据**，只有轮询与详情接了真接口。
- `TOP_DB`（静音判定阈值）当前是 **30.0，未经真实素材标定**；调参改 `parse_service` 顶部那一个常量即可（越小切得越碎）。
```

- [ ] **Step 4: 同步 `app/config.py` 里 `demucs_model_dir` 的注释**

Task 1 的探查把取数路径探清了（`get_model` 是**两级**：先 HF Hub、失败回退 torch.hub），但 `app/config.py:35-37` 的注释还停在旧说法「权重从 HuggingFace Hub 拉，所以 vocal_service 会把这个值接到 **HF_HOME** 上」——只讲了第一级、只提了一个环境变量。这个文件不属于任何其它任务的 Files 列表，不在这里改就没人改。

把 `app/config.py` 里 `demucs_model_dir` 上面那段注释的后半段：

```python
    # 本项目用的是 demucs 4.1.0，权重从 HuggingFace Hub 拉，所以 vocal_service
    # 会把这个值接到 HF_HOME 上——注意必须在 import demucs 之前设好，
    # huggingface_hub 在 import 期就求值了。
    demucs_model_dir: Path = BASE_DIR / "models" / "demucs"
```

改为：

```python
    # demucs 4.1.0 的 get_model 是**两级**取数路径（2026-09-22 实测确认）：
    # 先试 HuggingFace Hub（huggingface_hub.hf_hub_download，受 HF_HOME 控制），
    # 失败才回退 legacy 的 torch.hub.load_state_dict_from_url（受 TORCH_HOME 控制）。
    # 所以 vocal_service 把 HF_HOME 与 TORCH_HOME **都**接到这个目录：
    # 联网机器命中的是 HF 那一级、离线机器命中回退那一级，两级缓存都不能散到 ~/.cache。
    # 两级的求值时机不同：huggingface_hub 在 import 期就读 HF_HOME 成模块级常量
    # （必须早于 `import huggingface_hub`）；torch.hub 是首次下载时才读 TORCH_HOME。
    # 都设在 vocal_service._prepare_runtime() 里，早于任何下载。
    demucs_model_dir: Path = BASE_DIR / "models" / "demucs"
```

（`demucs_threads` 那一段不动。）

- [ ] **Step 5: 修正 `app/services/parse_service.py` 里 `_master_duration` 的取数机理注释**

Task 4+5 评审的 M1（已证实）：该函数 docstring 首句写「读文件头，不解码」，对浏览器上传的常见格式不成立。核实依据：`librosa/core/audio.py:795` 是 `try: sf.info(path).duration except sf.SoundFileRuntimeError: → audioread`（audioread 经 ffmpeg **全解码**）；本机 soundfile 0.14.0 支持 MP3/OGG/FLAC/WAV，**不支持 m4a / aac / webm**，而这三者正在 `app/common/storage.py:23` 的 `ALLOWED_EXT` 里（.m4a/.aac 恰是 iOS/Safari 与部分安卓录音的默认产物）。

把该 docstring 的首句：

```python
    """音频文件的真实全长（秒）。读文件头，不解码。
```

改为：

```python
    """音频文件的真实全长（秒）。多数格式只读元数据，不解码。

    走 librosa.get_duration(path=...)：它先试 soundfile 的 sf.info()，对
    wav/mp3/flac/ogg 只读文件头；soundfile 打不开的容器（m4a / aac / webm，
    都在 storage.ALLOWED_EXT 里）会回退到 audioread，那条路径经 ffmpeg 把整个
    文件解一遍（秒级到几十秒）。所以这里是「通常很便宜」而非「一定零成本」。
```

（docstring 其余部分——「读不出来返回 None 而不是 0.0」那两段——不动。）

- [ ] **Step 6: 提交**

```bash
git add CLAUDE.md DOC_ISSUES.md app/config.py app/services/parse_service.py \
        docs/superpowers/plans/2026-09-22-demo-library-parse.md
git commit -m "docs: 同步示范库解析链路的说明并落库实现计划"
```

---

## 计划自检

**Spec 覆盖**

| spec 章节 | 落在哪个任务 |
|---|---|
| 4.1 文件清单 | Task 1–8 的 Files 块逐一对齐 |
| 4.2 数据流 | Task 4（`submit`/`_dispatch`/`_parse`）、Task 6（接口层） |
| 4.3 解析管线（阶段/进度/分段/时长回填/幂等） | Task 3（切分）、Task 4（管线）、Task 5（幂等） |
| 4.4 任务状态（键/字段/TTL/终态/失败） | Task 2（键）、Task 4（TTL 由 repo 续期、终态与失败处理） |
| 4.5 接口清单 4 条 + 派生状态 | Task 6 |
| 5 前端改动（轮询/详情/步骤文案/副标题/时间轴标题） | Task 7 Step 1–7 逐项对应；Step 8–9 为预检新发现，见「刻意偏离」第 5、6 条 |
| 6.1 可达性 / 6.2 CPU-only 轮子 / 6.3 队列 / 6.4 权重 | Task 1（全部） |
| 7.1 CLAUDE.md / 7.2 DOC_ISSUES.md | Task 8 |
| 8.x 验证 | **本轮不做**（用户口径：开发完由用户验证）；冒烟脚本 `scripts/smoke_demo_library.sh` 亦不写 |
| 9.1 内存降级顺序 | **本轮不涉及**（不跑 Demucs，遇不到 OOM）；若用户验证时 OOM，按 spec §9.1 的四步顺序处理 |
| 9.2 遗留（不加列 / 不加鉴权 / 45% 停 / schema 可空） | Task 5（不加列）、Task 6（保留已有 `@teacher_required`）、Task 3+4 注释（45% 取舍）、Task 6 Step 1（schema 可空） |
| §3 两处 CRLF 噪音还原 | Task 8 Step 1 |

**与 spec 的刻意偏离（本轮口径变更）**

1. 不写冒烟脚本（spec §8.1）——用户明确「冒烟脚本不需要」。
2. 不做任何验证（spec §8.2/8.3/8.4）——用户明确「验证也不需要，开发完我验证」。
3. `TOP_DB` **不标定**（spec §4.3 要求「必须在真实素材上跑一遍后定值」）——标定需要真跑 Demucs 看切分效果，属验证环节。改为初值 30.0 + 代码注释与 CLAUDE.md 两处标注「未经标定」，由用户验证时决定是否调。
4. 权重取数路径**不做闸门式探查**（spec §6.4 要求确认后放权重、断网跑一次）——改为 `TORCH_HOME` 与 `HF_HOME` **两个都设**、都指向 `models/demucs`，代码不依赖探查结论；Task 1 Step 4 仍做一次轻量探查，用途仅限于把注释写准。
5. **`doUpload` 解信封（Task 7 Step 8）——计划原稿漏了，属必改项。** 新上传接口回统一信封 `{code,message,data}`，而 `doUpload` 读顶层 `data.demo_id`，拿到 `undefined`，`startPolling(undefined)` 会去请求 `/api/demo/library/undefined/parse/status`，被 `<int:demo_id>` 挡成 404。不改这里，「上传即自动投任务 + 前端轮询」这条用户明确要的链路走不起来。spec §5 没写这一项是因为 spec 假定前端已在读正确字段——实测没有。
6. **静态 HTML 里的 VocalParse / Elo 文案（Task 7 Step 9）——计划原稿只覆盖了 JS 里的两处数组。** spec §5 的第 5 项写的是「两处步骤数组」。但同一批文案在静态 HTML 里另有 5 处（`:1296` 卡片标题、`:1304` 静态占位步骤、`:1308` 静态占位步骤、`:1428` 弹窗副标题、`:1961` 同一句的 JS 赋值），且静态占位步骤条是**六步含 Elo**、与 Step 6 改完的五步数组不一致——页面在任何解析发生之前显示的就是这块。按用户「按建议改」的原话（第 17/19 条：不存在 VocalParse、不写 `elo_difficulty`）一并覆盖。

**类型一致性**：`_split_segments` 产出的 `[{seq,title,duration}]` 被 `replace_segments`（Task 5）、`SegmentOut`（Task 6）、前端 `s.title/s.duration`（Task 7）三处消费，字段名一致；`parse_service.status` 的返回键 `status/progress/stage/message` 与 B3 一致，前端只用其中三个（不碰 `stage`）；`submit` 返回 `str`（task_id），Task 6 直接放进 `{"task_id": ...}`。

**跨任务依赖（必须遵守）**：Task 4 与 Task 5 互相 import，**必须由同一个子代理完成、或至少在两者都写完之前不提交、不 import**。Task 6 依赖 Task 4+5。其余任务之间无前置。
