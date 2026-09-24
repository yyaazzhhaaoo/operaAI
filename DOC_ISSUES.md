# 文档问题记录

记录在实现过程中发现的 `../艺校_docs/` 文档问题（错误、前后不一致、关键信息缺失）。

**约定：文档是需求真源，发现问题一律不改文档，只在此处登记**，待文档方确认后统一修订。
代码遇到这些问题时按文档原样实现，并在注释里指向本文件的对应编号。

记录日期：2026-09-10

第 16–20 条记于 2026-09-21，来自「项目引入 Demucs、打通示范库解析链路」的准备工作。

---

## 1. 接口前缀不一致：文档写 `/api`，前端页面写 `/api/v1`

**涉及**：《5-接口清单-V1.0》

**问题**：文档中出现的接口路径**全部**以 `/api/` 开头，全文没有出现过 `/api/v1`。但前端 4 个页面里硬编码的调用路径**全部**带 `/v1`：

| 位置 | 前端写的 | 文档里对应的是 |
|---|---|---|
| `dashboard.html:848` | `/api/v1/students/bkt-state` | `GET /api/students/{id}`（路径名也不同） |
| `demo_library.html:1466` | `/api/v1/demos` | `GET /api/demos` |
| `demo_library.html:2028` | `/api/v1/demos/upload` | **文档中不存在**（见第 2 条） |
| `knowledge_graph.html:692` | `/api/v1/graph/nodes-and-edges` | `GET /api/graph`（路径名也不同） |
| `knowledge_graph.html:766` | `/api/v1/graph/prereq-chain` | **文档中不存在** |
| `tracking.html:978,982` | `/api/v1/students/...` | `GET /api/students/{id}` |

**影响**：后端若按文档实现（`/api/...`），前端这 6 处全部 404；反之则与文档不符。**动手实现接口前必须先定死这个前缀。**

**当前状态**：这些接口尚未实现，前端调用也因 `API_BASE` 未定义而没真正发出（只有 `demo_library.html:1461` 定义了 `const API_BASE = ""`），所以问题尚未暴露。

---

## 2. 前端调用了文档中不存在的接口

**涉及**：《5-接口清单-V1.0》

**问题**：`demo_library.html:2028` 调用 `POST ${API_BASE}/api/v1/demos/upload` 上传示范音频，但文档里**没有这个接口**——只有 `GET /api/demos` 和 `GET /api/demos/{id}`。文档中唯一的上传接口是 `POST /api/audio/upload`。

同理，`knowledge_graph.html:766` 的 `/api/v1/graph/prereq-chain`（前置技法链）在文档中也没有对应条目。

**影响**：示范库的上传功能、知识图谱的前置链查询无后端可对接。

---

## 3. 建库脚本的执行角色未说明（`CREATE DATABASE` 需要 CREATEDB 权限）

**涉及**：《4-数据库设计-V1.1》第 2 节、《11-部署与运维手册-V1.0》2.3 节

**问题**：`schema.sql` 第一行是 `CREATE DATABASE xiyun ENCODING 'UTF8';`，该语句需要 CREATEDB 权限。文档的验收流程写的是 `psql -f schema.sql`，但**没说用哪个角色执行**。实测 `xiyun` 角色权限为 `super=false createdb=false canlogin=true`，用它执行直接报：

```
ERROR:  permission denied to create database
```

**影响**：按文档字面用 `xiyun` 角色执行会失败。

**当前处理**：`schema.sql` 头注释已写明建库这一步需用 `postgres` 超级用户执行，并给出容器内执行的完整命令。

---

## 4. `seed.sql` 跨表外键按 SERIAL 推算写死了 id

**涉及**：《4-数据库设计-V1.1》第 3 节

**问题**：种子数据里跨表引用一律写死 id：

```sql
INSERT INTO students (user_id, level) VALUES (2, '初学'), (3, '初学');
INSERT INTO segments (demo_id, seq, ...) VALUES (1, 1, ...);
INSERT INTO cat_questions (seq, segment_id, ...) VALUES (1, 1, ...);
INSERT INTO graph_edges (source_id, target_id, edge_type) VALUES (1,2,'prereq'), ...;
```

其中的 `2`、`3` 是按 `users` 表的 SERIAL 从 1 开始、且按文档的插入顺序推算出来的。

**影响**：只要序列起点不是 1（曾删过数据、或上一次导入部分失败后重跑），这些行会**静默插到错误的行上**，不报任何错,比报错更难发现。

**当前处理**：`seed.sql` 保持文档原样。全新库上执行结果正确（实测 `students.user_id` 正确指向 `stu001`/`stu002`）。

---

## 5. `seed.sql` 不是幂等的

**涉及**：《4-数据库设计-V1.1》第 3 节

**问题**：重复执行会因 `users.username`、`students.user_id` 的 UNIQUE 约束报 duplicate key。文档既没说明这一点，也没给清理语句。

