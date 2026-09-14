# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

这是「戏韵AI」——一套面向戏曲（京剧等）演唱教学的 AI 辅助系统——的**前端静态 UI 原型目录**。系统面向两类用户：教师端（看板/示范库/标注/作业）与学生端（实时跟唱/AI 教练/测试/报告），底层以「技法维度」（音准控制、气息支撑、滑音、拖腔、归韵咬字、节奏感知、颤音等）为核心数据模型。

完整业务文档（PRD、系统设计、接口清单、数据库设计等）在**父目录** `../艺校_docs/`。Flask + librosa 后端**父目录与本目录各有一份 `app-d.py`**，5 个路由基本一致，差异见「运行方式」。本目录**没有 README、package.json、构建脚本、git 仓库**，但**有** Python 依赖清单 `requirements.txt`、建库脚本 `schema.sql`/`seed.sql`，以及数据库接入包 `app/`。

> **文档是需求真源，发现问题不改文档，只登记到根目录 `DOC_ISSUES.md`。** 目前已记录 12 条（接口前缀 `/api` vs 前端 `/api/v1`、前端调了文档里没有的接口、建库脚本的角色权限、seed 写死 id 且非幂等、`graph_nodes.ref_id` 注释与 DDL 不符、时区未约定、密码哈希算法变更、3.1 的 stage 与示例自相矛盾、3.2 结果契约的四处未定义等）。**动手实现接口前先看这份文件的第 1、2 条；实现 `/analyze` 相关接口前另见第 10、12 条。**

## 运行方式

- **纯前端页面无需构建、无需安装依赖。** 绝大多数页面（除下述两个外）是纯静态 HTML，无任何后端请求，直接用浏览器双击打开即可。
- 图表页依赖本地相对路径 `static/echarts.min.js`，file:// 下也能加载。
- **例外 1 — `pitch_comparison.html`**：以**根绝对路径** `/static/wavesurfer.min.js` 引入 WaveSurfer（与其它页的相对路径不一致），file:// 下加载不到；且它调用 Flask 后端（端点 `/api/upload`、`/api/progress`、`/api/analyze`、`/api/audio`，基于 librosa 做真实音准对比与 DTW）。该页 `pitch_comparison.html:423` 定义 `const API = location.protocol + '//' + location.host + "/api"`，**调用是带 `/api` 前缀的，与后端一致**。运行：起任一份 Flask 后端后用 HTTP 访问。父目录 `python3 ../app-d.py` 用 5000 端口（会被 macOS AirPlay 接收器占用），本目录 `python3 app-d.py` 用 8877 端口、无此冲突——建议用后者。
- **动那 4 条演示路由前先看这条**：它们挂在 `app-d.py` 的 `demo_bp` 上，与业务蓝图 `api_bp` 共用 `/api` 前缀，取音频路由是 **`GET /api/audio/demo/<path:filename>`**（两段）。《5-接口清单》B5 的 `GET /api/audio/<int:file_id>` 是单段且只吃数字，两者不重叠——**即便把演示路由回退成早先的单段形态 `/audio/<path:filename>`，B5 也只截数字路径，`/api/audio/xxx.wav` 仍归 `demo_bp`**（实测对照见 `app/api/audio_analyze.py` 末尾注释）。所以 B5 已可正常注册，它在 2026-09-14 实现了。
- **但 `pitch_comparison.html` 的音频加载现在是坏的，且与 B5 无关**：`:423` 的 `API` 已含 `/api`，`:529` 又拼 `${API}${j.url}`，而 `url_for("demo.audio", ...)` 返回的也含 `/api` → 前缀重复，实测 404。该拼法自 `8af3787` 首次提交起就在。修它是一行（`${j.url}`），但那只是让这个演示页复活，不解决它的根本问题：它走 `demo_bp` 落盘、不写 `audio_files` 表，B5 查不到它上传的文件。该页去留见 `DOC_ISSUES.md` 第 11 条。
- **例外 2 — `demo_library.html`**：内含对 `${API_BASE}/api/v1/demos/upload` 的真实上传调用，但 `API_BASE=""` 且当前后端未提供该端点——页面演示不受影响，上传会失败属预期。
- 页内无 `localStorage`、无持久化；刷新即重置。

### Python 后端依赖

依赖清单是 **`requirements.txt`**（64 个包全部 `==` 钉死：13 个直接依赖 + 51 个传递依赖，在 macOS Intel 上实测通过）。

**不要引入 `pyproject.toml`**：部署手册 `../艺校_docs/11-部署与运维手册-V1.0.docx` 2.3 节的流程就是 `pip install -r requirements.txt`，且本项目是应用而非可安装库，加打包元数据只会让手册与代码脱节。

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

