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

## 待核实

- `CLAUDE.md` 记载《5-接口清单》共 49 个接口，但按 `方法 + 路径` 提取只得 43 条、按资源路径去重得 37 个。差异可能来自提取方式（表格结构、路径参数写法），也可能是文档自身统计有误，**尚未确认，不作为问题登记**。
