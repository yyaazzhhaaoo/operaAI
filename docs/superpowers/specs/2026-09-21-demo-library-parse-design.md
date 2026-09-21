# 示范库解析链路设计（Demucs 人声分离 + 唱段切分）

日期：2026-09-21 ｜ 状态：已评审待实现 ｜ 关联：`DOC_ISSUES.md` 第 16–20 条；《5-接口清单-V1.0》3.1；`schema.sql` 的 `teacher_demos` / `segments`

## 1. 背景与目标

`demo_library.html` 的「上传示范音频 → 解析 → 存入基准库」链路，前端界面（上传弹窗、六步解析流、处理中弹窗、轮询循环）**早就写好**，但后端一条都没有：解析状态靠在 `DEMO_DATA` 里查表、上传调的是文档里不存在的 `/api/v1/demos/upload`。本次把它做成真的。

链路的关键偏离与既定范围全部记在 `DOC_ISSUES.md` 第 16–20 条，本次**照那些记录实现，不重新论证**：

- 第 16 条：分离引擎用 **Demucs**（文档三处写的是 HPSS），是有意偏离，B 组的 HPSS 流水线本次不动
- 第 17 条：这条链路在文档里属**二期**、且前提「VocalParse 微调」被记为不达标；接口形状由实现侧自拟
- 第 18 条：状态词表**按前端**（`parsing`/`parsed`/`error`）落地，步骤文案去掉 Elo 一步
- 第 19 条：**不实现 Elo**（文档无算法），解析不写 `elo_difficulty`
- 第 20 条：**不写 `lyrics_json`**（无 ASR，音频给不出汉字），解析的持久产物只有分段与时长

本次达成：

1. 上传后自动排队解析，前端轮询到终态，弹窗正常关闭
2. Demucs 分离人声 → 按停顿切分唱段 → 落 `segments` 多行 + 回填 `audio_files.duration_sec`
3. 详情页对真实 demo 显示分段列表；列表与其余演示数据保持 mock 不动

## 2. 范围之外（明确不做）

- **不做逐字戏词 / 逐字时间轴**（第 20 条：无 ASR，唯一可行路径是上传表单加戏词录入，属产品决策）
- **不做 Elo 难度**（第 19 条：文档只有名称、无算法与分值域）
- **不做 `POST .../parse` 重试入口**（前端没有重试 UI，YAGNI）
- **不加教师鉴权、不在前端按角色隐藏上传入口**（本轮决策：权限先不管。`upload` 维持 `@login_required`，前端 `access` 按角色取值的三行保持原样；已在的 `list` 的 `@teacher_required` 也不为了对称而移除）
- **不改 `segments` 表结构**（不加 `start_sec` 列）。分段在库里的位置信息只有 `seq` 与 `duration`，前端只显示「第 N 段 · 时长」
- **不改 B 组任何代码路径**：`analyze_service` / `audio_analyze.py` / `audio_service.get_playable` 一行不动
- **不删 `demo_bp`**（第 11 条：已是死代码，独立清理项）
- **不引入 pytest / jq**：验证沿用 `scripts/` 下的冒烟脚本

## 3. 现状：工作区已有的半成品

工作区存在上一轮留下的未提交改动，本次在其上继续，但要先清掉几处：

| 文件 | 现状 | 本次处理 |
|---|---|---|
| `app/services/vocal_service.py` | Demucs 分离，完整（惰性 import、HF_HOME、线程数、单声道化、重采样到 16k） | **保留不动** |
| `app/repositories/parse_task_repo.py` | redis 任务态读写 | 键由 `task_id` 改为 **`demo_id`**（见 4.4） |
| `app/config.py` | `demucs_model_dir` / `demucs_threads` | 保留不动 |
| `app/repositories/library_repo.py` | 只有 `get_library_list` / `add_library` | 扩：分段读写、详情查询 |
| `app/services/library_service.py` | 只有 `demo_library_add` / `demo_library_list` | 扩：上传后投任务、详情组装 |
| `app/schemas/demo_library.py` | `role: str` / `banshi: str` **非空**，而模型里两列可空 | 改为 `str \| None`，否则库里有一行空值就让列表接口 500 |
| `app/api/demo_library.py` | 有 `try/except + traceback.print_exc()`、`fail(404, ...)`、模块级 `UPLOAD_DIR`（建了个 `app/api/uploads/` 空目录，真实落盘目录其实是 `settings.upload_dir`） | **按项目分层重写** |
| `demo_library.html` | 上传已接真接口；`fetchStatus` / `fetchDemoDetail` 仍是 mock | 见第 5 节 |
| `requirements.txt` | 无 torch/torchaudio/demucs | 见第 6 节 |

