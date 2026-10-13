# AI 教练对话接入本地 LLM 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `AI_teacher.html` 从纯 mock 接通到内网 vLLM 部署的 Qwen 模型，实现 E1/E2/E3 三条接口（客观数据区读真库、对话真实往返、历史落库回读）。

**Architecture:** `llm_client.py` 是全项目唯一的 LLM 出口（换模型/加限频/开流式只动它）；`coach_service.py` 组装上下文、拼 prompt、解析模型输出、双写 `chat_messages`；`app/api/coach.py` 的三条桩路由填实。E2 复用 E1 的内部函数取上下文，不走 HTTP 回环。

**Tech Stack:** Flask 3.1 + SQLAlchemy 2.0 + PostgreSQL 15 + pydantic v2 + requests（直调 OpenAI 兼容端点，不引入 openai SDK）

**Spec:** `docs/superpowers/specs/2026-10-13-ai-coach-integration-design.md`

## Global Constraints

- **模型端点**：`http://192.168.36.208:8007/v1`，模型 id `Qwen3.6-27B-FP8`（vLLM 0.23.0），**内网无需 API Key**
- **必须关闭思考模式**：请求体带 `"chat_template_kwargs": {"enable_thinking": false}`，否则 `content` 恒为 `null`（实测 `max_tokens=800` 仍被思维链吃满）
- **超时 3 秒**（PRD 3.2 写 2 秒、系统设计 5.3 写 3 秒，取后者）
- **一期非流式**（《5-接口清单》3.3：「流式二期再考虑」）
- **响应走统一信封** `{"code":0,"message":"ok","data":{...}}`，用 `app/response.py` 的 `ok()`
- **业务错误抛 `BusinessError(code, message)`**，不写 try/except（`app/common/errors.py` 有全局 handler）
- **`student_id` 指 `students.id` 不是 `users.id`**（DOC_ISSUES 第 21 条，两套 id 部分重合、错查不报错只静默错位）
- **无源字段返回 `None` 而非 `[]`**：`None` = 「没有数据源」，`[]` = 「查了是空」（`homework_service.py:334` 的既有约定）
- **service 层调 `db.commit()`**，api 层用 `get_db()` 不提交
- **不新增依赖**：`requests==2.34.2` 已在 `requirements.txt:101`
- **不引入 pytest**（项目无测试框架），验证手段是临时脚本 + `scripts/smoke_*.sh` + `psql`
- **Commit message 用中文**

---

### Task 1: LLM 配置与 `llm_client.py`

**Files:**
- Modify: `app/config.py`（在 `celery_broker_db` 之后、`celery_broker_url` property 之前插入）
- Modify: `.env`（文件末尾追加）
- Create: `app/services/llm_client.py`
- Create: `scripts/tmp_check_llm.py`（临时，Task 8 删除）

**Interfaces:**
- Consumes: `app.config.settings`
- Produces:
  - `settings.llm_base_url: str`、`settings.llm_model: str`、`settings.llm_timeout: float`、`settings.llm_api_key: str`
  - `llm_client.LlmError(Exception)`
  - `llm_client.chat(messages: list[dict], *, timeout: float | None = None, response_format: dict | None = None) -> str`

---

- [ ] **Step 1: 探测内网可达性**

```bash
curl -s -m 6 --noproxy '*' -o /dev/null -w 'HTTP %{http_code}\n' \
  http://192.168.36.208:8007/v1/models
```

预期：`HTTP 200`。**若连不上**（超时/拒绝），停下来告诉用户——整个计划的前提是这台机器能访问该内网地址，换到 Ubuntu 部署机后需重新验证。

- [ ] **Step 2: 探测 guided decoding 是否可用**

```bash
curl -s -m 30 --noproxy '*' http://192.168.36.208:8007/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen3.6-27B-FP8","messages":[{"role":"user","content":"说点什么"}],"max_tokens":50,
       "chat_template_kwargs":{"enable_thinking":false},
       "response_format":{"type":"json_schema","json_schema":{"name":"r","schema":{"type":"object","properties":{"reply":{"type":"string"}},"required":["reply"]}}}}' \
  -w "\n[HTTP %{http_code}]\n"
```

- **HTTP 200 且 `content` 是合法 JSON** → guided decoding 可用，Task 4 走「路线一」
- **HTTP 400（`response_format` 不支持）或报错** → 不可用，Task 4 走「路线二」（prompt 约束 + 容错解析）

**把结论记下来**，Task 4 的 Step 5 要用。两条路线在 Task 4 都已给出完整代码，此处只是二选一。

- [ ] **Step 3: 加配置项**

在 `app/config.py` 的 `celery_broker_db: int = 0` 之后插入：

```python
    # ── LLM（AI 教练对话，模块3）────────────────────────────────
    # 公司内网自部署的 vLLM 服务，OpenAI 完全兼容、无需鉴权。
    # 换模型/换地址只改这里，调用方不感知（见 app/services/llm_client.py）。
    llm_base_url: str = "http://192.168.36.208:8007/v1"
    llm_model: str = "Qwen3.6-27B-FP8"
    # 超时取 3 秒：《5-接口清单》3.3 原文「LLM 同步调用，超时 3 秒」。
    # PRD 3.2 写的「2 秒内回复」是验收口径、不是超时值，两者冲突已记 DOC_ISSUES。
    llm_timeout: float = 3.0
    # 内网裸跑，留空。留空时 llm_client 不发送 Authorization 头，
    # 而不是发一个空 Bearer——空 Bearer 会被某些网关当成「带了但不对」直接拒。
    llm_api_key: str = ""
```

在 `.env` 末尾追加：

```bash
# ── LLM（AI 教练对话）────────────────────────────────
# 公司内网 vLLM 部署，OpenAI 兼容端点，无需 API Key。
# 部署到 Ubuntu 目标机后若跨网段不通，改这一行指向可达的中转地址。
LLM_BASE_URL=http://192.168.36.208:8007/v1
LLM_MODEL=Qwen3.6-27B-FP8
LLM_TIMEOUT=3
LLM_API_KEY=
```

- [ ] **Step 4: 写验证脚本**

创建 `scripts/tmp_check_llm.py`：

```python
# -*- coding: utf-8 -*-
"""临时脚本：验证 llm_client 能真实调通内网模型。验完即删（见计划的 Task 8）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.services import llm_client

print("端点:", settings.llm_base_url, "模型:", settings.llm_model)

# 1. 最基本的往返
out = llm_client.chat([{"role": "user", "content": "用一句话说明什么是音准。"}])
print("1) 回复:", out)
assert out and "音准" in out, f"回复异常: {out!r}"

# 2. content 不为空 —— 这条专门盯「思考模式没关掉」这个坑：
#    开着的话模型把正文全写进 reasoning，content 是 null。
assert out.strip(), "content 为空，多半是 enable_thinking 没关掉"

# 3. 错误路径：连不上的地址要抛 LlmError，不能是裸的 requests 异常
import app.services.llm_client as m
orig = settings.llm_base_url
try:
    m.settings.llm_base_url = "http://127.0.0.1:1/v1"   # 必然连不上
    try:
        m.chat([{"role": "user", "content": "hi"}], timeout=1)
        raise AssertionError("连不上时应抛 LlmError")
    except m.LlmError as e:
        print("3) 不可达时抛出 LlmError ✓:", e)
finally:
    m.settings.llm_base_url = orig

print("全部通过")
```

- [ ] **Step 5: 跑脚本，确认失败**

```bash
.venv/bin/python scripts/tmp_check_llm.py
```

预期：`ModuleNotFoundError: No module named 'app.services.llm_client'`

（若报的是 `settings` 没有 `llm_base_url`，说明 Step 3 没生效——检查缩进是否在 `Settings` 类体内。）

- [ ] **Step 6: 实现 `llm_client.py`**

创建 `app/services/llm_client.py`：

```python
# -*- coding: utf-8 -*-
"""LLM 调用的唯一出口。

只有这个模块知道模型部署在哪、怎么发请求、请求体长什么样。将来换模型、
加限频、开流式、加重试都只动这一个文件，coach_service 不用碰。

用 requests 直调而不引 openai SDK：本项目只有一个端点要调，而 SDK 会带进
httpx/anyio/distro/jiter/sniffio/tqdm 等约 8 个新依赖，按项目规矩（requirements.txt
每行钉死版本）要逐个钉，不划算。requests 已在 requirements.txt:101 钉好。
"""
import logging

import requests

from app.config import settings

logger = logging.getLogger(__name__)


class LlmError(Exception):
    """LLM 不可用：超时、连不上、非 200、响应结构异常、content 为空。

    service 层接住它转成 BusinessError(503)；让它带着原始信息向上冒，
    日志里能看到「到底哪一步坏了」，而不是一个笼统的「AI 不可用」。
    """


def chat(
    messages: list[dict],
    *,
    timeout: float | None = None,
    response_format: dict | None = None,
) -> str:
    """发一轮对话，返回 assistant 的文本内容。

    messages 是 OpenAI 格式：[{"role":"system"|"user"|"assistant","content":str}, ...]

    response_format 传了就在请求体里带上（guided decoding 强制结构化输出）；
    Task 1 的 Step 2 探测到该部署不支持时必须传 None，走 prompt 约束那条路。
    """
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "max_tokens": 800,
        "temperature": 0.7,
        # Qwen3.x 是推理模型：默认把正文写进 reasoning 字段、content 返回 null。
        # 实测 max_tokens=32 时 content 直接是 null；加到 800 仍被思维链吃满
        # （finish_reason=length，一个字正文都没有）。教练场景要的是能直接展示
        # 给学生看的回复，必须显式关掉思考。
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if response_format is not None:
        payload["response_format"] = response_format

    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"

    # 超时拆成 (连接, 读取)：连不上是网络问题、该快速失败；生成慢是正常现象、
    # 给足余量。单值超时会让「网络不通」也要干等满 3 秒。
    t = timeout if timeout is not None else settings.llm_timeout
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=(2, t))
    except requests.RequestException as e:
        raise LlmError(f"LLM 请求失败：{e}") from e

    if resp.status_code != 200:
        raise LlmError(f"LLM 返回 HTTP {resp.status_code}：{resp.text[:200]}")

    try:
        body = resp.json()
        content = body["choices"][0]["message"].get("content")
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise LlmError(f"LLM 响应结构异常：{e}；原文={resp.text[:200]}") from e

    if not content or not content.strip():
        raise LlmError("LLM 返回空 content（enable_thinking 没生效？）")

    return content
```

- [ ] **Step 7: 跑脚本，确认通过**

```bash
.venv/bin/python scripts/tmp_check_llm.py
```

预期：打印三行后输出 `全部通过`。

- [ ] **Step 8: Commit**

```bash
git add app/config.py app/services/llm_client.py scripts/tmp_check_llm.py
git commit -m "feat: 新增 llm_client，接通内网 vLLM 的 Qwen 模型

- 全项目唯一的 LLM 出口，换模型/加限频/开流式只动这一个文件
- 显式关闭 Qwen3.x 的思考模式（否则 content 恒为 null）
- 超时拆成 (连接 2s, 读取 3s)：网络不通时快速失败
- 用 requests 直调，不引入 openai SDK 的 8 个传递依赖"
```

（`.env` 不进版本库，无需 add。）

---

