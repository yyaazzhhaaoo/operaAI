# 文档问题记录

记录在实现过程中发现的 `../艺校_docs/` 文档问题（错误、前后不一致、关键信息缺失）。

**约定：文档是需求真源，发现问题一律不改文档，只在此处登记**，待文档方确认后统一修订。
代码遇到这些问题时按文档原样实现，并在注释里指向本文件的对应编号。

记录日期：2026-09-10

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

## 11. 3.1 标题声称「替代原阻塞式接口」，但该阻塞接口仍在前端使用

**涉及**：《5-接口清单-V1.0》3.1

**问题**：3.1 的标题是「异步分析协议（`/analyze`，**替代原阻塞式接口**）」，但文档没有说明被替代的那组接口（`POST /api/upload`、`GET /api/progress`、`GET /api/analyze`、`GET /api/audio/<filename>`）应何时下线、由谁迁移。

实测这组接口**仍在被使用**：`pitch_comparison.html:423` 定义 `const API = location.protocol + '//' + location.host + "/api"`，随后调 `${API}/upload`、`${API}/progress`、`${API}/analyze`。它们目前挂在 `app-d.py` 的 `demo_bp` 上，与业务蓝图 `api_bp` 共用 `/api` 前缀。

**影响**：B1–B5 落地时若直接删掉 `demo_bp`，`pitch_comparison.html` 的音准对比演示会当场失效；但它产出的数据格式（`teacher/student/aligned/score`）与 3.2 的结果契约（`overall/dimensions/timeline/regions/words`）并不一致，无法平滑切换。需要明确：这个演示页是保留并迁移到 B1/B5，还是随 `demo_bp` 一起废弃。

**当前处理**：`demo_bp` 原样保留，未改动。B5 此前**刻意未注册**，因为 `GET /api/audio/<file_id>`（单段）会与演示取音频路由 `GET /api/audio/<path:filename>`（当时也是单段）重叠，Werkzeug 优先匹配前者，演示页按 `/api/audio/xxx.wav` 取音频会拿到占位响应。

**2026-09-14 更新**：B5 已实现（`app/api/audio_analyze.py` 的 `audio_download` + `app/services/audio_service.py` 的 `get_playable`，见 `CLAUDE.md`）。重叠问题随之消解，且消解方式有两层：演示路由已挪到两段的 `/audio/demo/<path:filename>`；同时 B5 用的是 `<int:file_id>` 而非字面的 `<file_id>`，只吃数字，所以即便演示路由被回退成单段形态，`/api/audio/xxx.wav` 仍归 `demo_bp`（实测对照见 `audio_analyze.py` 末尾注释）。

**本节议题仍未了结**：文档始终没有说明 `demo_bp` 这 4 条演示路由与 `pitch_comparison.html` 应何时下线、由谁迁移。该页现在**音频加载是坏的**（`pitch_comparison.html:423` 的 `API` 已含 `/api`，`:529` 又拼 `${API}${j.url}`，而 `url_for("demo.audio", ...)` 返回的也含 `/api`，前缀重复 → 404；该拼法自 `8af3787` 首次提交起就存在，与 B5 无关）。另外它走 `demo_bp` 落盘、不写 `audio_files` 表，B5 查不到它的文件，结果契约也与 3.2 不同，无法平滑切换。

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
- `octave_fixed` 按**字**判断：全局修正之外，若某字的中位偏差仍落在 1200±400 cents 内，再折一次并置真。全局偏移量没有单独字段可放（契约里没有），仅进日志。
- `regions` 有歌词时由逐字结果按「相邻 + 同色 + 间隔 ≤0.3s」合并，`avg_cents` 按时长加权；无歌词时退回 2 秒滑窗，保证任何调用方式都有着色区间。
- `overall` 取五维**等权平均**。

**待文档方确认**：若上述任一项与设计意图不符，改动集中在 `_timeline` / `_words` / `_regions` 三个函数内，接口形状不变。

---

## 待核实

- `CLAUDE.md` 记载《5-接口清单》共 49 个接口，但按 `方法 + 路径` 提取只得 43 条、按资源路径去重得 37 个。差异可能来自提取方式（表格结构、路径参数写法），也可能是文档自身统计有误，**尚未确认，不作为问题登记**。