**当前处理**：清空重跑用的 `TRUNCATE ... RESTART IDENTITY CASCADE` 语句已写在 `seed.sql` 头注释里。

---

## 6. `graph_nodes.ref_id` 的注释与 DDL 不一致

**涉及**：《4-数据库设计-V1.1》第 2 节

**问题**：DDL 里该列写作

```sql
ref_id INT,                              -- 技法名存label；唱句指向segments.id
```

注释说它指向 `segments.id`，但这一列**没有建外键约束**（实测真库 `graph_nodes` 上没有任何外键）。而同一份 DDL 里其它同类引用关系都建了外键（如 `graph_edges.source_id REFERENCES graph_nodes(id)`）。

**影响**：是漏建外键，还是有意不加？该列按 `node_type` 分别指向不同目标（技法节点该列为空、唱句节点指向 segments），确实无法建单一外键——但这个理由文档没写。删分段时不会有级联或约束保护。

**当前处理**：ORM 模型按「无外键」如实映射，并在 `app/models/graph.py` 里注明原因。

---

## 7. 未约定时区

**涉及**：《4-数据库设计-V1.1》第 2 节

**问题**：全部时间列都是 `TIMESTAMP DEFAULT NOW()`，文档未说明时区。而实测部署用的 `postgres:15.7` Docker 容器时区是 `Etc/UTC`，`NOW()` 返回 UTC 时间，比北京时间**早整 8 小时**（实测：容器返回 `07:29` 时，宿主机为 `15:29`）。

**影响**：前端展示、按日统计、「今日练习记录」、「作业是否截止」等判断都会偏 8 小时——晚上 8 点后的操作会被算成第二天。

**当前处理**：已在 `CLAUDE.md` 记录约定——读取时显式 `created_at AT TIME ZONE 'Asia/Shanghai'`，不要直接当北京时间用。是否改容器时区（需重建容器）待定。

---

## 8. 密码哈希：文档要求 pbkdf2，但未提示 werkzeug 3.x 默认算法已变

**涉及**：《6-登录与数据隔离方案-V1.0》

**问题**：文档要求使用 pbkdf2 哈希。但 `werkzeug` 3.x 的 `generate_password_hash` **默认算法已由 pbkdf2 改为 scrypt**，输出 162 字符，直接超出 `users.password_hash` 的 `VARCHAR(128)`，插入时报表错。

**影响**：按文档朴素地「生成哈希 → 写入」会失败，且报错信息（value too long）不容易联想到算法变更。

**当前处理**：`seed.sql` 头注释写明必须显式指定 `method='pbkdf2:sha256'`（输出 103 字符），并给出生成命令。

---

## 9. 统一响应格式只规定了成功形态，未定义错误码

**涉及**：《5-接口清单-V1.0》

**问题**：文档写明「统一返回 `{"code":0, "message":"ok", "data":{...}}`」，但**只给了成功（`code=0`）的形态**，没有错误码表——出错时 `code` 取什么值、`message` 写什么、HTTP 状态码是用 200 还是 4xx/5xx，全都没规定。文档中另一处示例 `{"code":0,"data":{"task_id":"a1b2c3"}}` 连 `message` 都省了，与「统一返回」的说法也不完全一致。

**影响**：49 个接口的错误处理无据可依，各人实现必然不一致，前端也没法统一处理错误分支。

**当前处理**：待定。实现接口前需与文档方确认，或自行约定一套并回写文档。

---

## 10. 3.1 的 stage 示例值不在自己的枚举里（`DTW时间对齐` vs `时间对齐`）

**涉及**：《5-接口清单-V1.0》3.1

**问题**：同一节的枚举行与示例自相矛盾。枚举行写的是：

```
stage ∈ 上传完成|人声分离|音高提取|八度修正|时间对齐|评分计算
```

而紧挨着的示例写的是：

```
{"status":"processing","progress":62,"stage":"DTW时间对齐"}
```

示例里的 `DTW时间对齐` **不在枚举中**，枚举里的 `时间对齐` 也没在示例中出现过。两处必有一处是笔误。

同一个示例还有第二处对不上：`progress=62` 配 `stage=DTW时间对齐`。文档通篇没有规定各阶段的进度区间，唯一能参考的就是这个示例；而项目现有的区间（原 `audio_analyze.py` 里的 `STAGE_RANGE`，实现时沿用）中 `时间对齐` 是 70–85，`62` 落在 `八度修正`（55–70）。**区间与示例至少有一方需要改**，但文档没给依据。

**影响**：前端若照示例写死 `"DTW时间对齐"` 做判断或做文案映射，后端按枚举发出 `"时间对齐"`，两边永远匹配不上——表现为进度条卡住不动但接口一路 200，不报任何错，属于最难查的一类错配。

**当前处理**：代码按**枚举**实现（`app/services/analyze_service.py` 的 `STAGES` / `STAGE_RANGE`），并在注释里指向本条。待文档方确认后统一——若最终以示例为准，改 `STAGES` 里一个字符串即可。

---