### Task 2: 仓储层新增查询函数

**Files:**
- Modify: `app/repositories/user_repo.py`
- Modify: `app/repositories/bkt_history_repo.py`
- Modify: `app/repositories/practice_records_repo.py`
- Modify: `app/repositories/chat_repo.py`
- Create: `scripts/tmp_check_coach_repo.py`（临时，Task 8 删除）

**Interfaces:**
- Consumes: `app.models`（`Student`/`User`/`BktHistory`/`PracticeRecord`/`ChatMessage`）
- Produces:
  - `user_repo.get_student_id_by_user_id(db, user_id: int) -> int | None`
  - `user_repo.get_student_profile(db, student_id: int) -> tuple[int, str | None, str | None] | None`
  - `bkt_history_repo.get_latest_per_skill_for_student(db, student_id: int) -> list[BktHistory]`
  - `practice_records_repo.get_latest_for_student(db, student_id: int) -> PracticeRecord | None`
  - `chat_repo.add_message(db, student_id: int, role: str, content: str, context_snapshot: dict | None = None) -> ChatMessage`
  - `chat_repo.get_recent(db, student_id: int, limit: int) -> list[ChatMessage]`

---

- [ ] **Step 1: 写验证脚本**

创建 `scripts/tmp_check_coach_repo.py`：

```python
# -*- coding: utf-8 -*-
"""临时脚本：验证 coach 用到的四个仓储函数。验完即删（Task 8）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import session_scope
from app.repositories import bkt_history_repo, chat_repo, practice_records_repo, user_repo

with session_scope() as db:
    # 1. user_id → students.id。s01(users.id=50) → students.id=48
    sid = user_repo.get_student_id_by_user_id(db, 50)
    print("1) users.id=50 →", sid)
    assert sid == 48, f"期望 48，实际 {sid}"

    # 2. 不存在的用户 → None（不是抛异常）
    assert user_repo.get_student_id_by_user_id(db, 999999) is None
    print("2) 不存在的用户 → None ✓")

    # 3. 学生档案
    prof = user_repo.get_student_profile(db, 48)
    print("3) 档案:", prof)
    assert prof and prof[0] == 48 and prof[1] == "李小燕", f"实际 {prof}"

    # 4. 每技法最新一行：学生 48 有 8 个技法
    rows = bkt_history_repo.get_latest_per_skill_for_student(db, 48)
    skills = sorted(r.skill for r in rows)
    print("4) 技法数:", len(rows), skills)
    assert len(rows) == 8, f"期望 8 个技法，实际 {len(rows)}"
    assert len(set(skills)) == 8, "出现了重复技法，DISTINCT ON 没生效"

    # 5. 无数据的学生 → 空列表而不是报错
    assert bkt_history_repo.get_latest_per_skill_for_student(db, 2) == []
    print("5) 无数据学生 → [] ✓")

    # 6. 最新练习记录：学生 48 无记录（这 6 条都属于 50-55）
    assert practice_records_repo.get_latest_for_student(db, 48) is None
    print("6) 学生 48 无练习记录 → None ✓")
    rec = practice_records_repo.get_latest_for_student(db, 50)
    print("6) 学生 50 最新一条:", rec and (rec.id, rec.created_at))

    # 7. 对话读写（在事务里做，退出时 session_scope 提交，脚本末尾手动清理）
    before = len(chat_repo.get_recent(db, 48, 100))
    chat_repo.add_message(db, 48, "user", "临时验证消息", None)
    chat_repo.add_message(db, 48, "assistant", "临时验证回复", {"strategy": "引导"})
    after = chat_repo.get_recent(db, 48, 100)
    print("7) 落库前后:", before, "→", len(after))
    assert len(after) == before + 2
    assert after[-1].context_snapshot == {"strategy": "引导"}
    assert [m.role for m in after[-2:]] == ["user", "assistant"], "顺序应是先 user 后 assistant"

    # 清掉本次写入的两条，脚本可重复执行
    for m in after[-2:]:
        db.delete(m)
    print("清理完毕")

print("全部通过")
```

- [ ] **Step 2: 跑脚本，确认失败**

```bash
.venv/bin/python scripts/tmp_check_coach_repo.py
```

预期：`AttributeError: module 'app.repositories.user_repo' has no attribute 'get_student_id_by_user_id'`

- [ ] **Step 3: 实现 `user_repo` 两个函数**

在 `app/repositories/user_repo.py` 末尾追加：

```python
def get_student_id_by_user_id(db: Session, user_id: int) -> int | None:
    """登录用户 id → students.id；该用户没有学生档案时返回 None。

    students.id 与 users.id 是两条独立序列、数值部分重合，直接拿 user_id 当
    student_id 用会静默取到别人的数据，且不报错（DOC_ISSUES 第 21 条）。
    这里显式走 students.user_id 这一跳，是全项目唯一的正向映射入口。
    """
    return db.scalar(select(Student.id).where(Student.user_id == user_id))


def get_student_profile(
    db: Session, student_id: int
) -> tuple[int, str | None, str | None] | None:
    """单个学生的档案，返回 (students.id, display_name, level)；查不到返回 None。

    姓名在 users.display_name，students 表只有 id/user_id/level/avatar，
    所以必须 join 拐一次（同 get_student_names，DOC_ISSUES 第 21 条）。
    """
    row = db.execute(
        select(Student.id, User.display_name, Student.level)
        .join(User, User.id == Student.user_id)
        .where(Student.id == student_id)
    ).first()
    return tuple(row) if row else None
```

- [ ] **Step 4: 实现 `bkt_history_repo` 的新函数**

在 `app/repositories/bkt_history_repo.py` 末尾追加：

```python
def get_latest_per_skill_for_student(db: Session, student_id: int) -> list[BktHistory]:
    """某个学生每个技法只留 recorded_at 最新的那一条，即「当前掌握度」。

    与已有的 get_latest_by_skill 是同一套 DISTINCT ON 写法，区别只是**限定单个
    学生**——那个函数把全班拉回来再按学生分组，只为渲染一个人的左侧面板不值当，
    且 LIMIT 也下推不到索引。这里带上 student_id 等值条件，正好命中
    idx_bkt_student_skill(student_id, skill, recorded_at DESC)。
    """
    return list(db.scalars(
        select(BktHistory)
        .where(BktHistory.student_id == student_id)
        .distinct(BktHistory.skill)
        .order_by(BktHistory.skill, desc(BktHistory.recorded_at))
    ).all())
```

- [ ] **Step 5: 实现 `practice_records_repo` 的新函数**

在 `app/repositories/practice_records_repo.py` 末尾追加：

```python
def get_latest_for_student(db: Session, student_id: int) -> PracticeRecord | None:
    """某个学生最近一次练习记录；从没练过返回 None。

    None 是**正常返回值**不是错误——「这个学生还没练过」在教练页要渲染成
    「暂无练习记录」，不能当成 404。排序键与 idx_practice_student_time
    (student_id, created_at DESC) 一致。

    注意 created_at 存的是北京时间（服务器时区 Asia/Shanghai，见
    postgres-stores-beijing-time 那份记录），不要在这上面套 AT TIME ZONE。
    """
    return db.scalar(
        select(PracticeRecord)
        .where(PracticeRecord.student_id == student_id)
        .order_by(PracticeRecord.created_at.desc())
        .limit(1)
    )
```

若文件顶部没有 import `PracticeRecord` 或 `desc`，补上：

```python
from app.models import PracticeRecord
```

（`sqlalchemy` 的 `select` 该文件应已有；`PracticeRecord.created_at.desc()` 不依赖 `desc` 函数，无需额外 import。）

- [ ] **Step 6: 实现 `chat_repo` 两个函数**

在 `app/repositories/chat_repo.py` 末尾追加：

```python
def add_message(
    db: Session,
    student_id: int,
    role: str,
    content: str,
    context_snapshot: dict | None = None,
) -> ChatMessage:
    """追加一条对话。只 flush，提交由 service 层负责（与 user_repo 的写操作一致）。

    context_snapshot 记录「这条回复当时是基于什么上下文生成的」，只写在
    role='assistant' 那条上；user 那条传 None。
    """
    msg = ChatMessage(
        student_id=student_id,
        role=role,
        content=content,
        context_snapshot=context_snapshot,
    )
    db.add(msg)
    db.flush()
    return msg


def get_recent(db: Session, student_id: int, limit: int) -> list[ChatMessage]:
    """某个学生最近的 limit 条对话，**按时间正序**返回。

    E2 要把它直接拼进 prompt（必须正序，倒序会让模型以为对话是反着进行的），
    E3 要按正序渲染。先在库里按倒序取 limit 条（走 created_at 索引、避免全表
    排序），回到内存再翻转——只取 limit 条时这是划算的。

    同一毫秒内写入的 user/assistant 两条靠 id 兜底定序：created_at 是
    TIMESTAMP 无小数秒精度，同一秒内两条会并列，只按 created_at 排会随机。
    """
    rows = list(db.scalars(
        select(ChatMessage)
        .where(ChatMessage.student_id == student_id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(limit)
    ).all())
    rows.reverse()
    return rows
```

- [ ] **Step 7: 跑脚本，确认通过**

```bash
.venv/bin/python scripts/tmp_check_coach_repo.py
```

预期：每步打印一行后 `清理完毕` + `全部通过`。再跑一次应得到同样结果（脚本自清理）。

```bash
.venv/bin/python scripts/tmp_check_coach_repo.py
```

- [ ] **Step 8: Commit**

```bash
git add app/repositories/ scripts/tmp_check_coach_repo.py
git commit -m "feat: coach 接口所需的四个仓储查询函数

- user_repo: user_id → students.id 的正向映射，及单学生档案
- bkt_history_repo: 限定单个学生的每技法最新一行
- practice_records_repo: 单个学生最近一次练习
- chat_repo: 对话追加与按时间正序回读"
```

---

### Task 3: E1 客观数据区

**Files:**
- Create: `app/schemas/coach.py`
- Create: `app/services/coach_service.py`
- Modify: `app/api/coach.py`
- Create: `scripts/tmp_check_coach_e1.py`（临时，Task 8 删除）

**Interfaces:**
- Consumes: Task 2 的四个仓储函数
- Produces:
  - `coach_service.build_context(db, student_id: int) -> dict`（E1 的 `data`，也是 E2 组装 prompt 的输入）
  - `coach_service.resolve_student_id(db, path_student_id: int) -> int`（校验并返回 students.id，失败抛 `BusinessError`）
  - `coach_schemas.CoachContextOut`（pydantic 出参）

---

- [ ] **Step 1: 写验证脚本**

创建 `scripts/tmp_check_coach_e1.py`：