另有两处**与本次无关的噪音**，提交前应还原：`app-d.py`（470 行）与 `static/echarts.min.js`（45 行）的 diff **全部是 LF → CRLF 换行符变更**，无任何实质修改。

## 4. 后端设计

### 4.1 分层与文件清单

| 文件 | 动作 | 职责 |
|---|---|---|
| `app/services/parse_service.py` | 新建 | 解析任务生命周期（submit / status / 派生状态）+ 管线编排 + Celery 任务。与 `analyze_service` 对称 |
| `app/services/vocal_service.py` | 不动 | Demucs 分离（`separate_vocal`） |
| `app/services/library_service.py` | 扩 | 上传落库 + 投任务；详情组装 |
| `app/repositories/parse_task_repo.py` | 微调 | redis 任务态（键改 `demo_id`） |
| `app/repositories/library_repo.py` | 扩 | `replace_segments` / `list_segments` / `get_demo` |
| `app/api/demo_library.py` | 重写 | 4 条接口，只做校验→调 service→组响应，不写 try/except |
| `app/schemas/demo_library.py` | 修 | 可空字段 |
| `app/worker.py` | 文档 | 补 `-Q demucs` 的启动命令 |
| `scripts/fetch_demucs_weights.sh` | 新建 | 取 htdemucs 权重到 `models/demucs/`（可跳过，见 6.4） |
| `scripts/smoke_demo_library.sh` | 新建 | 端到端冒烟闸门 |

### 4.2 数据流

```
POST /api/demo/library/upload （登录）
  ├─ audio_service.save_upload(commit=False)    落盘 + audio_files 行
  ├─ library_service.demo_library_add(...)      teacher_demos 行  ← 一次 commit，两行同生共死
  └─ parse_service.submit(db, demo)             redis 建任务(parsing,0) → Celery(demucs 队列)
  ← data: {demo_id, task_id}

celery -A app.worker:celery_app worker -Q demucs --concurrency=1
  └─ parse_service.run_parse(demo_id)
       人声分离 → 唱段切分 → 结果入库 → status=parsed

GET /api/demo/library/<demo_id>/parse/status   （前端每 3 秒轮询）
  ← {status, progress, message, stage}         status ∈ parsing|parsed|error
```

`submit` 与 `run_parse` 之间**只传 `demo_id`**：路径、上传者、原有的 `duration` 都由任务自己查库取。这与 B 组（传磁盘路径 + lyrics）不同——示范库这条链路演示上是从头到尾都要查库的，把路径塞进消息只会多一处状态不一致。

### 4.3 解析管线

**阶段与进度**（区间刻意对齐前端 `renderParseFlow` 的阈值 `progress >= t + 15` 才算完成，这样每一步会依次亮起）：

| 阶段常量 | 值 | 对应前端步骤 | 进度 | 实测耗时 |
|---|---|---|---|---|
| （排队） | — | 音频上传 `t=0` | 0 | 立即 |
| `STAGE_SEPARATE` | `人声分离` | Demucs 分离 `t=20` | 20 → 45 | **8–15 分钟** |
| `STAGE_SEGMENT` | `唱段切分` | 唱段结构解析 `t=50` | 50 → 75 | 秒级 |
| `STAGE_SAVE` | `结果入库` | 结构化输出 `t=80` | 80 → 95 | 毫秒级 |
| — | — | 存入基准库 `t=100` | 100（`status=parsed`） | — |

`stage` 只有日志与排查价值，前端不消费（`renderParseFlow` 只收 status/progress/message），因此取值是自拟的中文，与 B 组的 `STAGES` 风格一致。**这与第 10、18 条记的那类「词表错配」不同**：那两处前端拿 stage/status 做判断，这里前端不碰 `stage`。

**分离阶段进度条会停在 45%**：`demucs.apply_model` 不提供分片回调，要细粒度进度只能自己按 30 秒切片循环调用，代价是段边界丢掉跨片上下文、分离质量下降。取舍是**不切**，改用 message 说清耗时预期：`"正在分离人声，单条约需 8–15 分钟…"`。