## 11. 3.1 标题声称「替代原阻塞式接口」，但该阻塞接口仍在前端使用（2026-09-20 已解决，见文末更新）

**涉及**：《5-接口清单-V1.0》3.1

**问题**：3.1 的标题是「异步分析协议（`/analyze`，**替代原阻塞式接口**）」，但文档没有说明被替代的那组接口（`POST /api/upload`、`GET /api/progress`、`GET /api/analyze`、`GET /api/audio/<filename>`）应何时下线、由谁迁移。

实测这组接口**仍在被使用**：`pitch_comparison.html:423` 定义 `const API = location.protocol + '//' + location.host + "/api"`，随后调 `${API}/upload`、`${API}/progress`、`${API}/analyze`。它们目前挂在 `app-d.py` 的 `demo_bp` 上，与业务蓝图 `api_bp` 共用 `/api` 前缀。

**影响**：B1–B5 落地时若直接删掉 `demo_bp`，`pitch_comparison.html` 的音准对比演示会当场失效；但它产出的数据格式（`teacher/student/aligned/score`）与 3.2 的结果契约（`overall/dimensions/timeline/regions/words`）并不一致，无法平滑切换。需要明确：这个演示页是保留并迁移到 B1/B5，还是随 `demo_bp` 一起废弃。

**当前处理**：`demo_bp` 原样保留，未改动。B5 此前**刻意未注册**，因为 `GET /api/audio/<file_id>`（单段）会与演示取音频路由 `GET /api/audio/<path:filename>`（当时也是单段）重叠，Werkzeug 优先匹配前者，演示页按 `/api/audio/xxx.wav` 取音频会拿到占位响应。

**2026-09-14 更新**：B5 已实现（`app/api/audio_analyze.py` 的 `audio_download` + `app/services/audio_service.py` 的 `get_playable`，见 `CLAUDE.md`）。重叠问题随之消解，且消解方式有两层：演示路由已挪到两段的 `/audio/demo/<path:filename>`；同时 B5 用的是 `<int:file_id>` 而非字面的 `<file_id>`，只吃数字，所以即便演示路由被回退成单段形态，`/api/audio/xxx.wav` 仍归 `demo_bp`（实测对照见 `audio_analyze.py` 末尾注释）。

**本节议题仍未了结**：文档始终没有说明 `demo_bp` 这 4 条演示路由与 `pitch_comparison.html` 应何时下线、由谁迁移。该页现在**音频加载是坏的**（`pitch_comparison.html:423` 的 `API` 已含 `/api`，`:529` 又拼 `${API}${j.url}`，而 `url_for("demo.audio", ...)` 返回的也含 `/api`，前缀重复 → 404；该拼法自 `8af3787` 首次提交起就存在，与 B5 无关）。另外它走 `demo_bp` 落盘、不写 `audio_files` 表，B5 查不到它的文件，结果契约也与 3.2 不同，无法平滑切换。

**2026-09-20 更新**：`pitch_comparison.html` 已迁到 B1/B2/B3/B4/B5，不再调用 `demo_bp` 的任何路由。本节记录的两个悬案随之解决：

- **「音频加载是坏的」** —— 由 B1 返回 B5 的 `url`（`url_for("api.audio_download", ...)` 生成）解决。前端不再拼 `${API}${j.url}` 而是 `${API}${j.data.url}`，且 `url` 本身已含 `/api` 前缀，不再重复。
- **「结果契约无法平滑切换」** —— 由前端新增的 `adaptResult()` 转换层解决。它把 3.2 契约的 `timeline` 三条曲线用 `t_cents = 1200·log2(t_hz/ref_hz)`、`s_cents = t_cents + deviation_cents` 还原成绘图函数认识的 `aligned[]`。契约不同构不再是障碍。

**但 `demo_bp` 那 4 条演示路由保留未删**（这是本次的明确决策，不是遗漏），已无任何调用方，是后续的独立清理项。它们至今没有鉴权——删之前不要往上面加功能。

---

## 12. 3.2 结果契约有四处未定义，实现时必须自行约定

**涉及**：《5-接口清单-V1.0》3.2

**问题**：3.2 只给了一个示例 JSON，没有字段说明。示例本身能看懂的只有形状，以下四处无法从文档推出：

1. **`timeline` 三条曲线的时间基准**。示例给的是 `[0.0, ...]`、`[0.05, ...]`，但没说这个 `0.0` 是原始音频的绝对秒数，还是「已对齐、现在从 0 开始」的相对秒数。两者在功能上差别很大：TL 上要画的是两条轨道的对比曲线，只有共用一个基准才画得对。
2. **`words[].octave_fixed` 的粒度**。字段挂在**字**上，但示例没说这个八度修正是一次全局修正（那就该整首歌同真同假，挂到字上没意义），还是逐字各自判断。同理，全局修正到底有没有发生过，结果里无处可查。
3. **`regions` 与 `words` 的关系**。示例里 `regions[0]` 的 `start/end`（0.5–1.2）与 `words[0]` 的 `start/end` 完全相同，暗示 regions 是按字合并出来的；但模式一（`teacher_audio_id` + `student_audio_id`）拿不到歌词，此时的 regions 从哪来没有说。
4. **`overall` 的算法**。示例 `82.5` 与五个维度的算术平均 `82.6` 差 0.1，既可能是四舍五入，也可能是有未写出的权重。