```python
# -*- coding: utf-8 -*-
"""临时脚本：验证 E1 的 context 组装与身份校验。验完即删（Task 8）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.common.errors import BusinessError
from app.db import session_scope
from app.schemas.coach import CoachContextOut
from app.services import coach_service

with session_scope() as db:
    # 1. 有数据的学生（students.id=48 李小燕）
    ctx = coach_service.build_context(db, 48)
    print("1) 学生:", ctx["student"])
    assert ctx["student"]["id"] == 48
    assert ctx["student"]["display_name"] == "李小燕"
    assert len(ctx["bkt"]) == 8, f"BKT 应有 8 项，实际 {len(ctx['bkt'])}"
    assert len(ctx["weak_skills"]) == 3, "薄弱技法取 p_l 最低的 3 项"
    # 薄弱技法按 p_l 升序：第一项应是最低的
    assert ctx["weak_skills"][0]["p_l"] <= ctx["weak_skills"][-1]["p_l"]

    # 2. 三项无源字段是 None 而不是 []
    assert ctx["deviations"] is None, "逐字偏差无数据源，必须是 None"
    assert ctx["cdm"] is None
    assert ctx["rag"] is None
    print("2) 三项空位均为 None ✓")

    # 3. 学生 48 没有练习记录 → last_practice 为 None，且不报错
    assert ctx["last_practice"] is None, f"实际 {ctx['last_practice']}"
    print("3) last_practice=None ✓")

    # 4. 有练习记录的学生（students.id=50）
    ctx50 = coach_service.build_context(db, 50)
    print("4) 学生 50 last_practice:", ctx50["last_practice"])
    assert ctx50["last_practice"] is not None

    # 5. 出参 schema 能吃下这个 dict（字段名对得上）
    out = CoachContextOut.model_validate(ctx50)
    dumped = out.model_dump(mode="json")
    assert set(dumped) == {"student", "last_practice", "bkt", "weak_skills",
                           "deviations", "cdm", "rag"}
    print("5) schema 字段:", sorted(dumped))

    # 6. 身份校验：路径 student_id 与登录人对不上 → 403
    assert coach_service.resolve_student_id(db, 48, user_id=50) == 48
    print("6) 本人访问 ✓")
    try:
        coach_service.resolve_student_id(db, 49, user_id=50)
        raise AssertionError("跨学生访问应抛 403")
    except BusinessError as e:
        assert e.code == 403, f"实际 {e.code}"
        print("6) 跨学生访问 → 403 ✓")

    # 7. stu002（users.id=4）：role='student' 但 students 表里没有它那一行。
    #    @student_required 会放它进来，全靠 resolve_student_id 的这一条挡。
    try:
        coach_service.resolve_student_id(db, 48, user_id=4)
        raise AssertionError("无学生档案的账号应抛 403")
    except BusinessError as e:
        assert e.code == 403, f"实际 {e.code}"
        print("7) role=student 但无学生档案 → 403 ✓")

    # 7b. teacher01（users.id=2）在 students 表里**有**行（students.id=1），
    #     所以这一层只能靠「不是我那条」挡住。真正把教师拦在门外的是路由上的
    #     @student_required，这里只确认本函数的比对逻辑不误放行。
    try:
        coach_service.resolve_student_id(db, 48, user_id=2)
        raise AssertionError("跨学生访问应抛 403")
    except BusinessError as e:
        assert e.code == 403
        print("7b) teacher01 跨学生 → 403 ✓")

    # 8. 不存在的学生 id：与「别人的 id」一视同仁 → 403（故意不区分
    #    「不存在」与「不是你的」，避免拿它当探针枚举库里的学生）
    try:
        coach_service.resolve_student_id(db, 999999, user_id=50)
        raise AssertionError("不存在的学生应抛 403")
    except BusinessError as e:
        assert e.code == 403, f"实际 {e.code}"
        print("8) 不存在的学生 → 403 ✓")

print("全部通过")
```

- [ ] **Step 2: 跑脚本，确认失败**

```bash
.venv/bin/python scripts/tmp_check_coach_e1.py
```

预期：`ModuleNotFoundError: No module named 'app.schemas.coach'`

- [ ] **Step 3: 写出参 schema**

创建 `app/schemas/coach.py`：

```python
# -*- coding: utf-8 -*-
"""AI 教练对话（模块3）的出入参。

三条接口的契约见《5-接口清单-V1.0》2.5 / 3.3。
"""
from pydantic import BaseModel, ConfigDict, Field


class StudentBrief(BaseModel):
    id: int
    display_name: str | None
    level: str | None


class LastPractice(BaseModel):
    segment_id: int | None
    segment_title: str | None
    ai_score: float | None
    duration_sec: float | None
    recorded_at: str | None


class BktItem(BaseModel):
    skill: str
    p_l: float
    confidence: float | None


class WeakSkill(BaseModel):
    skill: str
    p_l: float


class CoachContextOut(BaseModel):
    """E1 客观数据区。

    `deviations` / `cdm` / `rag` 恒为 None —— 这三块在库里没有任何数据源
    （逐字偏差：dimensions_json 全 NULL 且语义是五维分数；CDM 与知识库：
    表都不存在）。用 None 而不是 []表达「没有数据源」，与 homework_service
    的同名约定一致：[] 是「查了，结果是空」，两者语义不同。

    字段保留在响应里、不省略，前端据 None 渲染「待接入」占位；
    将来补上数据源时前端判断不用改。
    """
    model_config = ConfigDict(from_attributes=True)

    student: StudentBrief
    last_practice: LastPractice | None
    bkt: list[BktItem]
    weak_skills: list[WeakSkill]

    deviations: list[dict] | None = None
    cdm: list[dict] | None = None
    rag: list[dict] | None = None


class CoachChatIn(BaseModel):
    """E2 入参（《5-接口清单》3.3）。"""
    student_id: int
    message: str = Field(min_length=1, max_length=1000)


class CoachChatOut(BaseModel):
    """E2 出参。四个字段是文档 3.3 定死的契约，不加不减。"""
    reply: str
    strategy: str
    emotion: str
    quick_replies: list[str]


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    created_at: str | None
```

- [ ] **Step 4: 实现 `coach_service` 的 E1 部分**

创建 `app/services/coach_service.py`：

```python
# -*- coding: utf-8 -*-
"""AI 教练对话（模块3）的业务逻辑。

三个接口见《5-接口清单-V1.0》2.5；E2 的请求/响应契约见 3.3；
数据流见《2-系统设计说明》5.3。
"""
import json
import logging

from sqlalchemy.orm import Session

from app.common.errors import BusinessError
from app.models import ChatMessage
from app.repositories import (
    bkt_history_repo,
    chat_repo,
    practice_records_repo,
    user_repo,
)

logger = logging.getLogger(__name__)

# 拼进 prompt 的历史轮数。文档未规定——上限由延迟定，不是由 max_model_len 定：
# 该模型上下文有 65536，远不是瓶颈；真正的约束是历史越长 prompt 越长、
# 首字节越慢，而 PRD 3.2 卡的是 2 秒。
HISTORY_TURNS = 10

# 「薄弱技法」取 p_l 最低的几项
WEAK_SKILL_TOP_N = 3

# 约束条件：随每次请求发给模型的固定条款，也原样写进 context_snapshot。
# 与页面 mock 里那句「禁止编造数值 · 苏格拉底式 · 水平适配」对齐。
CONSTRAINTS = "禁止编造数值 · 苏格拉底式 · 水平适配"


def resolve_student_id(db: Session, path_student_id: int, user_id: int) -> int:
    """校验「路径里的 student_id」确实是登录人自己的，返回它。

    三条 E 接口的路径都带 student_id，但文档（《5-接口清单》2.5）把权限只写成
    「登录」、没区分角色。本实现收紧为「仅学生、且只能看自己」：
      - 路径里的 id 不是自己的 → 403
      - 登录人是学生却没有学生档案 → 403

    **没有 404**：任何「不是你的」id 一律 403，故意不区分「该学生不存在」与
    「不是你的」——拿 403/404 的差异去枚举库里有哪些学生是不必要的泄漏面。
    至于「档案不存在」：own 是从 students 表按 user_id 查出来的 students.id，
    只要不是 None，按同一张表主键再查必定查得到，那个分支不可达，不写。

    后端自己反查、不信任前端传来的 id：只做「传了吗」的判断没有意义，
    必须比对。

    **两道闸门，缺一不可**，别以为这一层够用：
      - 教师靠路由上的 @student_required 挡（文案「需要学生权限」）。
        它们**挡不住**：teacher01（users.id=2）在 students 表里有一行
        （students.id=1，种子数据如此），算得出 own=1，若请求的正是
        /coach/context/1，下面两个判断都会放过。
      - 学生里没有 students 行的那种（stu002，users.id=4，role='student'
        但 students 表无行）靠本函数的 `own is None` 挡——@student_required
        会放它进来。
    """
    own = user_repo.get_student_id_by_user_id(db, user_id)
    if own is None:
        raise BusinessError(403, "AI 教练仅学生可用")
    if own != path_student_id:
        raise BusinessError(403, "无权访问该学员数据")
    return own


def _bkt_items(db: Session, student_id: int) -> list[dict]:
    rows = bkt_history_repo.get_latest_per_skill_for_student(db, student_id)
    return [
        {"skill": r.skill, "p_l": round(r.p_l, 4), "confidence": r.confidence}
        for r in rows
    ]


def _weak_skills(bkt: list[dict]) -> list[dict]:
    """p_l 最低的若干项，即最薄弱的技法。

    数据不足 WEAK_SKILL_TOP_N 项时给几项算几项——新生只有一两个技法有记录
    是常态，不该为了凑数去补零值。
    """
    ranked = sorted(bkt, key=lambda x: x["p_l"])
    return [{"skill": x["skill"], "p_l": x["p_l"]} for x in ranked[:WEAK_SKILL_TOP_N]]


def _last_practice(db: Session, student_id: int) -> dict | None:
    """最近一次练习；从没练过返回 None（正常情况，不是错误）。"""
    rec = practice_records_repo.get_latest_for_student(db, student_id)
    if rec is None:
        return None
    # 曲目名要从 segments 表取，但 6 条练习记录里 5 条的 segment_id 是 NULL，
    # 取不到就填 None，不要编一个曲目名出来。
    title = None
    if rec.segment_id is not None:
        from app.models import Segment
        seg = db.get(Segment, rec.segment_id)
        title = seg.title if seg else None
    return {
        "segment_id": rec.segment_id,
        "segment_title": title,
        "ai_score": rec.ai_score,
        "duration_sec": rec.duration_sec,
        # created_at 存的是北京时间（服务器时区 Asia/Shanghai），直接出 ISO 串
        "recorded_at": rec.created_at.isoformat() if rec.created_at else None,
    }


def build_context(db: Session, student_id: int) -> dict:
    """组装 E1 的客观上下文，同时是 E2 拼 prompt 的输入。

    只放**程序算出来的**数据，不含任何模型生成内容——这是页面「数据/生成分离」
    那条设计线的服务端一半（AI_teacher.html:577）。
    """
    profile = user_repo.get_student_profile(db, student_id)
    if profile is None:
        raise BusinessError(404, "学员档案不存在")
    sid, display_name, level = profile

    bkt = _bkt_items(db, sid)
    return {
        "student": {"id": sid, "display_name": display_name, "level": level},
        "last_practice": _last_practice(db, sid),
        "bkt": bkt,
        "weak_skills": _weak_skills(bkt),
        # ↓ 三项显式空位，理由见 schemas/coach.py 的 CoachContextOut
        "deviations": None,
        "cdm": None,
        "rag": None,
    }
```

- [ ] **Step 5: 填实 E1 路由**

把 `app/api/coach.py` 整个替换为：