**分段算法**：

```
人声轨（16k 单声道，vocal_service 的产物）
  → librosa.effects.split(y, top_db=TOP_DB, frame_length=2048, hop_length=512)   有声区间
  → 相邻间隙 < MIN_GAP_SEC(0.35s) 的段合并
  → 短于 MIN_SEG_SEC(1.0s) 的碎段丢弃
  → 若结果为空：回退成「整条 = 1 段」（保证任何输入都有分段，终态仍是 parsed）
  → seq = 1..N，title = "第 N 段"，duration = 段长，lyrics_json = NULL
```

阈值常量放模块顶部、写明依据。`TOP_DB` 预计取 30–40（人声轨上伴奏残留少，可以比默认 60 激进），**必须在真实素材上跑一遍后定值**，定值依据写进常量的注释。

**时长回填**：`audio_files.duration_sec` 回填**音频文件的真实全长**（`librosa.get_duration`，读文件头，不解码），不是处理范围的长度。处理被 `MAX_AUDIO_SEC=180` 截断时（现有测试素材 182.8s 就超了），分段只覆盖前 3 分钟，此时任务完成消息里注明「音频超过 3 分钟，仅解析了前 3 分钟」。这样列表页显示的时长是如实的，分段不完整这件事也没有被藏起来。

**幂等**：落库走「先按 `demo_id` DELETE、再 INSERT」，同一 demo 重跑不累积脏行。管线整体可重入。

### 4.4 任务状态（redis）

- 键：`parse:demo:<demo_id>`（**不是 task_id**）。理由：一个 demo 同一时刻只有一个解析任务，前端也是按 demo_id 轮询；重跑即覆盖。Celery 的 `task_id` 仍用 `uuid4().hex[:12]`（与 B2 一致）存进 hash，只用于日志追踪。
- 字段：`status` / `progress` / `message` / `stage` / `demo_id` / `task_id`
- TTL 3600s，每次 `update` 续期（分离要 8–15 分钟，不续期会在写终态前过期）
- 终态只写 `parsed` / `error`；`parsed` 时 message 带段数，如 `"解析完成，共 12 段"`
- **失败**：`run_parse` 整体 try/except，`logger.exception` 记堆栈，`update(status="error", message=...)`——与 `analyze_service.run_analysis` 同构。**失败状态写入本身再失败**时只记日志，不让异常逃逸（否则 worker 会把这条消息当失败重投，无限重试）

### 4.5 接口清单（定稿）

| 方法 | 路径 | 鉴权 | data |
|---|---|---|---|
| POST | `/api/demo/library/upload` | `@login_required` | `{demo_id, task_id}` |
| GET | `/api/demo/library/list` | `@login_required` + `@teacher_required` | `[{id,title,role,banshi,duration,elo_difficulty,created_at,status}]` |
| GET | `/api/demo/library/<int:demo_id>` | `@login_required` | `{id,title,role,banshi,duration,created_at,status,segments:[{seq,title,duration}],url}` |
| GET | `/api/demo/library/<int:demo_id>/parse/status` | `@login_required` | `{status,progress,message,stage}` |

`list` 保留工作区里已有的 `@teacher_required`：本轮「权限先不管」的口径是**不新增限制，也不移除已有校验**。它目前只被冒烟脚本调用（前端仍走 `DEMO_DATA`），脚本用教师账号登录即可。（第 17 条记的「接口形状由实现侧自拟」，这 4 条就是自拟的最终形状。）

`status` 的取法分两种，写进 `parse_service` 的 docstring：

- redis 有任务 → 直接用 redis 的
- redis 无（TTL 已过 1 小时）→ 按「`segments` 有行 → `parsed`，无行 → `unparsed`」派生

否则详情页会在上传 1 小时后显示成「没解析过」。`unparsed` 是本设计新增的第四个取值，只可能出现在这一条派生路径上。

`url` 用 `url_for("api.audio_download", file_id=...)` 生成（指向 B5），前端可直接喂给播放器。**不返回 `audio_files.file_path`**（`common/storage.py` 承诺不泄漏服务端存储名，与 B1 一致）。

`<int:demo_id>` 的转换器与 B5 同理：非数字路径在路由层就 404，不进视图。

## 5. 前端改动（`demo_library.html`）