**影响**：这几处不会报错，只会让前端「画出来不对」——轴对不上、颜色错位、或者明明翻了八度却不提示。属于要靠肉眼比对才能发现的偏差。

**当前处理**：`app/services/analyze_service.py` 的实现按如下约定（均已写在对应函数的 docstring 里）：

- 三条曲线共用**教师轨**的时间栅格，且时间**相对教师开唱点**（静音被裁掉），`duration` 即该栅格末端，保证前端画图不空一截。
- `octave_fixed` 按**字**判断：全局修正之外，若某字的中位偏差仍落在 1200±400 cents 内，再折一次并置真。全局偏移量原先「没有单独字段可放，仅进日志」，2026-09-20 起 `result.octave_shift` 就是它（见第 14 条）。
- `regions` 有歌词时由逐字结果按「相邻 + 同色 + 间隔 ≤0.3s」合并，`avg_cents` 按时长加权；无歌词时退回 2 秒滑窗，保证任何调用方式都有着色区间。
- `overall` 取五维**等权平均**。

**待文档方确认**：若上述任一项与设计意图不符，改动集中在 `_timeline` / `_words` / `_regions` 三个函数内，接口形状不变。

---

## 13. 页面级鉴权文档完全未规定

**涉及**：《6-登录与数据隔离方案-V1.0》第 3、5 节

**问题**：《6》只定义了**接口级**鉴权——`login_required` / `teacher_required` 装饰器作用在 `/api/` 下的接口上。但本项目是前后端分离的静态原型：12 个 HTML 页面由 nginx 直接提供，压根不经 Flask。文档没有说明：

1. 页面本身是否也需要登录才能看
2. 未登录访问页面时的表现（跳转登录页？还是报错？）
3. 登出后的落点
4. 页面是否需要按角色区分（教师页 / 学生页）

**影响**：按文档字面实现，会得到一个「接口全部鉴权、页面全部裸奔」的系统——直接访问 `/dashboard.html` 就能看到完整看板，A 组接口做得再严也形同虚设。

**当前处理**：2026-09-15 实现页面级鉴权，按如下取值（完整设计见 `docs/superpowers/specs/2026-09-15-page-auth-design.md`）：

- 12 个页面全部需要登录，唯一公开页是 `login.html`
- 未登录访问页面 → 302 跳 `/login.html`（不是 401）
- 登出后落到 `/login.html`
- 不按角色区分页面，只校验「是否登录」；数据隔离规则仍落在接口层

**实现方式**：nginx 不再 `try_files` 静态直供 `.html`，改为转发给 Flask 的 `page_bp`（无 `/api` 前缀），受保护页面叠新增的 `page_login_required`。原有 `login_required` 保持抛 401 JSON 不变——它是接口契约，`scripts/smoke_auth.sh` 依赖它。

**代价（已确认接受）**：`file://` 双击打开页面的用法彻底失效；Flask 根路由 `/` 的 users-JSON 示例从 80 端口不可达（改由 nginx `location = /` 302 到 `/index.html`），直连 `:8877` 仍可访问。

---

## 14. 3.2 结果契约与 B1 响应缺前端展示所必需的字段

**涉及**：《5-接口清单-V1.0》3.2、B1

**问题**：3.2 只定义了 `overall / dimensions / timeline / regions / words` 五个字段，但 `pitch_comparison.html` 要把它画成曲线图，还需要四个结果里没有的值：

| 缺失字段 | 用途 | 为什么前端反推不出 |
|---|---|---|
| `octave_shift` | 「学生整体低 N 个八度，已自动对齐」提示；tooltip 里的原始 Hz | `student_pitch` 是**八度修正之后**的值，原始音高已丢失 |
| `teacher_onset` | 同步播放起点的 seek 位置 | `words[].start` 已经减掉了 onset |
| `student_onset` | 同上 | 同上 |
| `ref_hz` | 把 Hz 曲线还原成音分（绘图坐标系） | 前端只能在抽稀后的 1500 点上估中位数，与后端在全帧上算的有微差 |

同一个问题在 B1 上也存在：文档只定义了 `file_id`，但前端需要拿到一个能加载音频的地址。

**影响**：不是报错，是「画出来不对」——曲线基准偏了、八度提示消失、同步播放从文件开头而不是开唱点开始。属于靠肉眼比对才能发现的偏差。

**当前处理**：实现按上表补齐（`app/services/analyze_service.py` 的 `_analyze()`），B1 额外返回 `url`（由 `url_for("api.audio_download", ...)` 生成，指向 B5）。四个值在分析管线里本来就已经算好，只是没往 `result` 里放。**同时刻意不返回 `audio_files.file_path`**——它是服务端存储名，回给客户端违背 `common/storage.py` 模块文档里的承诺。