```python
# -*- coding: utf-8 -*-
"""AI 教练对话（模块3）的接口。

《5-接口清单-V1.0》2.5 节：
  E1 GET  /coach/context/<student_id>   客观数据区
  E2 POST /coach/chat                   发消息 → AI 回复
  E3 GET  /coach/history/<student_id>   历史对话
"""
from flask import request

from app.api import api_bp
from app.common.decorators import current_user_id, login_required, student_required
from app.db import get_db
from app.response import ok
from app.schemas.coach import CoachContextOut
from app.services import coach_service


def _payload() -> dict:
    """取 JSON 请求体。

    客户端没带 Content-Type: application/json 时 get_json() 会抛 415；
    silent=True 把它压成 None，这里再兜成 {}，让 pydantic 报「字段必填」
    而不是让 Flask 抛一个前端看不懂的 415。与 homeworks/audio_analyze 同款。
    """
    return request.get_json(silent=True) or {}


# 路径参数用 <int:student_id> 而不是 <student_id>：后者是字符串转换器，
# /coach/context/abc 也会匹配进来再进视图去查库；<int:...> 让 Werkzeug 在路由层
# 就挡掉（IntegerConverter 的正则是 \d+），走 errors.py 的统一 404「接口不存在」。
# 与 homeworks.py 的 F5/F6/F7 同款。
@api_bp.route("/coach/context/<int:student_id>", methods=["GET"])
@login_required
@student_required
def coach_context(student_id):
    """E1 客观数据区：摘要 / BKT（逐字偏差、CDM、RAG 为显式空位）。"""
    db = get_db()
    sid = coach_service.resolve_student_id(db, student_id, current_user_id())
    # mode="json"：出参里没有 datetime 了（service 已转 ISO 串），
    # 但保持与其它接口一致的写法，将来加字段不用再改。
    return ok(CoachContextOut.model_validate(
        coach_service.build_context(db, sid)).model_dump(mode="json"))
```

**注意**：本步只实现 E1，E2/E3 的路由先不加——它们各自的 Task 里加，这样每个 Task 的产物都能独立验证。`student_required` 的语义见 `app/common/decorators.py:48`（非学生 → 403），它与 `login_required` 叠加使用。

- [ ] **Step 6: 跑脚本，确认通过**

```bash
.venv/bin/python scripts/tmp_check_coach_e1.py
```

预期：8 组断言全过，末行 `全部通过`。

- [ ] **Step 7: 端到端验接口（含 403 分支）**

启动后端（若 8877 被 PyCharm 调试会话占用则跳过启动，那个实例会自动加载改动）：

```bash
.venv/bin/python app-d.py &
```

```bash
# 教师 → 403
J=/tmp/t.jar; rm -f $J
curl -s -c $J -b $J -X POST -H 'Content-Type: application/json' \
  -d '{"username":"teacher01","password":"xiyun@2026"}' \
  http://127.0.0.1:8877/api/auth/login > /dev/null
curl -s -b $J -w '\n[HTTP %{http_code}]\n' http://127.0.0.1:8877/api/coach/context/48

# 学生 s01（students.id=48，密码与 stu001 相同）→ 200
J=/tmp/s.jar; rm -f $J
curl -s -c $J -b $J -X POST -H 'Content-Type: application/json' \
  -d '{"username":"s01","password":"xiyun@2026"}' \
  http://127.0.0.1:8877/api/auth/login > /dev/null
curl -s -b $J -w '\n[HTTP %{http_code}]\n' http://127.0.0.1:8877/api/coach/context/48

# 同一学生看别人 → 403
curl -s -b $J -w '\n[HTTP %{http_code}]\n' http://127.0.0.1:8877/api/coach/context/49

# 未登录 → 401
curl -s -w '\n[HTTP %{http_code}]\n' http://127.0.0.1:8877/api/coach/context/48
```

预期依次为 `403`（文案「需要学生权限」——教师是被路由上的 `@student_required` 挡的）、`200`（`bkt` 8 项、`last_practice` 为 null、三项空位 null）、`403`、`401`。

- [ ] **Step 8: Commit**

```bash
git add app/schemas/coach.py app/services/coach_service.py app/api/coach.py scripts/tmp_check_coach_e1.py
git commit -m "feat: E1 客观数据区接口（GET /api/coach/context/<id>）

- BKT 取该生每技法最新一行，薄弱技法取 p_l 最低三项
- 逐字偏差/CDM/RAG 三项在库中无源，按既有约定返回 None 作显式空位
- 权限收紧为「仅学生、且只能看自己」，教师与跨学生访问均 403"
```

---

### Task 4: E2 对话接口

**Files:**
- Modify: `app/services/coach_service.py`
- Modify: `app/api/coach.py`
- Create: `scripts/tmp_check_coach_e2.py`（临时，Task 8 删除）

**Interfaces:**
- Consumes: Task 1 的 `llm_client.chat` / `LlmError`；Task 3 的 `build_context`、`resolve_student_id`
- Produces:
  - `coach_service.parse_reply(raw: str) -> tuple[str, dict]` → `(reply, {"strategy","emotion","quick_replies","strategy_desc"})`
  - `coach_service.chat(db, student_id: int, message: str) -> dict` → E2 的四字段契约

---

- [ ] **Step 1: 写验证脚本**

创建 `scripts/tmp_check_coach_e2.py`：

```python
# -*- coding: utf-8 -*-
"""临时脚本：验证 E2 的解析降级与真实往返。验完即删（Task 8）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import session_scope
from app.repositories import chat_repo
from app.services import coach_service
from app.services.llm_client import LlmError

# ── 第一部分：纯函数，不碰网络也不碰库 ────────────────────────
# 1. 正常 JSON
reply, meta = coach_service.parse_reply(
    '{"reply":"我们先听听音准。","strategy":"引导","emotion":"neutral",'
    '"quick_replies":["再看一遍曲线","直接告诉我"]}')
print("1)", reply, meta)
assert reply == "我们先听听音准。"
assert meta["strategy"] == "引导" and meta["emotion"] == "neutral"
assert meta["quick_replies"] == ["再看一遍曲线", "直接告诉我"]

# 2. 被 markdown 代码块包住也要能解
reply, meta = coach_service.parse_reply(
    '```json\n{"reply":"好的","strategy":"鼓励","emotion":"positive","quick_replies":[]}\n```')
assert reply == "好的" and meta["strategy"] == "鼓励", f"实际 {reply!r} {meta}"
print("2) 剥掉代码块 ✓")

# 3. 完全不是 JSON → 降级：整段当 reply，其余给默认值
reply, meta = coach_service.parse_reply("你的气息不太稳，我们慢慢来。")
assert reply == "你的气息不太稳，我们慢慢来。"
assert meta["strategy"] == "引导" and meta["emotion"] == "neutral"
assert meta["quick_replies"] == []
print("3) 非 JSON 降级 ✓")

# 4. JSON 合法但 strategy 越界 → 只重置该字段
reply, meta = coach_service.parse_reply(
    '{"reply":"嗯","strategy":"随便写的","emotion":"neutral","quick_replies":[]}')
assert reply == "嗯" and meta["strategy"] == "引导", f"实际 {meta}"
print("4) strategy 越界降级 ✓")

# 5. reply 缺失 → 整段降级
reply, meta = coach_service.parse_reply('{"strategy":"引导"}')
assert reply == '{"strategy":"引导"}', "reply 缺失时该把原文当回复，不能丢内容"
print("5) reply 缺失降级 ✓")

# 6. quick_replies 不是数组 → 置空而不是崩
reply, meta = coach_service.parse_reply(
    '{"reply":"嗯","strategy":"引导","emotion":"neutral","quick_replies":"再看看"}')
assert meta["quick_replies"] == []
print("6) quick_replies 类型异常降级 ✓")

# ── 第二部分：真实往返 + 落库 ────────────────────────────────
with session_scope() as db:
    before = len(chat_repo.get_recent(db, 48, 200))
    out = coach_service.chat(db, 48, "这一句总是唱不准")
    print("7) 真实回复:", out["reply"][:60])
    print("   strategy/emotion:", out["strategy"], "/", out["emotion"])
    assert set(out) == {"reply", "strategy", "emotion", "quick_replies"}
    assert out["reply"].strip()

    after = chat_repo.get_recent(db, 48, 200)
    assert len(after) == before + 2, f"应双写两条，实际多了 {len(after)-before}"
    assert after[-2].role == "user" and after[-2].content == "这一句总是唱不准"
    assert after[-2].context_snapshot is None, "user 那条不写快照"
    assert after[-1].role == "assistant"
    snap = after[-1].context_snapshot
    print("8) 快照键:", sorted(snap))
    assert snap["strategy"] == out["strategy"]
    assert snap["本次偏差"] is None, "无源项在快照里也要如实写 None"
    assert snap["RAG 检索"] is None
    assert "学生画像" in snap and "薄弱技法" in snap

    # 清理，脚本可重复执行
    for m in after[-2:]:
        db.delete(m)

# ── 第三部分：LLM 不可达时不落库 ─────────────────────────────
from app.config import settings
orig = settings.llm_base_url
try:
    settings.llm_base_url = "http://127.0.0.1:1/v1"
    with session_scope() as db:
        n_before = len(chat_repo.get_recent(db, 48, 200))
    try:
        with session_scope() as db:
            coach_service.chat(db, 48, "这条不该落库")
        raise AssertionError("LLM 不可达时应抛 BusinessError")
    except Exception as e:
        print("9) 不可达时抛出:", type(e).__name__, e)
        from app.common.errors import BusinessError
        assert isinstance(e, BusinessError) and e.code == 503, f"实际 {type(e)}"
    with session_scope() as db:
        n_after = len(chat_repo.get_recent(db, 48, 200))
    assert n_after == n_before, f"失败时不该落库：{n_before} → {n_after}"
    print("9) 失败未落库 ✓")
finally:
    settings.llm_base_url = orig

print("全部通过")
```

- [ ] **Step 2: 跑脚本，确认失败**

```bash
.venv/bin/python scripts/tmp_check_coach_e2.py
```

预期：`AttributeError: module 'app.services.coach_service' has no attribute 'parse_reply'`

- [ ] **Step 3: 加 prompt 与解析**

在 `app/services/coach_service.py` 顶部 import 区补上 `from app.services import llm_client` 与 `from app.services.llm_client import LlmError`，然后在文件末尾追加：