1. **`fetchStatus` 改调真接口**，并修掉「轮询永不终止」：现在 mock 对未知 id 返回 `null`，而 `startPolling` 里 `if (!st) return;` 会让定时器一直转。改为——取不到（404 / 已过期）或连续轮询超过 `POLL_MAX = 600` 次（3 秒 × 600 = 30 分钟，留足 Demucs 的最坏耗时）即按 `error` 收尾、停表、提示「解析超时，请查看服务器日志或重新上传」。
2. **`fetchDemoDetail`**：`DEMO_DATA` 命中走原 mock 分支（4 条演示数据不变）；未命中则调 `GET /api/demo/library/<id>`，把响应映射成 `renderDetail` 认识的对象：`versions: []`、`techniques: []`、`parse_result.timeline: []`（这三个空值走已有分支，对应区块自动隐藏）。
3. **`renderDetail` 两处容错**：
   - Elo：真实数据的 `elo_difficulty` 是库默认 `1000`（第 19 条），**不能渲染成 `1000.00` + 恒判「高难度」**。改为取不到有效值（`null` 或 > 1）时显示「待校准」，难度条不渲染。
   - 新增**分段列表**区块：`第 N 段 · 6.6s`。复用 `version-item` 那套样式，新增的 DOM 容器与少量 CSS 加在页面已有的 `<style>` 里（本页无共享样式文件，跨页漂移的既有口径不变）。
4. **步骤文案**（两处数组 `:1863` 与 `:1920`，各去掉 Elo 一步 + 改一处文案）：
   - `音频上传 → Demucs 分离 → 唱段结构解析 → 结构化输出 → 存入基准库`
   - 原「VocalParse 推理 / VocalParse 智能推理」改为「唱段结构解析」：本项目没有 VocalParse 组件（第 17 条），留着等于宣称一个不存在的能力
5. **页头副标题** `:1286`：`上传示范音频 → 人声分离与唱段切分 → 存入基准库`（原文的「VocalParse 自动解析 · 动态难度校准」两处都无实现）
6. `doUpload` 里 `access` 按角色取值的逻辑**保持原样**（本轮不动权限）

**不改**：`fetchDemos`（列表继续用 `DEMO_DATA`，4 条演示数据保留）、上传入口的角色可见性、`renderDemoList`。

## 6. 依赖与部署

### 6.1 实测结论：本机国内网络下各源的可达性

这条链路把两个新依赖面引了进来，而它们**在官方源上都拿不到**。实测（2026-09-21，本机）：

| 目标 | 结果 |
|---|---|
| `download.pytorch.org`（官方 CPU 轮子索引） | ❌ 超时 |
| `pypi.org`、`github.com`、`huggingface.co`、`hf-mirror.com` | ❌ 超时 |
| 清华 PyPI 镜像 | ✅ 有 `demucs==4.1.0` |
| SJTU `https://mirror.sjtu.edu.cn/pytorch-wheels/cpu/`（PEP 503 索引） | ✅ 有 `torch-2.14.0+cpu`、`torchaudio-2.11.0+cpu`（cp311 / manylinux_2_28_x86_64） |
| ModelScope `pengzhendong/uvr-demucs` | ✅ 有 `v3_v4_repo/955717e8-8726e21a.th`（84.14MB） |

**`955717e8-8726e21a.th` 正是官方 htdemucs 的权重文件**：官方分发地址 `https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/955717e8-8726e21a.th` 的文件名与它**逐字相同**。

**已实测校验通过（2026-09-21）**：从 ModelScope 下到的该文件为 84,141,911 字节，`sha256` 前 8 位是 `8726e21a`，与文件名末段完全一致，文件本身是 `torch.save` 产出的 zip 格式。也就是说这是官方权重的字节级副本，而不是同名替换件——下载耗时约 10 秒。这条 sha256 校验保留为 `scripts/fetch_demucs_weights.sh` 里的闸门。

### 6.2 依赖：CPU-only 轮子

PyPI 上 linux 的 `torch` 默认是 **CUDA 版**，会拖进约 2.5GB 的 `nvidia-*` 依赖；本机 4 核无 GPU，装它纯属浪费磁盘与内存。因此：

- 新增 **`requirements-demucs.txt`**（独立文件）：
  - 顶部 `--index-url https://mirror.sjtu.edu.cn/pytorch-wheels/cpu/`
  - `--extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple`（demucs 及其余依赖从清华取）
  - 三行依赖带 `; sys_platform == "linux"` 标记 → **Mac 上自动跳过**（PyTorch 自 2.2.2 起不再发布 macOS x86_64 轮子，第 16 条已记）