- Python 要求 **3.11**；数据库 PostgreSQL；部署目标 Ubuntu 22.04。
- 系统依赖（pip 管不了，需 apt）：`libsndfile1`、`ffmpeg`——soundfile/librosa 解码音频必需。
- **`psycopg2-binary` 不可换成 `psycopg2`**：后者要源码编译，需系统提供 `pg_config`。
- **`numba`/`llvmlite` 版本不可上调**：Intel Mac 上 llvmlite≥0.46 没有 macOS x86_64 wheel，会掉进 LLVM 源码编译。
- **`/api` 前缀只在 `app/api/__init__.py` 的 `url_prefix` 里写一次**（对齐《5-接口清单》的 Base URL）。路由一律写相对路径、挂到那里的 `api_bp` 上，不要在 `@app.route("/api/...")` 里逐个拼前缀——Flask 没有 Spring Boot 的 `context-path`，蓝图的 `url_prefix` 就是它的等价物（作用范围是挂在蓝图上的路由，不是整个 app；所以 Flask 实例上的根路由 `/` 不受影响）。
- **`app.register_blueprint(api_bp)` 必须写在所有 `@api_bp.route` 之后**（现在在 `app-d.py` 末尾）。`Blueprint.route()` 不当场注册，只把动作记进 `deferred_functions`；先 register 后定义会当场抛 `AssertionError: The setup method 'route' can no longer be called on the blueprint`（Flask 3.1.3 实测，不是静默失效）。
- `app-d.py` 是自包含的旧演示后端。它的音准分析部分（`/api/upload`、`/api/audio`、`/api/progress`、`/api/analyze`）**不碰数据库**，这 4 条是挂在 `api_bp` 上的**演示路由**；只有根路由 `/` 会通过 `app/` 包查 `users` 表（这是接入数据库的示例）。将来那 49 个业务接口按领域分文件放进 `app/api/`（如 `auth.py`、`analyze.py`），各自 `from . import api_bp` 后用 `@api_bp.route` 挂上去——不要往 `app-d.py` 里堆。

#### 两份 `app-d.py` 的差异

路由一一对应，仅 3 处不同：

| | `../app-d.py`（只读） | `app-d.py`（本目录） |
|---|---|---|
| 路由前缀 | 无前缀：`/upload`、`/audio/<filename>`、`/progress`、`/analyze` | **统一加 `/api`**：`/api/upload`、`/api/audio/demo/<filename>`、`/api/progress`、`/api/analyze`（2026-09-11 起对齐《5-接口清单》的 Base URL，旧的 4 条无前缀路径已移除，不留别名；取音频那条后来加了 `demo/` 一段，见下条） |
| 监听端口 | 5000，**常被 macOS AirPlay 接收器占用** | 8877 |
| 根路由 `/` | 返回 `index.html` 文件 | 查 `users` 表，按统一格式返回 `{"code":0,"message":"ok","data":[...]}`——**`data` 直接装数据本身，不外包一层**（根路由不在 `/api` 之下：它不是接口，没有任何前端调用它） |

其余（含 RMS / 频谱质心特征提取）完全一致。改后端前先确认改的是哪一份。

### 数据库接入层（`app/` 包）

PostgreSQL 跑在 Docker 容器 `docker_postgres`（`postgres:15.7`，端口 5432），库名、角色、口令均为 `xiyun`，连接信息在 `.env` 的 `DATABASE_URL`。

- **表结构的唯一真源是根目录 `schema.sql`**（誊自《4-数据库设计-V1.1》第 2 节），配 `seed.sql` 灌种子数据。`app/models/` 下的 ORM 模型**只做映射、不负责建表**；改表要先改 `schema.sql` 再同步模型。**不要引入 Alembic。**
- 模型覆盖全部 15 张表，按领域分文件放在 `app/models/`。**新增模型必须同步加进 `app/models/__init__.py`**，否则它不会进 `Base.metadata`。
- `app/config.py` 用 pydantic-settings 读 `.env`（路径基于 `__file__`，与启动时的工作目录无关）；`app/db.py` 提供 `engine`/`SessionLocal`/`Base`。**脚本与 celery 任务用 `with session_scope() as s:`**（进出都管事务，异常自动回滚）；**Flask 请求内用 `init_app(app)` + `get_db()` 配对**（只借出会话、不管提交，靠 `teardown_appcontext` 收尾），目前只有 `app-d.py` 的根路由 `/` 在用；业务接口挂上 `api_bp` 后再逐个接上。两者契约不同，不可互换。
- **连接串必须写 `postgresql+psycopg2://`**：`+psycopg` 是 SQLAlchemy 的 psycopg**3** 方言，而本项目装的是 `psycopg2-binary`，写成 `+psycopg` 会报 `ModuleNotFoundError: No module named 'psycopg'`。
- **`users.password_hash` 只有 `VARCHAR(128)`，而 werkzeug 3.x 的 `generate_password_hash` 默认算法已由 pbkdf2 改为 scrypt（输出 162 字符，会溢出报错）**。生成哈希必须显式指定 `method='pbkdf2:sha256'`（输出 103 字符）——文档 6 要求的也正是 pbkdf2。参见 `seed.sql` 头部注释。
- **容器内 PostgreSQL 的时区是 `Etc/UTC`**，`NOW()` 返回 UTC，比北京时间早整 8 小时。所有 `created_at`/`recorded_at`/`submitted_at` 等 `DEFAULT NOW()` 的列存进去的都是 UTC 时间。前端展示、按日统计、作业截止判断**都要显式换算**（如 `created_at AT TIME ZONE 'Asia/Shanghai'`），不要直接当北京时间用。
- `scripts/check_db.py` 是模型与真库之间的一致性闸门：`python scripts/check_db.py` 逐表比对表集合、列名、类型、可空性、外键与自定义索引（当前 15 表 / 110 列 / 22 外键 / 2 索引），有任何差异就打印明细并以退出码 1 结束，可直接接进 CI。**改完 `schema.sql` 或 `app/models/` 后跑一遍。**
- `app/response.py` 提供统一响应助手 `ok(data)` / `fail(code, message)`，对应文档的 `{"code":0,"message":"ok","data":{...}}`。错误码文档未定义，本项目约定 `code` 沿用 HTTP 语义（400/401/403/404/500）且与 HTTP 状态码一致——详见 `DOC_ISSUES.md` 第 9 条。**目前只有 `app-d.py` 的根路由 `/` 用了它**；`/api/upload`、`/api/progress`、`/api/analyze` 仍返回裸字段，因为 `pitch_comparison.html` 直接消费那些字段（`j.url`、`data.logs`、`data.score`），改了会当场打断音准对比演示——要统一必须先改前端。
- 后续业务接口的约定见《5-接口清单-V1.0》（Base URL `/api`，统一返回 `{"code","message","data"}`，共 49 个接口）与《6-登录与数据隔离方案-V1.0》（Flask 原生 Session、不做 JWT、`login_required`/`teacher_required` 装饰器）——**这两份文档描述的接口与认证尚未实现**。