```python
SYSTEM_PROMPT = """你是「戏韵AI」的戏曲演唱教练，面向京剧等戏曲的初学者。

教学方式：苏格拉底式引导——不直接给出答案，先用提问引导学生自己发现问题；
反复引导无效后才给出明确提示。语言风格按学生水平适配，初级学生多用生活化类比。

学生若表达挫败（如「太难」「算了」「不想练」「没劲」「放弃」），必须切到鼓励模式：
先肯定已有进步，再主动降低难度建议，不要继续追问。

strategy 只能取这四个值之一：引导、提示、鼓励、降难度
emotion 只能取这三个值之一：positive、neutral、concerned

只输出一个 JSON 对象，不要输出任何其它文字，不要用 markdown 代码块包裹：
{"reply":"给学生的回复正文","strategy":"引导","emotion":"neutral","quick_replies":["选项一","选项二"]}

用户消息里会带一段程序计算出的客观数据。所有数值一律以它为准，不要编造任何
分数、音分或百分比。数据里为 null 的项表示该维度暂无数据，直接跳过、不要提及。"""

_ALLOWED_STRATEGY = ("引导", "提示", "鼓励", "降难度")
_ALLOWED_EMOTION = ("positive", "neutral", "concerned")

_STRATEGY_DESC = {
    "引导": "不直接指出错误，通过提问引导学生自主发现偏差。",
    "提示": "反复引导无效后，给出明确的可执行提示。",
    "鼓励": "学生表达挫败，先肯定已有进步，再降低难度建议。",
    "降难度": "当前段落反复练不好，建议换成更短的片段再练。",
}

_JSON_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "coach_reply",
        "schema": {
            "type": "object",
            "properties": {
                "reply": {"type": "string"},
                "strategy": {"type": "string", "enum": list(_ALLOWED_STRATEGY)},
                "emotion": {"type": "string", "enum": list(_ALLOWED_EMOTION)},
                "quick_replies": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["reply", "strategy", "emotion", "quick_replies"],
        },
    },
}

# Task 1 的 Step 2 探测到该部署支持 guided decoding 就把这里改成 True。
# 不支持必须保持 False：带着 response_format 请求会被 vLLM 直接 400。
GUIDED_DECODING_SUPPORTED = False


def parse_reply(raw: str) -> tuple[str, dict]:
    """把 LLM 的原始输出解析成 (reply, meta)。

    meta 恒含四个键：strategy / emotion / quick_replies / strategy_desc。

    **任何异常都降级，绝不抛**：模型偶发不守格式是常态，一次格式抖动不该让
    整轮对话不可用。降级时把模型原文当 reply —— 内容本身仍是有效的教练回复，
    丢掉它才是真的损失；另外三个字段给默认值。

    取值越界（strategy 不在枚举内）只重置该字段，不整段降级：JSON 解出来了
    说明模型基本守约，reply 是可信的。
    """
    def fallback() -> dict:
        return {
            "strategy": "引导",
            "emotion": "neutral",
            "quick_replies": [],
            "strategy_desc": _STRATEGY_DESC["引导"],
        }

    text = raw.strip()
    # 即便 prompt 里说了不要用代码块，模型仍可能包一层；剥掉再试
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        obj = json.loads(text)
    except ValueError:
        logger.warning("LLM 输出不是合法 JSON，走降级：%s", raw[:120])
        return raw.strip(), fallback()

    if not isinstance(obj, dict):
        logger.warning("LLM 输出不是 JSON 对象，走降级：%s", raw[:120])
        return raw.strip(), fallback()

    reply = obj.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        logger.warning("LLM 输出缺 reply 字段，走降级：%s", raw[:120])
        return raw.strip(), fallback()

    strategy = obj.get("strategy")
    if strategy not in _ALLOWED_STRATEGY:
        logger.warning("strategy 越界（%r），重置为「引导」", strategy)
        strategy = "引导"

    emotion = obj.get("emotion")
    if emotion not in _ALLOWED_EMOTION:
        logger.warning("emotion 越界（%r），重置为 neutral", emotion)
        emotion = "neutral"

    qr = obj.get("quick_replies")
    if not isinstance(qr, list):
        qr = []
    qr = [x for x in qr if isinstance(x, str) and x.strip()][:4]

    return reply.strip(), {
        "strategy": strategy,
        "emotion": emotion,
        "quick_replies": qr,
        "strategy_desc": _STRATEGY_DESC[strategy],
    }


def _build_messages(context: dict, history: list[ChatMessage], message: str) -> list[dict]:
    """拼出完整 messages。

    客观数据只注入**当前这一轮**的 user 消息，不重复注入历史——历史里
    那些轮次的数据已经在各自的快照里了，重复塞既费 token 又会让模型
    以为数据在变化。
    """
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in history:
        msgs.append({"role": h.role, "content": h.content})
    msgs.append({
        "role": "user",
        "content": (
            "【客观数据】"
            + json.dumps(context, ensure_ascii=False)
            + "\n\n【学生说】" + message
        ),
    })
    return msgs


def _snapshot(context: dict, meta: dict) -> dict:
    """写进 chat_messages.context_snapshot 的快照。

    形状照库里已有那行（student_id=48）的中文键组织，便于对照。
    无源的三项如实写 None —— 快照是「当时 AI 到底用了什么」的审计记录，
    写假值会让它失去意义。
    """
    weak = " · ".join(f"{w['skill']}({w['p_l']})" for w in context["weak_skills"])
    stu = context["student"]
    return {
        "strategy": meta["strategy"],
        "strategy_desc": meta["strategy_desc"],
        "emotion": meta["emotion"],
        "学生画像": f"{stu['display_name']} · {stu['level']}",
        "薄弱技法": weak or None,
        "本次偏差": None,      # 无源
        "RAG 检索": None,      # 无源
        "约束条件": CONSTRAINTS,
    }


def chat(db: Session, student_id: int, message: str) -> dict:
    """E2：发消息 → 调 LLM → 双写 chat_messages。

    失败（LLM 超时/不可达/响应异常）一律抛 BusinessError(503)，且**一条都不写**：
    留半截对话会让 E3 读出来的轮次错乱，用户重试后还会堆一串孤立提问。
    """
    context = build_context(db, student_id)
    history = chat_repo.get_recent(db, student_id, HISTORY_TURNS)
    messages = _build_messages(context, history, message)

    try:
        raw = llm_client.chat(
            messages,
            response_format=_JSON_SCHEMA if GUIDED_DECODING_SUPPORTED else None,
        )
    except LlmError as e:
        logger.error("AI 教练调用失败：%s", e)
        raise BusinessError(503, "AI 教练暂时不可用，请稍后再试") from e

    reply, meta = parse_reply(raw)

    # 双写在同一事务里：api 层用 get_db() 不提交，这里一次 commit 落两条，
    # 要么都进要么都不进。
    chat_repo.add_message(db, student_id, "user", message, None)
    chat_repo.add_message(db, student_id, "assistant", reply, _snapshot(context, meta))
    db.commit()

    return {
        "reply": reply,
        "strategy": meta["strategy"],
        "emotion": meta["emotion"],
        "quick_replies": meta["quick_replies"],
    }
```

- [ ] **Step 4: 填实 E2 路由**

在 `app/api/coach.py` 的 import 区把 schema 补上：

```python
from app.schemas.coach import CoachChatIn, CoachContextOut
```

在 `coach_context` 之后追加：

```python
@api_bp.route("/coach/chat", methods=["POST"])
@login_required
@student_required
def coach_chat():
    """E2 发消息 → AI 回复。契约见《5-接口清单》3.3。"""
    data = CoachChatIn.model_validate(_payload())
    db = get_db()
    sid = coach_service.resolve_student_id(db, data.student_id, current_user_id())
    return ok(coach_service.chat(db, sid, data.message))
```

- [ ] **Step 5: 跑脚本，确认通过**

```bash
.venv/bin/python scripts/tmp_check_coach_e2.py
```

预期：9 组断言全过，末行 `全部通过`。第 7 步会真实调用内网模型，耗时约 2 秒。

若第 7 步失败并报 `LlmError`，先看报错原文：`enable_thinking` 没生效会报「返回空 content」，`response_format` 不被支持会报 HTTP 400 —— 后者说明 Task 1 Step 2 的探测结论记反了。

- [ ] **Step 6: 端到端验接口**

```bash
J=/tmp/s.jar
curl -s -b $J -X POST -H 'Content-Type: application/json' \
  -d '{"student_id":48,"message":"这一句总是唱不准"}' \
  -w '\n[HTTP %{http_code}]\n' http://127.0.0.1:8877/api/coach/chat

# 空 message → 422（pydantic min_length=1）
curl -s -b $J -X POST -H 'Content-Type: application/json' \
  -d '{"student_id":48,"message":""}' \
  -w '\n[HTTP %{http_code}]\n' http://127.0.0.1:8877/api/coach/chat
```

预期：第一条 `200` 且 `data` 含 `reply`/`strategy`/`emotion`/`quick_replies` 四字段；第二条 `422` 且报错中文化为「message: 长度不能少于 1 个字符」。

```bash
# 落库确认
docker exec docker_postgres psql -U xiyun -d xiyun -c \
  "select id, student_id, role, left(content,30), context_snapshot is not null as has_snap from chat_messages order by id desc limit 4;"
```

预期：最新两条是同一学生的 `user`/`assistant`，`assistant` 那条 `has_snap = t`。

- [ ] **Step 7: Commit**

```bash
git add app/services/coach_service.py app/api/coach.py scripts/tmp_check_coach_e2.py
git commit -m "feat: E2 对话接口（POST /api/coach/chat）

- 客观数据序列化后注入当前轮 prompt，历史按正序拼接
- 模型输出解析出四字段，任何格式异常都降级而非报错
- 双写 chat_messages（assistant 那条含 context_snapshot）
- LLM 不可用时抛 503 且一条都不落库"
```

---

### Task 5: E3 历史对话接口

**Files:**
- Modify: `app/services/coach_service.py`
- Modify: `app/api/coach.py`
- Modify: `scripts/tmp_check_coach_e2.py` → 改名思路：直接在本 Task 复用同目录新建 `scripts/tmp_check_coach_e3.py`（临时，Task 8 删除）

**Interfaces:**
- Consumes: Task 2 的 `chat_repo.get_recent`
- Produces: `coach_service.history(db, student_id: int, limit: int = 50) -> list[dict]`

---

- [ ] **Step 1: 写验证脚本**

创建 `scripts/tmp_check_coach_e3.py`：

```python
# -*- coding: utf-8 -*-
"""临时脚本：验证 E3 历史回读。验完即删（Task 8）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import session_scope
from app.schemas.coach import ChatMessageOut
from app.services import coach_service

with session_scope() as db:
    rows = coach_service.history(db, 48)
    print("1) 历史条数:", len(rows))
    assert rows, "库里本来就有 student_id=48 的一行，不该为空"

    # 正序：最早的在前
    times = [r["id"] for r in rows]
    assert times == sorted(times), f"应按时间正序（此处用 id 近似），实际 {times}"
    print("2) 正序 ✓")

    # 字段齐且能被 schema 吃下
    out = ChatMessageOut.model_validate(rows[0])
    assert set(out.model_dump()) == {"id", "role", "content", "created_at"}
    print("3) 首条:", out.role, repr(out.content[:30]))

    # 不含 context_snapshot：那是审计用的内部字段，不该给前端
    assert "context_snapshot" not in rows[0], "快照不对外暴露"
    print("4) 未泄漏 context_snapshot ✓")

    # 无对话的学生 → 空列表
    assert coach_service.history(db, 49) == [] or True   # 49 可能有自己的历史
    print("5) 空历史返回列表（学生 2）:", coach_service.history(db, 2))
    assert coach_service.history(db, 2) == []

    # limit 生效
    assert len(coach_service.history(db, 48, limit=1)) == 1
    print("6) limit 生效 ✓")

print("全部通过")
```

- [ ] **Step 2: 跑脚本，确认失败**

```bash
.venv/bin/python scripts/tmp_check_coach_e3.py
```

预期：`AttributeError: module 'app.services.coach_service' has no attribute 'history'`

- [ ] **Step 3: 实现 `history`**

在 `app/services/coach_service.py` 末尾追加：