- 主 `requirements.txt` **不加**这三行，改为加一行 `-r requirements-demucs.txt` 并把该文件的平台标记说明写在旁边。

**为什么不把三行直接并进 `requirements.txt`**：`--index-url` 是**全局**指令，写进主文件会把整个项目的包解析都改道到 pytorch 镜像上；而且部署手册 2.3 节的流程是 `pip install -r requirements.txt`，主文件必须保持「一条命令装完其余全部」。代价是部署手册要补一步，这一步第 16 条已预告。

**版本钉法**：以「实测能装上、且 `torch.version.cuda is None`」为准，装完记录最终版本到该文件的注释里。候选 `torch==2.14.0+cpu` / `torchaudio==2.11.0+cpu` / `demucs==4.1.0`；demucs 4.1.0 的元数据只要求 `torch>=2.0.1`、`torchaudio>=2.0.2`，但**torch 与 torchaudio 不保证任意版本组合可搭配**，必须以实测 import 成功为准（`import torch, torchaudio, demucs` 三者同时成功）。若某组合失败则顺延到最近可用组合，并把选定组合写进注释。

**验收**：装完后 `pip list` 中**不含** `nvidia-*`；`torch.version.cuda is None`；磁盘增量 < 1GB。

### 6.3 队列：解析走专用 `demucs` 队列

解析任务路由到 `demucs` 队列（`_dispatch` 里 `apply_async(queue="demucs")`），与 B 组分析的默认队列分开：

- 一条解析占 8–15 分钟，与秒级的 B 组分析同队列会把 `pitch_comparison.html` 拖住
- 第 16 条记的部署形态本就是「新增一个 systemd 服务跑 Demucs 专用 worker」

**代价（必须写进三处文档，否则是坑）**：`celery -A app.worker:celery_app worker` **不带 `-Q demucs` 不会消费这个队列**，解析会永远停在 `parsing`。三处都要写明：

1. `CLAUDE.md` 的运行方式一节
2. `app/worker.py` 的模块 docstring
3. `scripts/smoke_demo_library.sh` 的轮询超时提示

```bash
celery -A app.worker:celery_app worker -Q demucs --concurrency=1 --loglevel=info
```

`--concurrency=1` 而非 B 组的 2：`torch.set_num_threads(4)`（`demucs_threads` 默认 4）已经把 4 个核吃满，再开第二个进程只会互相抢核——`app/config.py` 里 `demucs_threads` 的注释记着这条，两处数值必须一起看。

### 6.4 权重落盘

`settings.demucs_model_dir` 默认 `BASE_DIR/models/demucs`，`vocal_service` 把它接到 `HF_HOME` 上（必须在 `import demucs` 之前设，`huggingface_hub` 在 import 期求值）。`.gitignore` 已有 `models/`（第 16 条：权重约 80MB 且随模型换代而变，不进版本库）。

`scripts/fetch_demucs_weights.sh`：从 ModelScope 取 `955717e8-8726e21a.th` 到该目录，并校验 sha256 前 8 位。**离线部署可跳过此脚本，改由人工拷贝**（与 `.gitignore` 里那句注释一致）。

装完 demucs 后要**先确认 `get_model` 的实际取数路径**（`torch.hub` 的 `hub/checkpoints` 还是 HF Hub 缓存），再把权重放到它认的位置——`vocal_service._get_model()` 调的是 `demucs.pretrained.get_model`，不同 demucs 版本走的路子不同，不能凭印象。放好后断网跑一次，确认没有联网动作。

## 7. 文档改动

### 7.1 `CLAUDE.md`

- 运行方式一节加：解析链路要起 `-Q demucs` 的专用 worker（含 6.3 的坑）
- 依赖一节加：`requirements-demucs.txt` 的存在与 `--index-url` 为何不能并进主文件
- 「架构」一节记新增的 `parse_service` 与 `app/api/demo_library.py` 的 4 条接口

### 7.2 `DOC_ISSUES.md`

第 16–20 条**本就是本次的准备记录**，实现完成后把各条「当前处理」里与实际实现不一致的措辞对齐（例如第 17 条记的自拟形状与最终 4 条路径的差异）。**不新增条目**——除非实现中发现新问题。

## 8. 验证