**关联**：本条给出的 `octave_shift` 同时了结了第 12 条第 2 项「全局偏移量没有单独字段可放」。

---

## 15. 3.1 未规定 B2 是否校验音频归属

**涉及**：《5-接口清单-V1.0》3.1（B2）

**问题**：文档规定了 B2 的入参（`teacher_audio_id` / `student_audio_id` / `segment_id`）与返回，但没有规定**提交分析时是否要校验这两个 `audio_id` 属于调用者**。

**影响**：实现现状是只查存在性（`analyze_service._require_audio()` 调 `audio_repo.get_by_id()`，不比对 `uploader_id`），于是任何登录用户拿任意 `audio_id` 就能提交分析、并读到 B4 返回的完整音高曲线——**包括他人 `access=private` 的学生录音**。《6-登录与数据隔离方案》第 4 节第 2 条定的可听范围（private 仅上传者本人与教师可听）在 B2 这条路径上被绕过了。B5 有 `audio_service.get_playable()` 做权限判定，B2 没有对应的一层。

**当前处理**：未修，仅登记。修它要先定「教师能否分析他人的学生录音」「跨学生比对是否允许」这类业务规则，文档没给依据，不属于前端迁移的范围。

## 16. 文档规定 HPSS 做人声分离，实现改为引入 Demucs（**有意偏离，非文档错误**）

**涉及**：`1-PRD-V1.0.docx`、`3-功能清单V1.0.docx`、`2-系统设计说明-V1.0.docx`

**问题**：这三处写的都是「**HPSS** 人声分离」，全文未出现「Demucs」。而实现（示范库解析链路）改用 Demucs。先说明这条的性质：**这是实现侧的有意偏离，不是文档写错了**——登记的目的是备查，避免日后有人拿文档与代码比对时误判为「实现走样」。

三处原文：

| 文档 | 原文 |
|---|---|
| `1-PRD-V1.0.docx` | `HPSS 人声分离` |
| `3-功能清单V1.0.docx` | `HPSS 人声分离` |
| `2-系统设计说明-V1.0.docx` | `Celery Worker：librosa.pyin 音高提取 → HPSS 人声分离 → DTW 对齐 → 八度修正 → 评分` |

**范围界定（这点值得说明，免得把偏离看得比实际大）**：系统设计那一处是**描述 B 组分析 worker 的流水线**，不是「全系统所有分离都必须用 HPSS」的总体规定；PRD 与功能清单那两处是孤立的技术点条目。所以本次在示范库解析链路引入 Demucs，**并未改动 B 组那条流水线**，偏离面比字面上看要窄。

两者不是同一层次的东西：

| | HPSS | Demucs |
|---|---|---|
| 原理 | 谐波/打击成分分离（`librosa.effects.hpss`），**无监督、无模型** | 基于 PyTorch 的深度神经网络，**需要权重文件** |
| 输出 | 谐波分量，伴奏仍在 | 独立人声轨 |
| 戏曲场景 | 伴奏与唱腔同频段，只能压掉一部分 | 分离质量明显更好 |
| 代价 | 秒级、零额外依赖 | 单条 8–15 分钟（4 核 CPU）、~2–4GB 内存、依赖只能在 Linux 装 |

**影响**：

1. **部署面变了**。`requirements.txt` 新增 torch/torchaudio/demucs 三项，且都带 `; sys_platform == "linux"` 标记——**Mac 上装不了**（PyTorch 自 2.2.2 起不再发布 macOS x86_64 轮子）。部署手册 2.3 节的 `pip install -r requirements.txt` 流程需补上 CPU-only 源与系统依赖说明，并**新增一个 systemd 服务**跑 Demucs 专用 worker。
2. **交付节奏变了**。解析不再是秒级，教师提交后要等 8–15 分钟。这不是可以靠调参抹平的差距，需要产品侧确认这个等待是否可接受。
3. **存在两条人声分离路径**。B 组分析（`analyze_service._load_vocal`）仍是 HPSS，本次**未改动**；只有示范库解析走 Demucs。同一套系统里两种分离方式并存，是本次的既定范围，但长期看应当收敛。

**为什么不把 B 组也换掉**：B2/B3/B4 正在服务 `pitch_comparison.html`，换分离方式会同时改变已上线结果的数值，属于独立议题，不在本次范围。

**当前处理**：实现按 Demucs 落地，`app/services/vocal_service.py` 模块文档里写明这条偏离。权重与依赖已解决：**权重从 ModelScope 副本取**（`scripts/fetch_demucs_weights.sh`，官方地址实测超时；落盘经字节数 + sha256 前缀双闸门校验），**依赖用 CPU-only 轮子**（`requirements-demucs.txt`，torch/torchaudio 都带 `+cpu` 后缀，避免 Linux 上拖进约 2.5GB 的 nvidia-* 依赖）。**待文档方确认**：是把三处「HPSS」正式修订为「Demucs」，还是明确「B 组用 HPSS、示范库用 Demucs」的双轨约定。