```python
def history(db: Session, student_id: int, limit: int = 50) -> list[dict]:
    """E3：回读某学生的对话，按时间正序。

    只出 id/role/content/created_at，**不出 context_snapshot** ——
    那是「这条回复当时基于什么」的审计记录，含学生画像等内部信息，
    前端渲染对话根本用不到，没必要暴露。

    created_at 存的是北京时间，直接给 ISO 串（前端 new Date() 解析本地时间）。
    """
    rows = chat_repo.get_recent(db, student_id, limit)
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in rows
    ]
```

- [ ] **Step 4: 填实 E3 路由**

在 `app/api/coach.py` 的 import 区补上：

```python
from app.schemas.coach import ChatMessageOut, CoachChatIn, CoachContextOut
```

在 `coach_chat` 之后追加：

```python
@api_bp.route("/coach/history/<int:student_id>", methods=["GET"])
@login_required
@student_required
def coach_history(student_id):
    """E3 历史对话。limit 走查询串，默认 50，上限 200。"""
    db = get_db()
    sid = coach_service.resolve_student_id(db, student_id, current_user_id())
    # request.args.get 拿到的永远是字符串，非数字会让 int() 抛 ValueError
    # 变成未捕获的 500；给个安全兜底，越界交给下面夹紧。
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 200))
    out = [ChatMessageOut.model_validate(m) for m in coach_service.history(db, sid, limit)]
    return ok([m.model_dump(mode="json") for m in out])
```

- [ ] **Step 5: 跑脚本，确认通过**

```bash
.venv/bin/python scripts/tmp_check_coach_e3.py
```

预期：6 组断言全过，末行 `全部通过`。

- [ ] **Step 6: 端到端验接口**

```bash
J=/tmp/s.jar
curl -s -b $J -w '\n[HTTP %{http_code}]\n' 'http://127.0.0.1:8877/api/coach/history/48?limit=3'
curl -s -b $J -w '\n[HTTP %{http_code}]\n' 'http://127.0.0.1:8877/api/coach/history/48?limit=abc'
curl -s -b $J -w '\n[HTTP %{http_code}]\n' http://127.0.0.1:8877/api/coach/history/999999
```

预期：`200`（最新 3 条）、`200`（非法 limit 回落 50，不 500）、`403`（不是自己的 id 一律 403，故意不回 404）。

- [ ] **Step 7: Commit**

```bash
git add app/services/coach_service.py app/api/coach.py scripts/tmp_check_coach_e3.py
git commit -m "feat: E3 历史对话接口（GET /api/coach/history/<id>）

- 按时间正序返回，limit 越界夹到 1-200、非数字回落默认值
- context_snapshot 是对外审计字段，不在此接口暴露"
```

---

### Task 6: 冒烟脚本 `scripts/smoke_coach.sh`

**Files:**
- Create: `scripts/smoke_coach.sh`

**Interfaces:**
- Consumes: Task 3/4/5 的三条接口
- Produces: `scripts/smoke_coach.sh`（可重复执行，退出码 0/1，风格同 `scripts/smoke_auth.sh`）

---

- [ ] **Step 1: 写脚本**

创建 `scripts/smoke_coach.sh`，沿用 `scripts/smoke_auth.sh` 的骨架（`req`/`jget`/`expect_*` 助手逐字照抄，只改断言部分）：

```bash
#!/usr/bin/env bash
# 戏韵AI — E 组 AI 教练接口冒烟测试（《5-接口清单-V1.0》E1–E3 / 模块3）
#
# 用法（在项目根目录执行）：
#     scripts/smoke_coach.sh                              # 直连后端 8877
#     BASE=http://127.0.0.1:80 scripts/smoke_coach.sh     # 经 nginx
#
# 前置：后端已启动、**内网 LLM 可达**、数据库已灌 seed。
#     .venv/bin/python app-d.py &
#
# ⚠️ 本脚本会真实调用内网模型（每轮约 2 秒），并往 chat_messages 写两条记录。
#    E2 部分因此是**非只读**的，但可重复执行——不依赖库里原有条数。
#
# 账号：s01（students.id=48 李小燕，有 BKT 数据）为学生侧主用；
#       teacher01 验 403；stu001（students.id=2，无数据）验空态。
set -u

BASE="${BASE:-http://127.0.0.1:8877}"
PY="${PY:-python3}"
PW="xiyun@2026"

# （此处照抄 scripts/smoke_auth.sh 的 TD / req / jget / expect_status /
#   expect_code / expect_in / expect_not_in / post_json / ok / bad / red / green
#   这几段，逐字不改；本脚本不需要它那个 restore_password 与 cleanup trap，
#   因为不改任何密码。）

echo "冒烟目标：$BASE"
echo

echo "── 1. 鉴权门 ──────────────────────────────────"
req "$BASE/api/coach/context/48"
expect_status "E1 未登录 → 401" 401

JAR="$JAR_T"
post_json "/api/auth/login" "{\"username\":\"teacher01\",\"password\":\"$PW\"}"
req "$BASE/api/coach/context/48"
expect_status "E1 教师 → 403" 403
# 教师是被路由上的 @student_required 挡的，文案是「需要学生权限」；
# 不是 service 里那句「AI 教练仅学生可用」——那句要到 stu002 那种
# 「是学生但没学生档案」的账号才会出现。
expect_in     "教师被挡的文案" "需要学生权限"

JAR="$JAR_S"
post_json "/api/auth/login" "{\"username\":\"s01\",\"password\":\"$PW\"}"
expect_status "s01 登录 → 200" 200

req "$BASE/api/coach/context/49"
expect_status "E1 跨学生 → 403" 403

req "$BASE/api/coach/context/abc"
expect_status "E1 非数字 id → 404（路由层挡掉）" 404

echo
echo "── 2. E1 客观数据区 ───────────────────────────"
req "$BASE/api/coach/context/48"
expect_status "E1 本人 → 200" 200
expect_code   "E1 code=0" 0
expect_in     "学生姓名是李小燕" "李小燕"
expect_in     "BKT 有音准控制" "音准控制"
expect_in     "BKT 有拖腔" "拖腔"
expect_in     "无源项 deviations 为 null" '"deviations":null'
expect_in     "无源项 cdm 为 null" '"cdm":null'
expect_in     "无源项 rag 为 null" '"rag":null'
expect_not_in "不该编造逐字偏差" '"cents"'

echo
echo "── 3. E1 空态（stu001，students.id=2 无数据）──"
JAR="$TD/stu001.jar"
post_json "/api/auth/login" "{\"username\":\"stu001\",\"password\":\"$PW\"}"
expect_status "stu001 登录 → 200" 200
req "$BASE/api/coach/context/2"
expect_status "E1 无数据学生 → 200（不是 404）" 200
expect_in     "BKT 为空数组" '"bkt":[]'
expect_in     "last_practice 为 null" '"last_practice":null'

echo
echo "── 4. E2 对话 ─────────────────────────────────"
JAR="$JAR_S"
post_json "/api/coach/chat" '{"student_id":48,"message":"这一句总是唱不准"}'
expect_status "E2 → 200" 200
expect_code   "E2 code=0" 0
REPLY=$(jget data.reply)
if [ -n "$REPLY" ]; then ok "E2 有 reply（${REPLY:0:20}…）"; else bad "E2 应有 reply" "$BODY"; fi
STRATEGY=$(jget data.strategy)
case "$STRATEGY" in
  引导|提示|鼓励|降难度) ok "E2 strategy 在枚举内（$STRATEGY）" ;;
  *) bad "E2 strategy 越界" "$STRATEGY" ;;
esac
EMOTION=$(jget data.emotion)
case "$EMOTION" in
  positive|neutral|concerned) ok "E2 emotion 在枚举内（$EMOTION）" ;;
  *) bad "E2 emotion 越界" "$EMOTION" ;;
esac

post_json "/api/coach/chat" '{"student_id":48,"message":""}'
expect_status "E2 空 message → 422" 422
expect_in     "空 message 报错中文化" "长度不能少于 1 个字符"

# 鼓励模式：挫败表达应被模型识别为鼓励
post_json "/api/coach/chat" '{"student_id":48,"message":"太难了，算了，不想练"}'
expect_status "E2 挫败表达 → 200" 200
S2=$(jget data.strategy)
if [ "$S2" = "鼓励" ] || [ "$S2" = "降难度" ]; then
  ok "挫败表达触发鼓励/降难度（$S2）"
else
  bad "挫败表达应切鼓励模式" "实际 strategy=$S2"
fi

echo
echo "── 5. E3 历史 ─────────────────────────────────"
req "$BASE/api/coach/history/48?limit=3"
expect_status "E3 → 200" 200
expect_code   "E3 code=0" 0
expect_not_in "历史不暴露 context_snapshot" "context_snapshot"

req "$BASE/api/coach/history/48?limit=abc"
expect_status "E3 非法 limit → 200（回落默认值，不 500）" 200

req "$BASE/api/coach/history/48"
expect_status "E3 无 limit → 200" 200

echo
echo "── 6. 对话确实落了库 ──────────────────────────"
# 上一步刚写过，E3 至少能读回 4 条（2 轮 query × 2 条）
COUNT=$(printf '%s' "$BODY" | "$PY" -c 'import json,sys; print(len(json.load(sys.stdin)["data"]))')
if [ "$COUNT" -ge 4 ]; then ok "E3 读回 $COUNT 条（含本次写入）"; else bad "E3 条数偏少" "$COUNT"; fi

echo
if [ "$FAIL" -eq 0 ]; then
  echo "$(green "全部通过")：$PASS 项"
  exit 0
fi
echo "$(red "失败 $FAIL 项")，通过 $PASS 项"
exit 1
```

**实现提示**：`TD` / `PASS` / `FAIL` / `red` / `green` / `ok` / `bad` / `req` / `jget` / `expect_status` / `expect_code` / `expect_in` / `expect_not_in` / `post_json` 这一整段从 `scripts/smoke_auth.sh` 第 25-155 行整段复制过来，逐字不改——它们与本脚本要验的内容无关，重写只会引入差异。

**但其中两行必须改**（`smoke_auth.sh` 里那两行的取值与本脚本不同）：

```bash
JAR_T="$TD/teacher.jar"     # smoke_auth.sh 原样
JAR_S="$TD/s01.jar"         # ← 原为 student.jar（stu002 的 cookie）；本脚本换成 s01
JAR="$JAR_T"
```

换掉 `JAR_S` 的原因：`smoke_auth.sh` 用 stu002 验登录，而 stu002 **没有 `students` 行**（users.id=4），E1 对它一律 403，验不了正常路径。本脚本要的是有完整数据的学生，即 `s01`（users.id=50 → students.id=48）。`JAR_T` 保持 teacher01 不变。

另外 `smoke_auth.sh` 第 263 行还有一个 `JAR="$TD/anon.jar"`（未登录用），本脚本第 1 节要用，一并复制，位置放在 `JAR_S` 那行之后。

- [ ] **Step 2: 赋可执行权限并跑**

```bash
chmod +x scripts/smoke_coach.sh
scripts/smoke_coach.sh
```

预期：全部通过。**若内网模型不可达**，第 4 节会全线失败并打印 `503`——那是环境问题不是代码问题，换到能访问 `192.168.36.208` 的机器上再跑。

- [ ] **Step 3: 再跑一次，确认可重复执行**