## 架构：单文件自包含原型

**每个 HTML 文件 = 一个完整页面**，相互独立、自成一体，没有共享的 JS/CSS/组件模块：

- `<head>` 内嵌整套 `<style>`，其中 `:root` 定义完整设计 token（见下）。
- `<body>` 底部单个 `<script>`（个别页为 2 个，含一个 JSON/常量块）内嵌**全部交互逻辑 + 全部 mock 数据**。
- 数据是硬编码的顶部大 JS 常量，无后端数据源。"改数据" = 改这些常量。常见锚点：`dashboard.html` 的 `STUDENTS`、`sing_along.html` 的 `PIECES`、`tracking.html` 的 `STUDENTS/TECHNIQUES/BKT_DATA`、`cdm_report.html` 的 `SUBMISSIONS`、`homework.html` 的 `HOMEWORKS/SUBMISSIONS`、`recommendation.html` 的 `ABILITY_DATA/RECOMMENDATIONS`、`annotation.html` 的 `LYRICS/EXISTING_ANNS`、`AI_teacher.html` 的 `RESPONSES`、`demo_library.html` 的 `DEMO_DATA`、`knowledge_graph.html` 的 `GRAPH_DATA`。
- mock 日期多固定在 2026-07/08；默认演示学生常为「李小燕」（初级班）。

## 设计系统（跨页保持一致的关键）

主题名「宣纸」：米白宣纸底（`--bg-primary:#F5EDE4`）+ 景泰蓝主色（`--primary:#0066B3`）+ 朱砂/赭色点缀，西文衬线标题、圆角卡片、暖色描边。**整套 `:root` CSS 变量按页重复粘贴**，各页变量名一致（`--bg-primary/--bg-secondary/--text-primary/--text-secondary/--primary/--border-*` 等），没有共享主题文件（`common/` 下 8 个 JS 文件目前仍是 0 字节占位；`scripts/` 里放的是运维脚本，不是前端资源）。

因此：**改动设计 token 时必须在多个页面同步**，否则页面间观感漂移；新增页面应从现有页复制这套 `:root` 与侧边栏，保持风格统一，不要另起一套配色。

## 导航约定

每页自带左侧 sidebar 导航（含各功能分组与图标），**逐页硬编码**其它页面的链接，并在当前页标 `active`。导航里链接到 `cat_test.html`（摸底测试）与 `daily_report.html`（学习报告）的页面在本目录尚不存在——是规划中页面，不要误当作损坏。`pitch_comparison.html` 无导航、标题不带「戏韵AI」前缀，是独立对比演示，不参与主流程。

## 交互形态

- 演示多为"模拟/脚本化"动画：`sing_along.html` 会真实调用 `getUserMedia` + `MediaRecorder` 录音（这是真实现实录音 UI），但录音后的音高分析、评分、跟唱气泡等由 `simulateAnalysisAfterRecord` / `recordLoop` 等**模拟**生成，非真实音频算法。
- 图表：需要图表数据的页面用 echarts（本地 `static/echarts.min.js`，`<script src="static/echarts.min.js">`）。
- 页面均为中文 UI，代码内注释用中文。代码标识符保持英文。