---

## 17. 文档没有示范库解析的接口契约，且该功能是**二期**、前提条件明确记录为「不达标」

**涉及**：《1-PRD-V1.0》、《3-功能清单V1.0》、《10-后续工作计划-0909》、《5-接口清单-V1.0》3.1

**问题**：本次要实现的「上传示范音频 → 解析 → 存基准库」链路，在文档里**没有接口契约**，而且文档对它的排期与可行性是有明确结论的——**结论是「现在不做」**。

**（1）没有接口契约。** 3.1 只有 B2 一种形态（`teacher_audio_id` + `student_audio_id` + `segment_id`），语义是「比对教师与学生的同一唱段」。示范库要的是「拿一个示范音频，解析出唱段结构」，**没有学生侧音频、也不做比对**，套不进 B2 的入参。`schema.sql` 里也没有解析任务表，`stage` 枚举（第 10 条）同样只有 B 组那一套。

**（2）文档把这条链路整体排在二期，且给了理由。** 功能清单的二期清单里写的是「数据标注、模型微调、**示范库管理（需模型解析）**、计费收费」，前置条件写作「**VocalParse 微调完成**」。

**（3）PRD 明确说了**一期**不依赖 VocalParse 自动识别**，原文：

> 关于戏词数据来源的说明：本模块的戏词文本及声学数据（音高/时值/NOTE）由老师或助教根据唱段提前录入，**而非依赖 VocalParse 自动识别**。原因：
> - 当前 VocalParse 基于流行音乐训练，对戏曲咬字（尖团、上口）识别准确率不足；
> - 二期 VocalParse 微调完成后，可与示范库管理模块打通，实现自动解析+人工复核的混合模式。

**（4）《10-后续工作计划-0909》里「VocalParse」只出现一次，内容是一句结论：「VocalParse 二期不达标」。**

**影响**：把 (2)(3)(4) 连起来看，情况比「文档没写接口」严重得多：

- 前端 `demo_library.html` 弹窗里演的六步（音频上传 → **Demucs 分离** → **VocalParse 推理** → 结构化输出 → Elo 校准 → 存入基准库），在文档里正是**二期**形态，一期明确排除了自动识别。
- 文档给一期定的做法是「**老师或助教提前录入**戏词文本及声学数据」——即人工录入，不是自动解析。
- 而二期形态的前提「VocalParse 戏曲微调」被后续工作计划记为**不达标**。

也就是说：本次实现的全自动解析链路，是文档**有意推迟、且其前提条件已被判定为不达标**的功能。这不代表技术上做不成，但意味着**产品排期与范围需要重新确认**，不能默认它属于一期范围内的工作。

**当前处理**：接口形状已由实现落地为最终 4 条，挂在 `api_bp` 上（`/api` 前缀只在 `app/api/__init__.py` 的 `url_prefix` 写一次）：`POST /api/demo/library/upload`、`GET /api/demo/library/list`、`GET /api/demo/library/<int:demo_id>`、`GET /api/demo/library/<int:demo_id>/parse/status`，登记在此。**待文档方确认（这条是本组里最需要拍板的）**：

1. 示范库自动解析从二期提前到一期，是否是有意为之；
2. 一期是否仍坚持「老师/助教提前录入戏词」的做法——若是，本次解析链路产出的**只有分段与时长，没有戏词**（`segments.lyrics_json` 留 NULL），这与产品预期是否一致（详见第 20 条）；
3. 「VocalParse 二期不达标」这一结论对本次实现是否构成否决——本项目实际用的是 Demucs 而非 VocalParse，两者的差别见第 16 条。

---

## 18. 前端自拟的解析步骤与状态词表，与文档的枚举互不兼容

**涉及**：《5-接口清单-V1.0》3.1、`demo_library.html`

**问题**：`demo_library.html` 的解析进度弹窗是照着文档的**形状**做的（有 stage、有 progress、有 status），但取值是自己编的，与文档枚举对不上：

| | 文档（3.1） | 前端（`demo_library.html`，**登记这条问题时的快照**） |
|---|---|---|
| `stage` / 步骤 | 上传完成 \| 人声分离 \| 音高提取 \| 八度修正 \| 时间对齐 \| 评分计算 | 音频上传 \| Demucs 分离 \| VocalParse 推理 \| 结构化输出 \| Elo 难度校准 \| 存入基准库 |
| `status` | `queued` \| `processing` \| `done` \| `failed` | `pending` \| `parsing` \| `parsed` \| `error` |

（表里前端两列都是**登记这条问题时的快照**。本次改动后前端是五步：音频上传 / Demucs 分离 / 唱段结构解析 / 结构化输出 / 存入基准库——相比快照去掉了 `VocalParse 推理` 与 `Elo 难度校准`、新增了 `唱段结构解析`。`status` 列不变；「与文档枚举零重合」的结论仍然成立。）