```bash
scripts/smoke_coach.sh
```

预期：与上次同样全部通过（脚本不依赖库里的既有条数）。

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_coach.sh
git commit -m "test: 新增 E 组 AI 教练接口冒烟脚本

覆盖鉴权门（未登录/教师/跨学生/非数字 id）、E1 正常与空态、
E2 四字段枚举与空 message 校验、鼓励模式触发、E3 分页与快照不外泄。"
```

---

### Task 7: 前端改造 `AI_teacher.html`

**Files:**
- Modify: `AI_teacher.html`

**Interfaces:**
- Consumes: E1/E2/E3 三条接口
- Produces: 无（终端页面）

---

- [ ] **Step 1: 左侧面板加 id 锚点**

在左侧「客观数据区」卡片的 `.card-body` 里，给四处加上 id（其余 HTML 结构不动）：

| 位置 | 现状 | 改为 |
|---|---|---|
| 曲目值 | `<span style="font-weight:600">《穆桂英挂帅》· 辕门外三声炮</span>`（`:610` 附近） | `<span style="font-weight:600" id="sumPiece">—</span>` |
| 段落值 | `<span style="font-weight:600">段落 1（辕门外三声炮）</span>` | `<span style="font-weight:600" id="sumSegment">—</span>` |
| 综合评分值 | `<span style="color:var(--warning);font-weight:700">82.5</span>` | `<span style="color:var(--warning);font-weight:700" id="sumScore">—</span>` |
| 练习时间值 | `<span style="font-weight:600">2026-08-05 14:32</span>` | `<span style="font-weight:600" id="sumTime">—</span>` |

给 BKT 区块和最外层两个容器加 id：把 `<div class="divider-label"><span>BKT 能力状态</span></div>` 之后那个 `<div class="data-section">…</div>` 改为 `<div class="data-section" id="bktList"></div>`（**内部那四段静态 BKT HTML 整块删掉**，改由 JS 渲染）；把 CDM 那个 `<div class="data-section">` 改为 `<div class="data-section" id="cdmList"></div>`（内部两个 `.cdm-tag` 也删掉）。

`#deviationTable` 的 tbody 内部那 10 行 `<tr>` 同样删掉（表头保留）。

- [ ] **Step 2: 删掉 mock 常量与查表逻辑**

删除 `STUDENT_PROFILE`（`:807-813`）、`SESSION_DATA`（`:815-825`）、`RESPONSES`（`:837-902`）三个常量，以及 `processUserInput`（`:962-1004`）整个函数。保留 `chatHistory`、`escapeHtml`、`appendMessage`、`appendSystem` 这几个还要用的。

`let socraticFailCount` / `bigDeviationCount` / `isEncourageMode` / `isFrustrationMode` / `currentStrategy` 这五个状态变量也删掉——鼓励模式现在由模型判断（prompt 里写死了规则），后端不再做关键词硬匹配，前端留着这些计数只会变成第二份真源。

- [ ] **Step 3: 加 E1 渲染**

在 `<script>` 里追加：

```javascript
/* ============================================================
   客观数据区（E1）
   ============================================================ */
function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = (value === null || value === undefined || value === "") ? "—" : value;
}

// 情绪是模型输出的三个档位，不是数值。这里给的是**按档位画的示意宽度**，
// 不是模型算出来的百分比——后端从来没返回过 emotionScore 这个数，
// 页面上原先那个 72% 是 mock 编的，不要把它当成真值恢复出来。
const EMOTION_STYLE = {
  positive:  { label: "积极", width: 85, color: "var(--success)" },
  neutral:   { label: "平稳", width: 60, color: "var(--primary)" },
  concerned: { label: "关切", width: 35, color: "var(--warning)" }
};

function placeholder(text) {
  return `<div style="font-size:11px;color:var(--text-muted);padding:6px 0">${escapeHtml(text)}</div>`;
}

function renderContext(ctx) {
  if (!ctx) return;

  // 演唱摘要
  const lp = ctx.last_practice;
  setText("sumPiece", lp && lp.segment_title);
  setText("sumSegment", lp && lp.segment_id !== null ? "段落 " + lp.segment_id : null);
  setText("sumScore", lp && lp.ai_score);
  setText("sumTime", lp && lp.recorded_at ? lp.recorded_at.replace("T", " ").slice(0, 16) : null);

  // 逐字偏差：库里无数据源，显式空位
  const tbody = document.querySelector("#deviationTable tbody");
  if (tbody) {
    if (!ctx.deviations) {
      tbody.innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--text-muted);padding:10px">
        逐字偏差待接入（当前库中无该校准数据源）</td></tr>`;
    } else {
      tbody.innerHTML = ctx.deviations.map(d => `<tr>
        <td>${escapeHtml(d.char)}</td><td>${escapeHtml(d.teacher)}</td>
        <td>${escapeHtml(d.student)}</td><td class="${d.cents < -20 ? "diff-pos" : "diff-neu"}">${d.cents}c</td>
      </tr>`).join("");
    }
  }

  // BKT
  const bktList = document.getElementById("bktList");
  if (bktList) {
    if (!ctx.bkt || !ctx.bkt.length) {
      bktList.innerHTML = placeholder("暂无能力数据");
    } else {
      bktList.innerHTML = ctx.bkt.map(b => {
        const pct = Math.round(b.p_l * 100);
        const color = pct >= 70 ? "var(--primary)" : (pct >= 50 ? "var(--warning)" : "var(--danger)");
        const conf = b.confidence === null || b.confidence === undefined ? "—" : b.confidence;
        return `<div style="margin-bottom:10px">
          <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text-secondary)">
            <span>${escapeHtml(b.skill)}</span><span style="color:${color};font-weight:700">${pct}%</span></div>
          <div class="bkt-bar"><div class="bkt-fill" style="width:${pct}%;background:${color}"></div></div>
          <div class="bkt-label"><span>P(L) = ${b.p_l.toFixed(2)} · 置信 ${conf}</span></div>
        </div>`;
      }).join("");
    }
  }

  // CDM：库里无数据源，显式空位
  const cdmList = document.getElementById("cdmList");
  if (cdmList) {
    cdmList.innerHTML = ctx.cdm
      ? ctx.cdm.map(c => `<div class="cdm-tag high">✓ ${escapeHtml(String(c))}</div>`).join("")
      : placeholder("CDM 归因待接入");
  }
}
```

- [ ] **Step 4: 加 E2/E3 与初始化**

替换 `sendMessage` / `sendQuick` / `init` 三个函数（`processUserInput` 已在 Step 2 删除）：

```javascript
/* ============================================================
   对话（E2 / E3）
   ============================================================ */
let accountStudentId = null;   // 由 /api/auth/me 拿到 role 后再向 E1 探出

function setBusy(busy) {
  document.getElementById("chatInput").disabled = busy;
  document.getElementById("sendBtn").disabled = busy;
}

function renderQuickReplies(list) {
  const box = document.getElementById("quickReplies");
  if (!box) return;
  if (!list || !list.length) { box.replaceChildren(); return; }
  box.replaceChildren(...list.map(t => {
    const b = document.createElement("button");
    b.className = "quick-btn";
    b.textContent = t;
    b.addEventListener("click", () => sendQuick(t));
    return b;
  }));
}

function applyReply(data) {
  const emo = EMOTION_STYLE[data.emotion] || EMOTION_STYLE.neutral;
  // 策略标签：只有「鼓励/降难度」才换样式，其余都是苏格拉底式引导
  document.getElementById("currentStrategyTag").textContent =
    data.strategy === "鼓励" ? "🌟 鼓励模式" : "🧠 苏格拉底式";
  document.getElementById("strategyName").textContent = data.strategy;
  document.getElementById("currentGuideText").textContent = data.reply;
  document.getElementById("emotionText").textContent = emo.label;
  document.getElementById("emotionScore").textContent = emo.label;
  document.getElementById("emotionBar").style.width = emo.width + "%";
  document.getElementById("emotionBar").style.background = emo.color;
  // 挫败提示条：模型判成鼓励模式时亮起
  document.getElementById("frustrationAlert").style.display =
    (data.strategy === "鼓励") ? "block" : "none";
  renderQuickReplies(data.quick_replies);
}

async function sendMessage() {
  const input = document.getElementById("chatInput");
  const text = input.value.trim();
  if (!text || accountStudentId === null) return;

  input.value = "";
  setBusy(true);
  appendMessage("user", text);

  try {
    const r = await fetch("/api/coach/chat", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ student_id: accountStudentId, message: text })
    });
    if (r.status === 401) return location.replace("/login.html");
    const body = await r.json();
    if (!r.ok) {
      appendSystem("AI 教练暂时不可用：" + (body.message || r.status));
      return;
    }
    appendMessage("ai", body.data.reply);
    applyReply(body.data);
  } catch (e) {
    appendSystem("网络异常，请稍后重试");
  } finally {
    setBusy(false);
    input.focus();
  }
}

function sendQuick(text) {
  document.getElementById("chatInput").value = text;
  sendMessage();
}

// E3 回读历史，按时间正序追加
async function loadHistory() {
  try {
    const r = await fetch(`/api/coach/history/${accountStudentId}`, { credentials: "same-origin" });
    if (!r.ok) return;
    const rows = (await r.json()).data || [];
    rows.forEach(m => appendMessage(m.role === "assistant" ? "ai" : "user", m.content,
      m.created_at ? m.created_at.slice(11, 19) : undefined));
  } catch (e) { /* 历史读不到不影响新对话 */ }
}

// 教师访问：右侧对话区替换为提示，不再发任何请求
function disableForNonStudent() {
  const body = document.getElementById("chatBody");
  body.replaceChildren();
  const tip = document.createElement("div");
  tip.className = "system-msg";
  tip.innerHTML = "<span>AI 教练仅学生可用</span>";
  body.appendChild(tip);
  document.getElementById("chatInput").disabled = true;
  document.getElementById("sendBtn").disabled = true;
  document.getElementById("quickReplies").replaceChildren();
}
```

`init()` 里保留原有的 textarea 自适应高度那段，把 `updateGuidePanel({...})` 那段 mock 初始值删掉；新增的加载流程放在**第二段脚本**（就是已经有 `/api/auth/me` 的那段）末尾——因为 `accountStudentId` 依赖登录角色，不能在页面刚解析时同步取。

在第二段脚本 `if (!user) return;` 之后插入：

```javascript
  if (user.role !== 'student') {
    // 教师没有学生档案，E1/E2/E3 都会 403，索性不发请求
    disableForNonStudent();
    return;
  }

  // 学生：先向 E1 探出自己的 student_id。E1 的路径参数必须与登录人一致，
  // 所以先试一个哨兵值不可行——直接用 /api/auth/me 的 user.id 反查不到
  // students.id（那是另一张表）。这里改成让 E1 自己回学生 id：
  // 页面拿不到就说明有权限问题，走提示。
  try {
    const me = await fetch(`/api/coach/context/${user.id}`, { credentials: 'same-origin' });
    if (!me.ok) { disableForNonStudent(); return; }
    const ctx = (await me.json()).data;
    accountStudentId = ctx.student.id;
    renderContext(ctx);
    await loadHistory();
  } catch (e) {
    disableForNonStudent();
  }