零新增依赖（不装 pytest、不装 jq），全部走 `.venv/bin/python` 内联脚本 + `curl` + `scripts/` 下的冒烟脚本，风格对齐 `scripts/smoke_analyze.sh`。

### 8.1 `scripts/smoke_demo_library.sh`（先写、红 → 绿）

| 断言 | 期望 |
|---|---|
| 上传（教师账号） | 200，`data.demo_id` 与 `data.task_id` 均非空 |
| 轮询终态 | 在超时预算内到达 `parsed`（超时则打印 `-Q demucs` 提示后退出 1） |
| `progress` 单调不减 | 全程成立 |
| `status` 取值 | 只出现 `parsing` / `parsed`（失败路径另测） |
| 轮询终态时 `message` | 含「共 N 段」 |
| 详情 `segments` | 非空数组，每项有 `seq` / `title` / `duration > 0` |
| `duration_sec` 回填 | 详情/列表返回的 `duration` 与 `librosa.get_duration` 一致（±0.5s） |
| 鉴权 | 未登录访问 4 条接口 → 401 |
| 未知 demo_id | 详情与状态接口 → 404 |

素材：默认沿用 `smoke_analyze.sh` 的约定（`AUDIO_DIR` 默认 `$HOME/Desktop/test_audio`、`01_xipi_1931.wav`），并**额外支持** `AUDIO_DIR=uploads` 之类的覆盖。本机 `$HOME/Desktop/test_audio` 不存在，但 `uploads/` 里有 182.8s 的真实素材可代用。

**为了让闸门能在几分钟内跑完而不是 15 分钟**：脚本默认用 `ffmpeg` 从素材切一段 20–30 秒的临时片段（`mktemp`，退出时清理）作为上传件，`FULL=1` 时才用全长素材。这样日常回归是分钟级，全长那一遍走 8.3 的手工验证。

### 8.2 分段算法的单元级验证

`.venv/bin/python` 内联脚本，喂人造信号（正弦 + 中间插入静音），断言：切分点数量、`MIN_GAP` 合并生效、`MIN_SEG` 过滤生效、全静音输入走「整条 = 1 段」回退。不引测试框架。

### 8.3 端到端手工验证（本机、真实音频）

1. 起 Flask（8877）+ redis + `-Q demucs` worker
2. 浏览器登录教师账号 → `demo_library.html` → 上传一条 **182.8s 全长**素材
3. 弹窗应逐步走过五步、进度条从 20 走到 100、约 8–15 分钟后显示「解析完成」并自动关闭
4. 详情页显示真实分段列表；逐字时间轴区块隐藏；Elo 显示「待校准」
5. 库里核对：`segments` 行数与页面一致、`lyrics_json` 全为 NULL、`audio_files.duration_sec` ≈ 182.8

### 8.4 回归闸门

`scripts/smoke_analyze.sh`（B1–B5）、`scripts/smoke_auth.sh`（A 组）、`scripts/check_db.py`（15 表 / 110 列）三者必须仍然全绿——本次不动这三条链路的代码。

## 9. 风险与遗留

### 9.1 本机内存可能不够（最大风险）

本机 **4 核 / 3.9GB 总内存 / 可用约 1.8GB + 2GB swap**，而第 16 条自记 Demucs 需 **2–4GB**。端到端真跑有被 OOM killer 杀掉的风险。降级顺序（**逐步试，不擅自跳到最后一步**）：

1. `apply_model` 的 `segment` 参数调小（默认 7.8s，内存峰值与片长成正比）
2. `overlap` 由 0.25 调小
3. 换更小的模型（`hdemucs_mmi` 等）
4. 承认本机跑不动 → **停下来报告**，改为在目标部署机验证，或退回「管线用轻量替身验证」那一档

### 9.2 遗留（登记，不修）

- **`segments` 无起止时间**（第 2 节已定）：前端只能显示「第 N 段 · 时长」，做不了「点击定位到该段」。若日后要让 B2 按段比对，需要新决策。
- **上传无角色限制**（本轮决策）：任何登录用户都能建 `teacher_demos` 行。与第 15 条是同类问题，一并等业务规则确认。
- **进度条在分离阶段停在 45%**（4.3 的取舍）。
- **`DemoLibraryOut.role/banshi` 的可空问题**：本次修 schema；`elo_difficulty` 仍按第 19 条不写，保持库默认 1000，前端的「待校准」是绕过而非解决。