步骤数组写死在两处：`renderParseFlow` 与 `renderProcessingModal` 各自的 `const steps`（在 `demo_library.html` 里 grep `const steps = [` 即达，两处）。终止判定在 `startPolling` 里：`st.status === "parsed" || st.status === "error"`。

**影响**：两边取值集合**没有任何一个词重合**。后端若按文档发 `status="done"`，前端 `:2064` 的终止条件永远不成立 → 弹窗永不关闭、轮询永不停止，且接口一路 200、不报任何错。这与第 10 条是同一类错配（那个是 `DTW时间对齐` vs `时间对齐`），只是这次发生在示范库这条新链路上。

**当前处理**：已按前端词表落地——状态存 redis，词表为 `parsing`/`parsed`/`error`（常量 `STATUS_*` 在 `app/services/parse_service.py` 顶部；TTL 过期后按 `segments` 有无行派生额外取值 `unparsed`）；两处步骤文案里的 Elo 一步已去掉（本次不实现）。**待文档方确认**：3.1 的枚举是否需要扩展出解析链路的一套取值——若要统一到文档词表，改前端上述两处 `const steps` 与 `startPolling` 的终止判定 + 后端状态常量即可，接口形状不变。

---

## 19. `elo_difficulty` 量纲冲突：库里是 1000 分制，前端按 0–1 用

**涉及**：《4-数据库设计-V1.1》第 2 节、`demo_library.html`

**问题**：`schema.sql:61` 是

```sql
elo_difficulty FLOAT DEFAULT 1000,
```

默认值 `1000` 是国际象棋 Elo 的初始分数量纲（分值大致在 800–2000 区间浮动）。但前端把它当成 **0–1 的比率**用：

| 位置 | 用法 |
|---|---|
| `demo_library.html:1719-1721` | `getEloLabel()` 阈值 `>= 0.85` 高难度 / `>= 0.70` 中等 |
| `:1765` | 卡片徽标 `Elo ${d.elo_difficulty.toFixed(2)}` |
| `:1767` | 难度条宽度 `width: ${d.elo_difficulty * 100}%` |
| `:1768` | 班级平均 `(d.elo_difficulty * 0.88).toFixed(2)` |
| `:1804-1805` | 详情页三档配色，阈值同样是 `0.85` / `0.7` |

四个 mock 值也都在 0–1：`:1481` = 0.72、`:1540` = 0.85、`:1589` = 0.78、`:1625` = 0.68。

**影响**：按库里的量纲（1000 起步）算出来的值喂给前端，`* 100` 会变成 `72000%` 的进度条、`.toFixed(2)` 显示 `1000.00`、`getEloLabel` 恒判「高难度」。**不会报错**，只是数字全错。

**关于 Elo 算法本身**：全部 11 份文档中「Elo」只出现 4 次，且**全部只是一句名称，没有任何算法、公式、分值域的定义**：

| 文档 | 原文 |
|---|---|
| `1-PRD-V1.0.docx` | `Elo 评分系统，动态评估唱句难度` |
| `1-PRD-V1.0.docx` | `上传示范音频 → VocalParse 自动解析 → 存入基准库 · Elo 动态难度校准` |
| `3-功能清单V1.0.docx` | `VocalParse 自动解析入库 · Elo 难度校准` |

（改动前前端 `:1925` 那一步的文案「Elo 难度校准」正是照抄这句，本次已随第 18 条一并移除。）这两句同时也是第 17 条「整条链路属二期」的佐证——**Elo 与自动解析是绑在一起排进二期的**。

**当前处理**：本次**不实现 Elo**（无算法可依），所以量纲冲突暂不触发：解析结果不写 `elo_difficulty`，保持库默认值，前端详情页的 Elo 位显示为「待校准」、难度条不渲染（`getEloLabel` 仍服务于列表页的演示数据）。**待文档方确认**：Elo 的分值域究竟是 1000 基准还是 0–1 比率、`getEloLabel` 的阈值按哪套定，以及 Elo 算法本身（第 17 条确认链路提前到一期后，这条会立刻变成阻塞项）。

---

## 20. 解析链路拿不到戏词，前端要的逐字时间轴无数据来源

**涉及**：`1-PRD-V1.0.docx`、《4-数据库设计-V1.1》`segments`、`demo_library.html`

**问题**：示范库详情页要渲染一条**逐字时间轴**，而解析链路**不可能产出其中的「字」**。

前端 mock 的契约（`demo_library.html:1484-1500`）是这样的：

```js
parse_result: {
  word_count: 62,
  timeline: [
    { char: "辕", pitch: 64, note: "NOTE_8", time: 0.0 },
    { char: "门", pitch: 66, note: "NOTE_8", time: 0.4 },
    ...
    { char: "，", pitch: null, note: null, time: 5.4, punct: true },
```

`segments.lyrics_json` 的形状与之对应（`app/models/demo.py`）：