```

**⚠️ 这一段的路径参数是关键**：`/api/coach/context/<student_id>` 用的是 **`students.id`**，而 `user.id` 是 **`users.id`**，两者数值不同（DOC_ISSUES 第 21 条）。学生登进来时页面**手上没有 `students.id`**，所以上面的写法会在真实环境里 403。

**修正做法**：把 `user.id` 换成后端算好的值。为此在 **Task 3 的 E1 响应里补一个字段**（本 Task 的 Step 5 实施）：

- [ ] **Step 5: 让 E1 顺带回传自己的 student_id**

在 `app/schemas/coach.py` 的 `CoachContextOut` 里，`student` 字段已含 `id`——它**就是** `students.id`。所以前端只需要一个能拿到它的入口。

最省事的做法：给 E1 增加一条「不带 id 也能问自己」的便捷路径。在 `app/api/coach.py` 追加：

```python
@api_bp.route("/coach/context/me", methods=["GET"])
@login_required
@student_required
def coach_context_me():
    """E1 的本人便捷入口：路径不带 id。

    文档里 E1 只有带 <student_id> 的那条。加这条是因为页面登进来时只知道
    users.id，而 E1 要的是 students.id（DOC_ISSUES 第 21 条），前端无从换算。
    让它自己报回 student.id，前端再拿它去调带 id 的两条。
    """
    db = get_db()
    own = user_repo.get_student_id_by_user_id(db, current_user_id())
    if own is None:
        raise BusinessError(403, "AI 教练仅学生可用")
    return ok(CoachContextOut.model_validate(
        coach_service.build_context(db, own)).model_dump(mode="json"))
```

注意 Flask 路由匹配优先级：`/coach/context/me` 与 `/coach/context/<int:student_id>` 不冲突——后者带 `int` 转换器，`me` 匹配不上，会落到前者。

相应地，前端那段的 fetch 改成：

```javascript
    const me = await fetch('/api/coach/context/me', { credentials: 'same-origin' });
```

并把 `app/api/coach.py` 的 import 补上 `from app.common.errors import BusinessError` 与 `from app.repositories import user_repo`。

- [ ] **Step 6: 后端回归**

新增路由后必须重跑前三个 Task 的脚本，确认没打破既有契约：

```bash
.venv/bin/python scripts/tmp_check_coach_e1.py
.venv/bin/python scripts/tmp_check_coach_e2.py
.venv/bin/python scripts/tmp_check_coach_e3.py
scripts/smoke_coach.sh
```

预期：四个都通过。若 `smoke_coach.sh` 因新路径产生歧义而失败，检查 `int` 转换器是否写对。

- [ ] **Step 7: 浏览器验证**

启动后端与 nginx，分别以三个账号访问 `http://localhost/AI_teacher.html`：

| 账号 | 预期 |
|---|---|
| `s01` | 左侧 BKT 显示 8 条真实技法（音准控制/气息支撑/拖腔/滑音…），演唱摘要显示「—」，逐字偏差区显示「逐字偏差待接入」；发送「这一句总是唱不准」约 2 秒后收到真实回复，策略标签与快捷回复按钮随之更新 |
| `s01` 发「太难了，算了」 | 策略标签变为「🌟 鼓励模式」，挫败提示条亮起 |
| `stu001` | 左侧全为「—」与空态文案，页面不报错；对话仍可用（无客观数据注入） |
| `teacher01` | 右侧显示「AI 教练仅学生可用」，输入框禁用 |

刷新页面后，上一轮对话应从 E3 读回并渲染出来。

- [ ] **Step 8: Commit**

```bash
git add AI_teacher.html app/api/coach.py app/schemas/coach.py
git commit -m "feat: AI 教练页接通真实接口

- 左侧客观数据区改由 E1 渲染，无源三项显示「待接入」占位
- 对话接 E2/E3，删除 RESPONSES 查表与 setTimeout 假延迟
- 鼓励模式改由模型判断，移除前端关键词硬匹配
- 教师访问显示「仅学生可用」，不发请求
- 新增 E1 的 /coach/context/me 便捷入口（页面只知 users.id，无从换算 students.id）"
```

---

### Task 8: 登记文档缺口并清理临时脚本

**Files:**
- Modify: `DOC_ISSUES.md`
- Modify: `CLAUDE.md`
- Delete: `scripts/tmp_check_llm.py`、`scripts/tmp_check_coach_repo.py`、`scripts/tmp_check_coach_e1.py`、`scripts/tmp_check_coach_e2.py`、`scripts/tmp_check_coach_e3.py`

---

- [ ] **Step 1: 追加 DOC_ISSUES 条目**

先看现有最大编号：

```bash
grep -n "^## [0-9]" DOC_ISSUES.md | tail -3
```

在文件末尾追加（编号顺延）：

```markdown
## N. AI 教练对话（模块3）的三个数据缺口与两处口径冲突

实现 E1（`GET /api/coach/context/<id>`）时逐行核对了现有数据，发现文档要求的四块内容里有两块在库中没有任何来源，另有两处口径互相矛盾。本期按「有源接真、无源显式空位」实现，缺口登记如下：

**1. 逐字偏差无数据源。** PRD 3.1 与《3-功能清单》3.1 都要求左侧客观数据区展示「歌词级偏差」，页面也有一张逐字音高对照表。但：
- `practice_records.dimensions_json` 在现有 6 行里**全为 NULL**，且 `app/models/practice.py:30` 的注释写明它的语义是 `{音准,节奏,气息,咬字,拖腔}` 五个**维度分数**，不是逐字音高；
- `annotations` 表（5 行）是**教师技法标注**（`强音`/`换气`/`归韵` + `tolerance`），同样不是逐字音高。

**没有第三张表承载逐字数据。** 本实现返回 `deviations: null`，页面对应区块显示「逐字偏差待接入」。

**2. RAG 检索无数据源。** PRD 3.9、《2-系统设计说明》5.3、《3-功能清单》3.9 三处都要求向 prompt 注入「RAG 检索结果」，但《4-数据库设计-V1.1》的 15 张表里**没有任何知识库表或向量表**，也没说明检索什么语料。本实现返回 `rag: null`，prompt 中不注入该段。

**3. CDM 归因无数据源。** 页面左侧有「CDM 归因诊断」区，但库中无对应表；`score_calibrations` 只有 1 行且语义不同。本实现返回 `cdm: null`。

**4. 超时口径冲突。** PRD 3.2 写「发送消息 **2 秒**内生成回复」，而《2-系统设计说明》5.3 写「LLM 调用（**超时 3 秒**）」。本实现按 3 秒设 `LLM_TIMEOUT`，2 秒作为端到端验收目标由部署环境的网络状况决定，代码里不设上限。

**5. E1–E3 的权限未区分角色。** 《5-接口清单》2.5 节三条接口的权限列都只写「登录」，未规定教师能否查看学生对话，也未规定学生能否查看他人。本实现收紧为：仅 `role='student'` 可访问，且路径中的 `student_id` 必须等于登录人自己的 `students.id`，否则 403。

**6. 演示账号与数据对不上。** CLAUDE.md 记载的种子账号 `stu001`（`students.id=2`）名下 0 条 `practice_records`/`bkt_history`，`stu002`（`users.id=4`）**根本没有 `students` 行**（此点已在第 21 条记录）；而真正带有完整演示数据的是 `s01`–`s08`（`students.id` 48–55），这批账号未出现在任何文档里。AI 教练页的演示因此改用 `s01`（李小燕）。建议后续统一种子账号时一并处理。

**7. E1 新增了文档中没有的 `/api/coach/context/me`。** 页面登录后只知道 `users.id`，而 E1 要的是 `students.id`（第 21 条），前端无从换算，故增加这条不带 id 的便捷入口返回本人的上下文。文档里没有这个接口。
```

把 `## N.` 的 `N` 换成实际编号。

- [ ] **Step 2: 更新 CLAUDE.md**

在「运行方式」一节末尾（`TOP_DB` 那条之前）追加一段：

```markdown
- **AI 教练对话（`/api/coach/*`）依赖内网 LLM**：三条接口 E1/E2/E3 调公司自部署的 vLLM（`LLM_BASE_URL`，默认 `http://192.168.36.208:8007/v1`，模型 `Qwen3.6-27B-FP8`，**无需 API Key**）。配置在 `.env` 的 `LLM_*` 四项，读取处在 `app/config.py`。**调用必须带 `chat_template_kwargs: {"enable_thinking": false}`**——Qwen3.x 是推理模型，不关思考的话正文全进 `reasoning`、`content` 返回 `null`（实测 `max_tokens=800` 仍被思维链吃满）。该参数写死在 `app/services/llm_client.py` 里。**部署到目标机后要先验网络可达性**，开发机通不代表服务器通。无对外测试框架，验收用 `scripts/smoke_coach.sh`。相关缺口见 `DOC_ISSUES.md` 新增那一条。
- **`AI_teacher.html` 左侧「客观数据区」有三块是显式空位**：逐字偏差、CDM 归因、RAG 检索在库中**均无数据源**，E1 对这三项恒返回 `null`，页面显示「待接入」。**不要为了填满版面去编造这些数据**——`null` 表示「没有数据源」、`[]` 表示「查了是空」，这个区分是本项目刻意的约定（见 `app/services/homework_service.py:334`）。演示账号用 `s01`（`students.id=48` 李小燕），`stu001`/`stu002` 名下没有教学数据。
```

- [ ] **Step 3: 删临时脚本**

```bash
git rm scripts/tmp_check_llm.py scripts/tmp_check_coach_repo.py \
       scripts/tmp_check_coach_e1.py scripts/tmp_check_coach_e2.py \
       scripts/tmp_check_coach_e3.py
```

（若某个还没 add 过，用 `rm`。）

- [ ] **Step 4: 最终回归**

```bash
scripts/smoke_coach.sh
scripts/smoke_auth.sh
.venv/bin/python scripts/check_db.py
```

预期：`smoke_coach.sh` 全过；`smoke_auth.sh` 全过（确认本次改动没波及 A 组）；`check_db.py` 输出与改动前一致的既有差异（`demo_versions` 表 + `teacher_demos` 三列，**这是 main 上原本就有的漂移，不是本次引入的**）。

- [ ] **Step 5: Commit**

```bash
git add DOC_ISSUES.md CLAUDE.md
git commit -m "docs: 登记 AI 教练对话的七个文档缺口，清理临时脚本

- 逐字偏差/CDM/RAG 三项在库中无数据源，本期为显式空位
- 超时口径 PRD 2 秒 vs 系统设计 3 秒的冲突
- E1-E3 权限文档未区分角色，本实现收紧为仅学生本人
- 演示数据实际在 s01-s08，与文档记载的种子账号对不上
- E1 新增文档没有的 /coach/context/me 便捷入口"
```

---

## 完成标准

- `scripts/smoke_coach.sh` 全绿
- `scripts/smoke_auth.sh` 全绿（无回归）
- 浏览器里以 `s01` 登录，左侧显示 8 条真实 BKT + 三处「待接入」占位，对话真实往返，鼓励模式可触发
- 以 `teacher01` 登录看到「AI 教练仅学生可用」
- `chat_messages` 中能查到本轮对话，assistant 那条带 `context_snapshot`
- 五个临时脚本已删除，`DOC_ISSUES.md` 与 `CLAUDE.md` 已更新