```python
# [{word, midi, start, end, note, tip}]
lyrics_json: Mapped[list | None] = mapped_column(JSONB)
```

`word`→`char`、`midi`→`pitch`、`start`→`time`、`note`→`note` 逐字段对得上。**问题出在 `word`：这一列是文字，而音频里没有文字。**

Demucs 分离 + librosa 提音高能给出的是 `pitch / note / time`（音高、音符、时刻），**给不出「辕」「门」「外」**。要从音频得到汉字需要语音识别，而：

1. 本项目**没有任何 ASR 组件**，VocalParse（唯一的候选）本身就没有代码；
2. 上传接口（`app/api/demo_library.py`）收的字段只有 `audio` / `title` / `role` / `banshi` / `access`，**没有戏词输入框**；
3. PRD 一期的规定正是「戏词文本**由老师或助教提前录入**」（见第 17 条），也就是说这条数据在产品设计上本来就靠人工。

**影响**：

- **本次解析的持久产物只有「分段」与「时长」**，逐字数据落不下来。详情页的逐字时间轴本次只能是空的——不是实现漏了，是无源之水。
- 前端 `word_count: 62` 这类统计值同理无从计算。
- 逐字音高曲线（`pitch`/`note`）其实**算得出来**，但没有地方存：唯一的容身之处 `lyrics_json` 本次不动（见第 17 条的待确认事项），只能留在 redis 任务结果里，1 小时后随 TTL 消失。
- 更要紧的是：**即便补上 ASR，也绕不开「字」的来源问题**——戏曲咬字的识别准确率文档已判为不足（第 17 条引的 PRD 原文）。所以这不是「再加个模型就好」，而是产品上必须先定「戏词从哪来」。

**当前处理**：已落地——解析**不写 `lyrics_json`**（该列恒 NULL，与 `seed.sql` 之外的现状一致），解析只落分段与时长，同时回填 `audio_files.duration_sec`。**待文档方确认**：一期是否需要在上传表单加一个戏词录入（或上传 .lrc/.txt）的入口——这是让逐字时间轴有数据的**唯一**可行路径，且它本来就是 PRD 给一期定的做法。

---

## 21. `student_id` 列指向 `students.id` 而非 `users.id`，两套 id 极易混用

`schema.sql` 里 `bkt_history` / `practice_records` / `submissions` 三张表的 `student_id`，外键都指向 **`students(id)`**（见《4-数据库设计-V1.1》）。DDL 本身没错、外键也建了，问题出在**列名**：`student_id` 与 `user_id` 语义太近，且 `students` 表只是 `users` 的角色扩展表（`students.user_id → users.id`），写代码时极易跳过中间这一跳，直接把 `student_id` 当 `users.id` 用。

**为什么不会报错**：`students.id` 与 `users.id` 是两条独立序列，数值经常同量级、部分重合，所以错查往往"看起来正常"——取到的是另一个学生的名字，或者取不到返回 `NULL`。没有异常、没有日志，只有数据静默错位。

实测映射（当前库，`students` 前两条是示例数据，真实学生从 48 起）：

| `students.id` | `students.user_id` = `users.id` | `users.display_name` |
|---|---|---|
| 48 | 50 | 李小燕 |
| 49 | 51 | 张博文 |
| 50 | 52 | 刘思琪 |
| 51 | 53 | 陈浩然 |
| 52 | 54 | 赵雨桐 |
| 53 | 55 | 周明轩 |
| 54 | 56 | 吴佳怡 |
| 55 | 57 | 孙志远 |

**影响**：`/api/dashboard/alerts` 的三组预警都中招过——`student_id=50`（刘思琪）被当成 `users.id=50` 查出「李小燕」，同一份响应里 `student_id=48`（也是李小燕）与 `student_id=50` **显示成同一个人**。教师端按姓名找学生时会直接找错人。

**当前处理**：已修三处，都改走 `students.user_id → users.id`：

1. `app/services/dashboard_service.py` 的骤降预警（原 `user_repo.get_by_id(db, student_id)`）；
2. `app/repositories/practice_records_repo.py` 的连续未练习（原 `.join(User, User.id == pr.student_id)`）；
3. `app/services/dashboard_service.py` 的前置技法锁定（新增时即按正确路径写）。

姓名统一走 `user_repo.get_student_names(db, ids)` 批量取（`students.id → students.user_id → users.id`），不要在业务代码里手写 join。

**待文档方确认**：这是列命名带来的长期陷阱，**是否应在《4-数据库设计》里显式标注**「本列指向 `students.id`，取姓名需经 `students.user_id`」。不改 DDL，只加一句说明即可；若不标注，后续每接一个用到 `student_id` 的接口都要重踩一次。

---

## 待核实

- `CLAUDE.md` 记载《5-接口清单》共 49 个接口，但按 `方法 + 路径` 提取只得 43 条、按资源路径去重得 37 个。差异可能来自提取方式（表格结构、路径参数写法），也可能是文档自身统计有误，**尚未确认，不作为问题登记**。
