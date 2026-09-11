# 后端接口分层结构 + A 组认证接口 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为戏韵AI 后端建立 `api → services → repositories → models` 四层结构 + `common/` 横切层，并以《5-接口清单-V1.0》的 A 组认证接口（A1–A4）作为跑得通的模板。

**Architecture:** 分层单向依赖，`/api` 前缀由 `app/api/__init__.py` 的 `API_PREFIX` 常量唯一持有；应用装配集中在 `app/__init__.py::create_app()`；错误处理收敛到 `app/common/errors.py` 注册的四个全局 handler，路由与 service 层不写 `try/except`；session 读写只发生在 `api/` 层；事务边界在 service 层显式 `commit()`。（完整设计见 `docs/superpowers/specs/2026-09-11-backend-layering-design.md`）

**Tech Stack:** Python 3.11 ｜ Flask 3.1.3 ｜ SQLAlchemy 2.0.52 ｜ pydantic 2.13.5（由 pydantic-settings 传递引入）｜ werkzeug 3.1.8 ｜ PostgreSQL 15.7（Docker `docker_postgres`）

## Global Constraints

以下约束适用于**每一个任务**，不再逐条重复：

- **零新增 Python 依赖。** 不装 pytest、不装 jq、不引入 marshmallow / Flask-Login / JWT / Alembic。所有验证用 `.venv/bin/python` 内联脚本 + `curl`。
- **解释器一律用 `.venv/bin/python`。** PATH 上的 `python`/`pip` 是 pyenv 3.12，不是本项目 venv（Python 3.11.13）。
- **依赖方向单向**：`api → services → repositories → models`；`common/` 被各层引用、自身不引用上层。禁止反向 import。
- **`/api` 前缀字面量只在 `app/api/__init__.py` 出现一次。** 其余文件写相对路径或引用 `API_PREFIX`。
- **统一返回** `{"code":0,"message":"ok","data":...}`；`code` 沿用 HTTP 语义且与 HTTP 状态码一致（`DOC_ISSUES.md` 第 9 条）。
- **中文**：UI 文案、注释、文档全用中文；标识符保持英文；文件 UTF-8。
- **密码哈希必须显式 `method='pbkdf2:sha256'`**（werkzeug 3.x 默认已改为 scrypt，输出 162 字符会超出 `VARCHAR(128)`，见 `DOC_ISSUES.md` 第 8 条）。
- **事务边界**：`repositories/` 的写操作只 `db.flush()`；`services/` 写操作显式 `db.commit()`。
- **连接串必须是 `postgresql+psycopg2://`**（写成 `+psycopg` 会 `ModuleNotFoundError`）。
- **不改前端文件。** `pitch_comparison.html` 里 3 处旧路径（`:522` `/upload`、`:804` `/progress`、`:824` `/analyze`）由用户自行修改。
- **不改 `../艺校_docs/` 下的文档。** 发现的文档空白登记到根目录 `DOC_ISSUES.md`。
- 命令一律在项目根目录 `/Users/meiyazhao/Documents/lianshu/operaAI` 执行。

### 基线快照（2026-09-11，执行前记录；Task 11 / Task 13 用它验证「不该动的文件没被动」）

本项目**不用 git 管理**，所以用哈希当基线。以下值在整个实现过程中必须保持不变：

```
前端 HTML 聚合哈希 (md5 -q *.html | md5) : 0bee8fb6f56a6db81d5b8fa5c327a5a3   ← 12 个页面
requirements.txt                        : 61054cfc633a3a79c13c3fc2d27757da
```

逐文件哈希（万一聚合值变了，用这张表定位是哪个页面被改动）：

| 文件 | md5 |
|---|---|
| `AI_teacher.html` | `1e4900be2aad6b9fee8a66d46b37cf66` |
| `annotation.html` | `1bc4d8b66bb8f5497d54f5a4f2f77bba` |
| `cdm_report.html` | `a9656f5530337c350a7b5bb6f250f0e8` |
| `dashboard.html` | `c7dc0a25ba2e4c25b227d9db971ac1a2` |
| `demo_library.html` | `8f94cd4b9c7d25bf3a1b931c3caa3a40` |
| `homework.html` | `771bd85c3717772e6bb0f4b4ac2e3151` |
| `index.html` | `81f70239e8622ad42ea92d140517dffd` |
| `knowledge_graph.html` | `25915c9b10ebad0693e1797fd2e97356` |
| `pitch_comparison.html` | `12e6f9a3f74a7e482d73933d724bf354` |
| `recommendation.html` | `f9aa1e1bf29b4d9021cfacc902a100d8` |
| `sing_along.html` | `32edb5d7b4bdaae002404b099a5ba3a6` |
| `tracking.html` | `6c0e8c33b51d1b2d2aa03b175d27cb5e` |

> `pitch_comparison.html` 的 3 处旧路径调用（`:522` `/upload`、`:804` `/progress`、`:824` `/analyze`）**由用户自行修改**，不在本计划范围内——它的哈希变了说明有人越界了。

### 不用 git

本项目**没有也不引入 git 管理**。计划里不出现任何 `git` 命令；每个任务末尾的「检查点」就是停下来向协调者汇报，不做提交。

### 与设计文档的两处有意偏差（实现时按本计划为准）

1. **任务顺序**：设计文档 §12 把「`app/api/auth.py`」排在「`create_app()`」之前。本计划对调为 **create_app()（Task 8）先于 auth.py（Task 9）**——A1–A4 只有通过 `create_app()` 装配出的 app 才能测，反过来做会让 Task 9 无法独立验证。
2. **HTTPException 的文案**：设计文档 §5 只说该 handler 返回 JSON，未规定 message，字面实现会透出 Werkzeug 的英文长句（"The requested URL was not found on the server..."）。本计划在 `errors.py` 里加一张 `_HTTP_MSG_CN` 表映射常见状态码为中文，取不到时回退 `e.description`。这与本项目的中文 UI 一致，也与 §5.1 的取舍原则（英文只在携带具体信息时才保留）一致。

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `app/__init__.py` | `create_app()` 唯一装配点 | 重写 |
| `app/config.py` | Settings，新增 `secret_key` / `session_cookie_secure` | 改 |
| `app/db.py` | engine / session_scope / init_app / get_db | **不动** |
| `app/response.py` | `ok()` / `fail()` | **不动** |
| `app/models/` | 15 个 ORM 模型 | **不动** |
| `app/api/__init__.py` | `API_PREFIX` + `api_bp` + 子模块注册清单 | 重写 |
| `app/api/auth.py` | A1–A4 路由，session 读写唯一发生地 | 新建 |
| `app/services/auth_service.py` | 认证业务规则 + 事务边界 | 新建 |
| `app/repositories/user_repo.py` | `users` 表查询，写操作只 flush | 新建 |
| `app/schemas/auth.py` | `LoginIn` / `PasswordChangeIn` / `UserOut` | 新建 |
| `app/common/errors.py` | `BusinessError` + 四个全局 handler + pydantic 中文化 | 新建 |
| `app/common/decorators.py` | `login_required` / `teacher_required` / `current_user_id` | 新建 |
| `app/common/security.py` | `hash_password` / `verify_password` | 新建 |
| `app-d.py` | 演示路由迁到 `demo_bp`，app 由 `create_app()` 产出 | 改 |
| `scripts/smoke_auth.sh` | A1–A4 冒烟测试（curl + python3 标准库） | 新建 |
| `DOC_ISSUES.md` | 登记第 10–12 条 | 改 |
| `CLAUDE.md` | 补目录结构 / 依赖方向 / 事务边界三条约定 | 改 |

---

## Task 1: `app/config.py` 加 `secret_key` / `session_cookie_secure`

**Files:**
- Modify: `app/config.py`（全文重写，仅 14 行）
- 依赖已就位: `.env` 已有 `SECRET_KEY`（`secrets.token_urlsafe(48)`，64 字符）

**Interfaces:**
- Consumes: 无
- Produces: `settings.secret_key: str`、`settings.session_cookie_secure: bool`（Task 8 的 `create_app()` 读取这两个字段）

- [ ] **Step 1: 先确认现在读不到这两个字段（失败基线）**

```bash
.venv/bin/python -c "
from app.config import settings
print(settings.secret_key)          # 现在应当报 AttributeError
print(settings.session_cookie_secure)
"
```

Expected: `AttributeError: 'Settings' object has no attribute 'secret_key'`

- [ ] **Step 2: 改 `app/config.py`**

```python
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（app/ 的上一级）。用绝对路径，保证从任意工作目录启动都能读到 .env
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    database_url: str

    # Flask 会话签名密钥。刻意不给默认值——缺了它签名可被伪造，
    # 宁可启动即报错，也不要静默用一个空密钥跑起来。
    secret_key: str

    # 会话 Cookie 的 Secure 属性。默认 False 是刻意的：本地 nginx 走 HTTP，
    # 置 True 后浏览器会静默丢弃 Cookie，表现为「登录返回成功、之后每个请求都 401」，
    # 排查起来很绕。生产上 HTTPS 就绪后在 .env 加 SESSION_COOKIE_SECURE=true。
    session_cookie_secure: bool = False


settings = Settings()
```

- [ ] **Step 3: 验证两个字段都读到了**

```bash
.venv/bin/python -c "
from app.config import settings
assert len(settings.secret_key) == 64, len(settings.secret_key)
assert settings.secret_key.startswith('Ee_zYYvE'), settings.secret_key[:8]
assert settings.session_cookie_secure is False
print('secret_key 长度:', len(settings.secret_key))
print('session_cookie_secure:', settings.session_cookie_secure)
print('database_url:', settings.database_url)
"
```

Expected:
```
secret_key 长度: 64
session_cookie_secure: False
database_url: postgresql+psycopg2://xiyun:xiyun@localhost:5432/xiyun
```

- [ ] **Step 4: 确认缺 `secret_key` 时会明确报错（防止它退化回可选）**

```bash
cd /tmp && /Users/meiyazhao/Documents/lianshu/operaAI/.venv/bin/python -c "
import os
os.environ['SECRET_KEY'] = ''
" ; cd /Users/meiyazhao/Documents/lianshu/operaAI
.venv/bin/python -c "
from app.config import Settings
try:
    Settings(_env_file=None)
except Exception as e:
    print('缺 secret_key 时如期报错:', type(e).__name__)
"
```

Expected: `缺 secret_key 时如期报错: ValidationError`

- [ ] **Step 5: 顺带确认没弄坏数据库模型与真库的一致性**

```bash
.venv/bin/python scripts/check_db.py
```

Expected: 末行 `结果：全部一致 ✓`，退出码 0

- [ ] **Step 6: 检查点 —— 停下，交给协调者审查**

**本任务不执行任何 git 命令**（本项目不用 git 管理）。停在这里，把两样东西汇报给协调者，等审查通过后再开始下一个任务：

1. 本任务新增/修改的文件清单（用 `ls` 或 `find` 列，不要用 `git status`）
2. 上一步验证命令的完整输出

协调者审查通过后，直接进入下一个任务；被退回则改完重跑验证再汇报。

---

## Task 2: `app/common/errors.py` —— 统一错误出口

**Files:**
- Create: `app/common/__init__.py`
- Create: `app/common/errors.py`
- 使用: `app/response.py` 的 `fail()`（已存在，不改）

**Interfaces:**
- Consumes: `app.response.fail(code, message) -> (Response, int)`
- Produces:
  - `BusinessError(code: int, message: str)`，实例带 `.code` / `.message`（Task 4、7、9 抛它）
  - `register_error_handlers(app) -> None`（Task 8 的 `create_app()` 调用）

- [ ] **Step 1: 建包**

```bash
mkdir -p app/common
```

`app/common/__init__.py` 内容：

```python
"""横切关注点：异常与全局处理、鉴权装饰器、密码哈希。

本包被 api / services / repositories 各层引用，自身不引用任何上层模块。
"""
```

- [ ] **Step 2: 写一个会失败的验证脚本**

存成 `app/common/_t_errors.py`（**验证完就删，不留在仓库里**）：

```python
# -*- coding: utf-8 -*-
"""errors.py 的临时验证脚本：起一个最小 Flask app，把四条出口各打一遍。"""
from flask import Flask
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.common.errors import BusinessError, register_error_handlers

app = Flask(__name__)
register_error_handlers(app)


class M(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    pw: str = Field(min_length=8)
    new: str = Field(min_length=1)

    @field_validator("new")
    @classmethod
    def _not_same(cls, v, info):
        if info.data.get("pw") == v:
            raise ValueError("新密码不能与旧密码相同")
        return v


@app.route("/be")
def be():
    raise BusinessError(403, "账号已停用")


@app.route("/ve1")
def ve1():
    M.model_validate({"pw": "123"})                 # username 缺失 + pw 过短
    return ""


@app.route("/ve2")
def ve2():
    # 自定义校验必须单独测：pw 合法才会进 info.data，_not_same 才会真正跑
    M.model_validate({"username": "u", "pw": "12345678", "new": "12345678"})
    return ""


@app.route("/boom")
def boom():
    raise RuntimeError("连接串 postgresql://xiyun:xiyun@localhost/xiyun 拒绝连接")


c = app.test_client()

cases = [
    ("/be",   403, {"code": 403, "message": "账号已停用", "data": None}),
    ("/nope", 404, {"code": 404, "message": "接口不存在", "data": None}),
    ("/boom", 500, {"code": 500, "message": "服务器内部错误", "data": None}),
]
for path, status, want in cases:
    r = c.get(path)
    print(f"{path:8} -> HTTP {r.status_code} {r.get_data(as_text=True)}")
    assert r.status_code == status, (path, r.status_code)
    assert r.get_json() == want, (path, r.get_json())

# 500 不得泄漏内部细节
raw = c.get("/boom").get_data(as_text=True)
assert "postgresql" not in raw and "RuntimeError" not in raw, raw
print("500 未泄漏内部细节 ✓")

# pydantic → 422，且报错都中文化
r = c.get("/ve1")
print("ve1      ->", r.status_code, r.get_data(as_text=True))
assert r.status_code == 422, r.status_code
msg = r.get_json()["message"]
assert "username: 必填" in msg, msg
assert "pw: 长度不能少于 8 个字符" in msg, msg
assert r.get_json()["code"] == 422

# 自定义校验单测：pydantic v2 不把「校验失败的字段」放进 info.data。
# 若把 pw 过短与 new==pw 塞进同一个请求，pw 先失败被剔除，_not_same 里
# info.data.get("pw") 得到 None，两条断言天然互斥，必须拆开。
r = c.get("/ve2")
print("ve2      ->", r.status_code, r.get_data(as_text=True))
assert r.status_code == 422, r.status_code
assert "new: 新密码不能与旧密码相同" in r.get_json()["message"]

print("OK")
```

- [ ] **Step 3: 跑它，确认现在失败**

```bash
.venv/bin/python -m app.common._t_errors
```

Expected: `ModuleNotFoundError: No module named 'app.common.errors'`

- [ ] **Step 4: 写 `app/common/errors.py`**

```python
# -*- coding: utf-8 -*-
"""统一错误出口。

api 层与 services 层都不写 try/except——业务错误抛 BusinessError、
参数错误由 pydantic 抛 ValidationError，加上 HTTP 异常与未捕获异常，
四类一起汇到本文件注册的 handler，最终都变成
{"code","message","data"} 形态的 JSON。

code 沿用 HTTP 语义、与 HTTP 状态码一致（见 DOC_ISSUES.md 第 9 条）。
"""

from flask import jsonify
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

from app.response import fail


class BusinessError(Exception):
    """业务规则不满足。由 service 层抛出，handler 转成 fail(code, message)。

    例：raise BusinessError(401, "用户名或密码错误")
    """

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# pydantic v2 的默认报错是英文（实测 'Field required'、
# 'String should have at least 8 characters'），本项目是中文 UI，
# 直接透给前端不可接受。已知的 type 在这里映射成中文，参数从 err["ctx"] 取。
_MSG_CN = {
    "missing": lambda c: "必填",
    "string_too_short": lambda c: f"长度不能少于 {c['min_length']} 个字符",
    "string_too_long": lambda c: f"长度不能超过 {c['max_length']} 个字符",
    "int_parsing": lambda c: "必须是整数",
}

# HTTP 异常的默认 description 是 Werkzeug 的英文长句
# （"The requested URL was not found on the server..."），前端直接展示很突兀。
# 常见状态码映射成中文；表里没有的仍回退 description，不吞信息。
_HTTP_MSG_CN = {
    400: "请求参数错误",
    401: "未登录",
    403: "无权限",
    404: "接口不存在",
    405: "请求方法不允许",
    413: "上传内容过大",
    415: "不支持的 Content-Type",
    422: "参数错误",
    500: "服务器内部错误",
}


def _format_validation_error(exc: ValidationError) -> str:
    """把 pydantic 的报错压成一句话，供前端直接展示。

    三层处理：① 已知 type 走中文映射；② 自定义 validator 抛的 ValueError
    本身就是中文，只需去掉 pydantic 加的 "Value error, " 前缀；
    ③ 其余回退英文原文——宁可给英文，也不要用「参数错误」四个字把信息吞掉。
    """
    parts = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err["loc"]) or "body"
        if fmt := _MSG_CN.get(err["type"]):
            msg = fmt(err.get("ctx") or {})
        else:
            msg = err["msg"].removeprefix("Value error, ")
        parts.append(f"{loc}: {msg}")
    return "; ".join(parts)


def register_error_handlers(app):
    """在 Flask 应用上注册四个错误 handler。

    Flask 按异常类型的精确度选 handler，注册顺序无关紧要：
    BusinessError / ValidationError 比 Exception 更具体，会先命中。
    DEBUG=True 时同样生效——Flask 的 handle_user_exception 先查已注册的
    handler，查到就直接调用，走不到 PROPAGATE_EXCEPTIONS 那条分支（3.1.3 实测）。
    """

    @app.errorhandler(BusinessError)
    def _business_error(e: BusinessError):
        return fail(e.code, e.message)

    @app.errorhandler(ValidationError)
    def _validation_error(e: ValidationError):
        return fail(422, _format_validation_error(e))

    @app.errorhandler(HTTPException)
    def _http_exception(e: HTTPException):
        # 这条必须有：未匹配的 URL 默认返回 Werkzeug 的 HTML 404 页，
        # 前端 JSON.parse 会当场炸，也不符合《5-接口清单》的统一返回。
        code = e.code or 500
        return fail(code, _HTTP_MSG_CN.get(code) or e.description or "请求错误")

    @app.errorhandler(Exception)
    def _unexpected(e: Exception):
        # 堆栈只进日志，响应不回内部细节，避免泄漏文件路径、连接串等。
        app.logger.exception("未捕获异常: %s", e)
        return fail(500, "服务器内部错误")
```

- [ ] **Step 5: 再跑验证脚本，应当全绿**

```bash
.venv/bin/python -m app.common._t_errors
```

Expected:
```
/be      -> HTTP 403 {"code":403,"data":null,"message":"账号已停用"}
/nope    -> HTTP 404 {"code":404,"data":null,"message":"接口不存在"}
/boom    -> HTTP 500 {"code":500,"data":null,"message":"服务器内部错误"}
500 未泄漏内部细节 ✓
ve1      -> 422 {"code":422,"data":null,"message":"username: 必填; pw: 长度不能少于 8 个字符"}
ve2      -> 422 {"code":422,"data":null,"message":"new: 新密码不能与旧密码相同"}
OK
```

- [ ] **Step 6: 删掉临时脚本并确认没误删**

```bash
rm app/common/_t_errors.py
ls app/common/
```

Expected: `__init__.py  __pycache__  errors.py`

- [ ] **Step 7: 检查点 —— 停下，交给协调者审查**

**本任务不执行任何 git 命令**（本项目不用 git 管理）。停在这里，把两样东西汇报给协调者，等审查通过后再开始下一个任务：

1. 本任务新增/修改的文件清单（用 `ls` 或 `find` 列，不要用 `git status`）
2. 上一步验证命令的完整输出

协调者审查通过后，直接进入下一个任务；被退回则改完重跑验证再汇报。

---

## Task 3: `app/common/security.py` —— 密码哈希

**Files:**
- Create: `app/common/security.py`
- 使用: 已在 `seed.sql` 里的真实 pbkdf2 哈希（只读，不修改）

**Interfaces:**
- Consumes: 无
- Produces: `hash_password(plain: str) -> str`、`verify_password(password_hash: str, plain: str) -> bool`（Task 7 的 `auth_service` 用）

- [ ] **Step 1: 写验证脚本（先看它失败）**

存成 `app/common/_t_security.py`（验证完删除）：

```python
# -*- coding: utf-8 -*-
"""security.py 的临时验证脚本。"""
from app.common.security import HASH_METHOD, hash_password, verify_password

# seed.sql 里 teacher01 的真实哈希，用来确认与既有数据互通
SEED_TEACHER01 = (
    "pbkdf2:sha256:1000000$mfKCSpfKvUXWipn8$"
    "fa5942b981cabbda43d543e8c59b602fd517cfd06180cdce73f8cda08d019f75"
)

assert HASH_METHOD == "pbkdf2:sha256"

h = hash_password("xiyun@2026")
print("哈希前缀:", h.split("$")[0], "长度:", len(h))
assert h.startswith("pbkdf2:sha256:"), h
# users.password_hash 是 VARCHAR(128)，超了插入直接报 value too long
assert len(h) <= 128, len(h)

assert verify_password(h, "xiyun@2026") is True
assert verify_password(h, "xiyun@2027") is False
assert verify_password(SEED_TEACHER01, "xiyun@2026") is True
assert verify_password(SEED_TEACHER01, "wrong") is False

# 每次加盐，同一个明文两次哈希必须不同
assert hash_password("xiyun@2026") != hash_password("xiyun@2026")

print("OK")
```

（`SEED_TEACHER01` 的哈希值直接抄 `seed.sql:24`，不要手改——本步骤已验证它对 `xiyun@2026` 校验为 True。）

- [ ] **Step 2: 跑它，确认失败**

```bash
.venv/bin/python -m app.common._t_security
```

Expected: `ModuleNotFoundError: No module named 'app.common.security'`

- [ ] **Step 3: 写 `app/common/security.py`**

```python
# -*- coding: utf-8 -*-
"""密码哈希。

哈希算法只在这里指定一次，避免第二处再踩 werkzeug 3.x 的默认值变更
（DOC_ISSUES.md 第 8 条）。
"""

from werkzeug.security import check_password_hash, generate_password_hash

# 必须显式指定：werkzeug 3.x 的 generate_password_hash 默认算法已由 pbkdf2
# 改为 scrypt，输出 162 字符，超出 users.password_hash 的 VARCHAR(128)，
# 插入时报 "value too long"。pbkdf2:sha256 输出 103 字符。
# 《6-登录与数据隔离方案》要求的也正是 pbkdf2。
HASH_METHOD = "pbkdf2:sha256"


def hash_password(plain: str) -> str:
    """生成密码哈希（自带随机盐）。"""
    return generate_password_hash(plain, method=HASH_METHOD)


def verify_password(password_hash: str, plain: str) -> bool:
    """校验明文是否匹配哈希。

    算法与轮数从 password_hash 自身解析，所以 seed.sql 里既有的哈希
    （pbkdf2:sha256:1000000$...）无需特殊处理也能校验通过。
    """
    return check_password_hash(password_hash, plain)
```

- [ ] **Step 4: 再跑，应当全绿**

```bash
.venv/bin/python -m app.common._t_security
```

Expected:
```
哈希前缀: pbkdf2:sha256:1000000 长度: 103
OK
```

- [ ] **Step 5: 删临时脚本**

```bash
rm app/common/_t_security.py
```

- [ ] **Step 6: 检查点 —— 停下，交给协调者审查**

**本任务不执行任何 git 命令**（本项目不用 git 管理）。停在这里，把两样东西汇报给协调者，等审查通过后再开始下一个任务：

1. 本任务新增/修改的文件清单（用 `ls` 或 `find` 列，不要用 `git status`）
2. 上一步验证命令的完整输出

协调者审查通过后，直接进入下一个任务；被退回则改完重跑验证再汇报。

---

## Task 4: `app/common/decorators.py` —— 鉴权装饰器

**Files:**
- Create: `app/common/decorators.py`
- 依据: `../艺校_docs/6-登录与数据隔离方案-V1.0.docx` 第 5 节的参考实现（返回体改走 `response.fail()`，由 Task 2 的 `BusinessError` handler 兜）

**Interfaces:**
- Consumes: `app.common.errors.BusinessError`
- Produces:
  - `login_required(fn)` —— 未登录抛 `BusinessError(401, "未登录")`
  - `teacher_required(fn)` —— 非教师抛 `BusinessError(403, "需要教师权限")`
  - `current_user_id() -> int | None`（Task 9 的 A3/A4 用）
  - **叠放顺序**：`@login_required` 在外层、`@teacher_required` 在内层

- [ ] **Step 1: 写验证脚本（先看它失败）**

存成 `app/common/_t_decorators.py`（验证完删除）：

```python
# -*- coding: utf-8 -*-
"""decorators.py 的临时验证脚本：起最小 app，用测试客户端伪造会话。"""
from flask import Blueprint, Flask, session

from app.common.decorators import current_user_id, login_required, teacher_required
from app.common.errors import register_error_handlers

app = Flask(__name__)
app.secret_key = "test-only"
register_error_handlers(app)

bp = Blueprint("t", __name__, url_prefix="/t")


@bp.route("/login-only")
@login_required
def login_only():
    return {"uid": current_user_id()}


@bp.route("/teacher-only")
@login_required
@teacher_required
def teacher_only():
    return {"uid": current_user_id(), "role": session["role"]}


@bp.route("/set/<role>")
def set_session(role):
    session["user_id"] = 7
    session["role"] = role
    return {"ok": True}


@bp.route("/clear")
def clear():
    session.clear()
    return {"ok": True}


app.register_blueprint(bp)
c = app.test_client()

# 未登录 → 401
r = c.get("/t/login-only")
print("未登录 login_only ->", r.status_code, r.get_json())
assert r.status_code == 401 and r.get_json()["message"] == "未登录"

r = c.get("/t/teacher-only")
assert r.status_code == 401, r.status_code   # 外层 login_required 先拦，不是 403
print("未登录 teacher_only -> 401（外层先拦，说明叠放顺序对）✓")

# 学生 → teacher_required 拦到 403
c.get("/t/set/student")
r = c.get("/t/login-only")
assert r.status_code == 200 and r.get_json()["uid"] == 7, r.get_data(as_text=True)
print("学生 login_only -> 200 ✓")

r = c.get("/t/teacher-only")
print("学生 teacher_only ->", r.status_code, r.get_json())
assert r.status_code == 403 and r.get_json()["message"] == "需要教师权限"

# 教师 → 全通
c.get("/t/set/teacher")
assert c.get("/t/teacher-only").status_code == 200
print("教师 teacher_only -> 200 ✓")

# 清空会话后回到 401
c.get("/t/clear")
assert c.get("/t/login-only").status_code == 401
print("会话清空后 -> 401 ✓")

print("OK")
```

- [ ] **Step 2: 跑它，确认失败**

```bash
.venv/bin/python -m app.common._t_decorators
```

Expected: `ModuleNotFoundError: No module named 'app.common.decorators'`

- [ ] **Step 3: 写 `app/common/decorators.py`**

```python
# -*- coding: utf-8 -*-
"""鉴权装饰器（《6-登录与数据隔离方案-V1.0》第 5 节）。

叠放顺序有意义——login_required 在外层，未登录先 401；
teacher_required 在内层，已登录再判 403：

    @api_bp.route("/students", methods=["POST"])
    @login_required
    @teacher_required
    def create_student(): ...
"""

from functools import wraps

from flask import session

from app.common.errors import BusinessError


def current_user_id():
    """取当前登录用户的 id；未登录返回 None。"""
    return session.get("user_id")


def login_required(fn):
    """未登录则抛 401。"""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("user_id") is None:
            raise BusinessError(401, "未登录")
        return fn(*args, **kwargs)

    return wrapper


def teacher_required(fn):
    """非教师则抛 403。必须叠在 login_required 内层使用。"""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("role") != "teacher":
            raise BusinessError(403, "需要教师权限")
        return fn(*args, **kwargs)

    return wrapper
```

- [ ] **Step 4: 再跑，应当全绿**

```bash
.venv/bin/python -m app.common._t_decorators
```

Expected:
```
未登录 login_only -> 401 {'code': 401, 'data': None, 'message': '未登录'}
未登录 teacher_only -> 401（外层先拦，说明叠放顺序对）✓
学生 login_only -> 200 ✓
学生 teacher_only -> 403 {'code': 403, 'data': None, 'message': '需要教师权限'}
教师 teacher_only -> 200 ✓
会话清空后 -> 401 ✓
OK
```

- [ ] **Step 5: 删临时脚本**

```bash
rm app/common/_t_decorators.py
ls app/common/
```

Expected: `__init__.py  __pycache__  decorators.py  errors.py  security.py`

- [ ] **Step 6: 检查点 —— 停下，交给协调者审查**

**本任务不执行任何 git 命令**（本项目不用 git 管理）。停在这里，把两样东西汇报给协调者，等审查通过后再开始下一个任务：

1. 本任务新增/修改的文件清单（用 `ls` 或 `find` 列，不要用 `git status`）
2. 上一步验证命令的完整输出

协调者审查通过后，直接进入下一个任务；被退回则改完重跑验证再汇报。

---

## Task 5: `app/schemas/auth.py` —— 入参与出参模型

**Files:**
- Create: `app/schemas/__init__.py`
- Create: `app/schemas/auth.py`
- 使用: pydantic 2.13.5（已由 pydantic-settings 传递引入，**不新增依赖**）

**Interfaces:**
- Consumes: 无
- Produces:
  - `LoginIn(username: str, password: str)`，`model_validate(dict)` 校验
  - `PasswordChangeIn(old: str, new: str)`，`new` 最短 8 位且不得与 `old` 相同
  - `UserOut(id: int, username: str, display_name: str, role: str)`，带 `from_attributes=True`，可 `UserOut.model_validate(user_orm_obj)`
  - 三者校验失败都抛 `pydantic.ValidationError`，由 Task 2 的 handler 转 422

- [ ] **Step 1: 建包**

```bash
mkdir -p app/schemas
```

`app/schemas/__init__.py` 内容：

```python
"""入参与出参校验（pydantic v2）。每个接口模块一个文件。"""
```

- [ ] **Step 2: 写验证脚本（先看它失败）**

存成 `app/schemas/_t_auth.py`（验证完删除）：

```python
# -*- coding: utf-8 -*-
"""schemas/auth.py 的临时验证脚本。"""
from pydantic import ValidationError

from app.schemas.auth import LoginIn, PasswordChangeIn, UserOut


def err_of(model, payload):
    try:
        model.model_validate(payload)
    except ValidationError as e:
        return {(tuple(x["loc"]), x["type"]) for x in e.errors()}
    raise AssertionError(f"{payload} 竟然通过了校验")


# LoginIn
d = LoginIn.model_validate({"username": "stu001", "password": "xiyun@2026"})
assert d.username == "stu001" and d.password == "xiyun@2026"
assert err_of(LoginIn, {}) == {(("username",), "missing"), (("password",), "missing")}
assert err_of(LoginIn, {"username": "a" * 51, "password": "x"}) == {(("username",), "string_too_long")}
print("LoginIn ✓")

# PasswordChangeIn
d = PasswordChangeIn.model_validate({"old": "xiyun@2026", "new": "newpass123"})
assert d.new == "newpass123"
assert err_of(PasswordChangeIn, {"old": "x"}) == {(("new",), "missing")}
assert err_of(PasswordChangeIn, {"old": "x", "new": "123"}) == {(("new",), "string_too_short")}
assert err_of(PasswordChangeIn, {"old": "xiyun@2026", "new": "xiyun@2026"}) == {(("new",), "value_error")}
print("PasswordChangeIn ✓")


# UserOut：既能吃 dict，也能吃 ORM 对象
class FakeUser:
    id = 2
    username = "stu001"
    display_name = "张三"
    role = "student"
    password_hash = "不该被带出来"


u = UserOut.model_validate(FakeUser())
assert u.model_dump() == {"id": 2, "username": "stu001", "display_name": "张三", "role": "student"}
assert "password" not in u.model_dump_json()
u2 = UserOut.model_validate({"id": 1, "username": "t", "display_name": "王老师", "role": "teacher"})
assert u2.role == "teacher"
print("UserOut ✓  序列化结果:", u.model_dump_json())

print("OK")
```

- [ ] **Step 3: 跑它，确认失败**

```bash
.venv/bin/python -m app.schemas._t_auth
```

Expected: `ModuleNotFoundError: No module named 'app.schemas.auth'`

- [ ] **Step 4: 写 `app/schemas/auth.py`**

```python
# -*- coding: utf-8 -*-
"""A 组认证接口的入参/出参模型。

pydantic 已由 pydantic-settings 传递引入（2.13.5），零新增依赖。
校验失败抛 ValidationError，由 app/common/errors.py 的 handler 转成 422 中文文案。
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginIn(BaseModel):
    """A1 入参。上限对齐 users 表的列宽：username VARCHAR(50)。"""

    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class PasswordChangeIn(BaseModel):
    """A4 入参。

    《5-接口清单》未规定新密码强度，本项目取最短 8 位、且不得与旧密码相同
    （DOC_ISSUES.md 第 10 条）。
    """

    old: str = Field(min_length=1, max_length=128)
    new: str = Field(min_length=8, max_length=128)

    @field_validator("new")
    @classmethod
    def _not_same_as_old(cls, v, info):
        # old 声明在前，此处 info.data 里必定已有它
        if info.data.get("old") == v:
            raise ValueError("新密码不能与旧密码相同")
        return v


class UserOut(BaseModel):
    """A1 / A3 共用的出参。

    from_attributes=True 让它能直接吃 ORM 的 User 对象；
    字段是白名单，password_hash 不在其中，不可能被带出去。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: str
```

- [ ] **Step 5: 再跑，应当全绿**

```bash
.venv/bin/python -m app.schemas._t_auth
```

Expected:
```
LoginIn ✓
PasswordChangeIn ✓
UserOut ✓  序列化结果: {"id":2,"username":"stu001","display_name":"张三","role":"student"}
OK
```

- [ ] **Step 6: 删临时脚本**

```bash
rm app/schemas/_t_auth.py
ls app/schemas/
```

Expected: `__init__.py  __pycache__  auth.py`

- [ ] **Step 7: 检查点 —— 停下，交给协调者审查**

**本任务不执行任何 git 命令**（本项目不用 git 管理）。停在这里，把两样东西汇报给协调者，等审查通过后再开始下一个任务：

1. 本任务新增/修改的文件清单（用 `ls` 或 `find` 列，不要用 `git status`）
2. 上一步验证命令的完整输出

协调者审查通过后，直接进入下一个任务；被退回则改完重跑验证再汇报。

---

## Task 6: `app/repositories/user_repo.py` —— 数据访问层

**Files:**
- Create: `app/repositories/__init__.py`
- Create: `app/repositories/user_repo.py`
- 使用: `app/models/user.py` 的 `User`、`app/db.py` 的 `session_scope()`（均不改）

**Interfaces:**
- Consumes: `sqlalchemy.orm.Session`、`app.models.user.User`（字段：`id` / `username` / `password_hash` / `role` / `display_name` / `is_active` / `created_at`）
- Produces:
  - `get_by_username(db: Session, username: str) -> User | None`
  - `get_by_id(db: Session, user_id: int) -> User | None`
  - `update_password(db: Session, user: User, password_hash: str) -> None`（只 `flush()`，不 commit）
  - 三个函数的第一个参数都是 `db: Session`（约定见 CLAUDE.md，Task 12 会写进去）

- [ ] **Step 1: 建包**

```bash
mkdir -p app/repositories
```

`app/repositories/__init__.py` 内容：

```python
"""数据访问层（SQL 封装）。

约定：
  - 第一个参数永远是 db: Session，由 service 层传下来，本层不自己取全局会话
  - 写操作只 db.flush()（拿 id、触发约束检查），不 commit——事务边界在 service 层
  - 数据隔离规则（《6-登录与数据隔离方案》第 4 节）后续集中落在本层，
    例如 student_repo.get_visible(db, student_id, current_user)，
    越权直接抛 BusinessError(403, ...)，所有调用方自动继承
"""
```

- [ ] **Step 2: 写验证脚本（先看它失败）**

存成 `app/repositories/_t_user_repo.py`（验证完删除）：

```python
# -*- coding: utf-8 -*-
"""user_repo.py 的临时验证脚本。需要真库、且已灌 seed.sql。"""
from app.db import session_scope
from app.repositories import user_repo

with session_scope() as db:
    u = user_repo.get_by_username(db, "stu001")
    if u is None:
        raise SystemExit("users 表里没有 stu001 —— 先执行 seed.sql（命令见 seed.sql 头注释）")

    print("get_by_username:", u.id, u.username, u.role, u.display_name)
    assert u.role == "student", u.role
    assert u.display_name == "张三", u.display_name
    assert u.password_hash.startswith("pbkdf2:sha256:"), u.password_hash[:20]

    assert user_repo.get_by_username(db, "no-such-user") is None

    u2 = user_repo.get_by_id(db, u.id)
    assert u2 is not None and u2.username == "stu001"
    assert user_repo.get_by_id(db, 999999) is None

    # 教师账号同样能查到
    t = user_repo.get_by_username(db, "teacher01")
    assert t is not None and t.role == "teacher", t

print("OK")
```

- [ ] **Step 3: 跑它，确认失败**

```bash
.venv/bin/python -m app.repositories._t_user_repo
```

Expected: `ModuleNotFoundError: No module named 'app.repositories.user_repo'`

- [ ] **Step 4: 写 `app/repositories/user_repo.py`**

```python
# -*- coding: utf-8 -*-
"""users 表的数据访问。

写操作只 flush()、不 commit——事务边界在 service 层，理由见 CLAUDE.md。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


def get_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def get_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def update_password(db: Session, user: User, password_hash: str) -> None:
    """改密码哈希。只 flush，提交由 service 层负责。"""
    user.password_hash = password_hash
    db.flush()
```

- [ ] **Step 5: 再跑，应当全绿**

```bash
.venv/bin/python -m app.repositories._t_user_repo
```

Expected:
```
get_by_username: 2 stu001 student 张三
OK
```

（id 若不是 2 也正常——取决于序列起点；脚本没有断言具体 id。）

- [ ] **Step 6: 删临时脚本**

```bash
rm app/repositories/_t_user_repo.py
ls app/repositories/
```

Expected: `__init__.py  __pycache__  user_repo.py`

- [ ] **Step 7: 检查点 —— 停下，交给协调者审查**

**本任务不执行任何 git 命令**（本项目不用 git 管理）。停在这里，把两样东西汇报给协调者，等审查通过后再开始下一个任务：

1. 本任务新增/修改的文件清单（用 `ls` 或 `find` 列，不要用 `git status`）
2. 上一步验证命令的完整输出

协调者审查通过后，直接进入下一个任务；被退回则改完重跑验证再汇报。

---

## Task 7: `app/services/auth_service.py` —— 业务逻辑与事务边界

**Files:**
- Create: `app/services/__init__.py`
- Create: `app/services/auth_service.py`
- 使用: `app/repositories/user_repo.py`（Task 6）、`app/common/security.py`（Task 3）、`app/common/errors.py`（Task 2）

**Interfaces:**
- Consumes: `user_repo.get_by_username(db, username)`、`user_repo.get_by_id(db, user_id)`、`user_repo.update_password(db, user, password_hash)`、`hash_password(plain)`、`verify_password(hash, plain)`、`BusinessError(code, message)`
- Produces:
  - `login(db: Session, username: str, password: str) -> User`
    - 用户不存在或密码错 → `BusinessError(401, "用户名或密码错误")`
    - `is_active` 为假 → `BusinessError(403, "账号已停用")`
  - `get_user(db: Session, user_id: int) -> User`
    - 查不到 → `BusinessError(401, "登录状态已失效")`
  - `change_password(db: Session, user: User, old: str, new: str) -> None`
    - 原密码错 → `BusinessError(401, "原密码不正确")`
    - 成功后 `hash_password` + `user_repo.update_password` + **显式 `db.commit()`**
  - 本层**不 import `flask.session` / `flask.request`**，可脱离请求上下文直接调用

- [ ] **Step 1: 建包**

```bash
mkdir -p app/services
```

`app/services/__init__.py` 内容：

```python
"""业务逻辑层。

业务规则、编排、事务边界都在本层。刻意不引用 flask.session / flask.request，
因此脱离请求上下文也能直接调用测试（会话读写只在 api/ 层发生）。
"""
```

- [ ] **Step 2: 写验证脚本（先看它失败）**

存成 `app/services/_t_auth_service.py`（验证完删除）：

```python
# -*- coding: utf-8 -*-
"""auth_service.py 的临时验证脚本。需要真库、且已灌 seed.sql。

会临时改 stu001 的密码，末尾改回 xiyun@2026，可重复执行。
"""
from app.common.errors import BusinessError
from app.db import session_scope
from app.services import auth_service

OLD = "xiyun@2026"
TMP = "tmp-pass-2026"

with session_scope() as db:
    # 登录成功
    u = auth_service.login(db, "stu001", OLD)
    print("login stu001:", u.id, u.username, u.role)
    assert u.role == "student"

    # 失败分支：密码错 / 用户不存在 → 同一句文案
    msgs = []
    for uname, pw, want in [("stu001", "wrong-pw", 401), ("no-such-user", "x", 401)]:
        try:
            auth_service.login(db, uname, pw)
            raise AssertionError(f"{uname} 竟然登录成功")
        except BusinessError as e:
            assert e.code == want, (uname, e.code)
            msgs.append(e.message)
    assert msgs[0] == msgs[1] == "用户名或密码错误", msgs
    print("登录失败文案一致，不泄漏账号是否存在 ✓")

    # 停用账号 → 403（flush 出去再改回，本事务结束时落库的是 True）
    stu2 = auth_service.login(db, "stu002", OLD)
    stu2.is_active = False
    db.flush()
    try:
        auth_service.login(db, "stu002", OLD)
        raise AssertionError("停用账号竟然登录成功")
    except BusinessError as e:
        assert e.code == 403 and e.message == "账号已停用", (e.code, e.message)
    print("停用账号 → 403 账号已停用 ✓")
    stu2.is_active = True
    db.flush()

    # get_user
    assert auth_service.get_user(db, u.id).username == "stu001"
    try:
        auth_service.get_user(db, 999999)
        raise AssertionError("不存在的 user_id 竟然没报错")
    except BusinessError as e:
        assert e.code == 401 and e.message == "登录状态已失效", (e.code, e.message)
    print("get_user 不存在 → 401 登录状态已失效 ✓")

    # change_password：原密码错
    try:
        auth_service.change_password(db, u, "wrong-pw", "newpass123")
        raise AssertionError("原密码错竟然改密成功")
    except BusinessError as e:
        assert e.code == 401 and e.message == "原密码不正确", (e.code, e.message)
    print("change_password 原密码错 → 401 原密码不正确 ✓")

    # change_password：成功 → 新密码可登录 → 改回
    auth_service.change_password(db, u, OLD, TMP)
    assert auth_service.login(db, "stu001", TMP).id == u.id
    print("改密后新密码可登录 ✓")
    auth_service.change_password(db, u, TMP, OLD)
    assert auth_service.login(db, "stu001", OLD).id == u.id
    print("已改回原密码 ✓")

print("OK")
```

- [ ] **Step 3: 跑它，确认失败**

```bash
.venv/bin/python -m app.services._t_auth_service
```

Expected: `ModuleNotFoundError: No module named 'app.services.auth_service'`

- [ ] **Step 4: 写 `app/services/auth_service.py`**

```python
# -*- coding: utf-8 -*-
"""A 组认证接口的业务逻辑。

本层不引用 flask.session / flask.request——会话读写只在 api/ 层发生，
所以这里的函数脱离请求上下文也能直接调用测试。

事务边界在本层：写操作显式 commit（理由见 CLAUDE.md）。
仓储层只 flush，提交失败要在这里冒泡，不能在响应发出后才炸。
"""

from sqlalchemy.orm import Session

from app.common.errors import BusinessError
from app.common.security import hash_password, verify_password
from app.models.user import User
from app.repositories import user_repo


def login(db: Session, username: str, password: str) -> User:
    """校验用户名密码，返回用户。

    用户不存在与密码错误返回同一句文案，不泄漏账号是否存在。
    """
    user = user_repo.get_by_username(db, username)
    if user is None or not verify_password(user.password_hash, password):
        raise BusinessError(401, "用户名或密码错误")
    if not user.is_active:
        raise BusinessError(403, "账号已停用")
    return user


def get_user(db: Session, user_id: int) -> User:
    """按 id 取用户，供 A3/A4 从会话里的 user_id 反查。

    查不到说明账号已被删——对前端而言等价于登录失效。
    """
    user = user_repo.get_by_id(db, user_id)
    if user is None:
        raise BusinessError(401, "登录状态已失效")
    return user


def change_password(db: Session, user: User, old: str, new: str) -> None:
    """改密码。先验原密码，成功后写库并提交。"""
    if not verify_password(user.password_hash, old):
        raise BusinessError(401, "原密码不正确")
    user_repo.update_password(db, user, hash_password(new))
    db.commit()
```

- [ ] **Step 5: 再跑，应当全绿**

```bash
.venv/bin/python -m app.services._t_auth_service
```

Expected:
```
login stu001: 2 stu001 student
登录失败文案一致，不泄漏账号是否存在 ✓
停用账号 → 403 账号已停用 ✓
get_user 不存在 → 401 登录状态已失效 ✓
change_password 原密码错 → 401 原密码不正确 ✓
改密后新密码可登录 ✓
已改回原密码 ✓
OK
```

- [ ] **Step 6: 确认没有反向依赖与禁止的 import**

```bash
grep -nE 'flask|import' app/services/auth_service.py
```

Expected: import 只有 `sqlalchemy.orm.Session` / `app.common.errors` / `app.common.security` / `app.models.user` / `app.repositories`；**没有** `flask`、**没有** `app.api`。

- [ ] **Step 7: 删临时脚本**

```bash
rm app/services/_t_auth_service.py
ls app/services/
```

Expected: `__init__.py  __pycache__  auth_service.py`

- [ ] **Step 8: 检查点 —— 停下，交给协调者审查**

**本任务不执行任何 git 命令**（本项目不用 git 管理）。停在这里，把两样东西汇报给协调者，等审查通过后再开始下一个任务：

1. 本任务新增/修改的文件清单（用 `ls` 或 `find` 列，不要用 `git status`）
2. 上一步验证命令的完整输出

协调者审查通过后，直接进入下一个任务；被退回则改完重跑验证再汇报。

---

## Task 8: `API_PREFIX` 提取 + `create_app()` 装配点

**Files:**
- Modify: `app/api/__init__.py`（重写）
- Modify: `app/__init__.py`（重写，当前只有一句 docstring）
- 使用: `app/config.py`（Task 1）、`app/common/errors.py`（Task 2）、`app/db.py::init_app`

**Interfaces:**
- Consumes: `settings.secret_key`、`settings.session_cookie_secure`、`register_error_handlers(app)`、`init_app(app)`
- Produces:
  - `API_PREFIX = "/api"`（Task 10 的 `demo_bp` 引用）
  - `api_bp`（Task 9 挂路由、Task 8 的 create_app 注册）
  - `create_app(config_overrides: dict | None = None) -> Flask`（Task 9/10 的入口）
  - 该 app 的 JSON 不再转义中文（`app.json.ensure_ascii is False`）
  - 四个错误 handler 已注册（未匹配 URL 返回 JSON 404）

- [ ] **Step 1: 写验证脚本（先看它失败）**

存成 `_t_create_app.py`（项目根目录，验证完删除）：

```python
# -*- coding: utf-8 -*-
"""create_app() 的临时验证脚本（此阶段 A 组路由还没挂上）。"""
from app import create_app
from app.api import API_PREFIX

app = create_app()
c = app.test_client()

assert API_PREFIX == "/api"

# 配置
assert app.secret_key is not None and len(app.secret_key) == 64
assert app.config["PERMANENT_SESSION_LIFETIME"].days == 7
assert app.config["SESSION_COOKIE_HTTPONLY"] is True
assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
assert app.config["SESSION_COOKIE_SECURE"] is False
print("配置 ✓  会话有效期:", app.config["PERMANENT_SESSION_LIFETIME"])

# 中文不转义（Flask 3.x 已移除 JSON_AS_ASCII，只能走 app.json）
assert app.json.ensure_ascii is False
print("ensure_ascii ✓")

# 错误 handler 已注册：未匹配的 /api/* 是 JSON 404，不是 Werkzeug 的 HTML 页
r = c.get("/api/nope")
print("GET /api/nope ->", r.status_code, r.get_data(as_text=True))
assert r.status_code == 404
assert r.is_json and r.get_json()["code"] == 404
assert r.get_json()["message"] == "接口不存在"

# ── 下面三行 Task 8 阶段先注释掉，Task 9 挂上 auth.py 后再恢复 ──
# 本任务只装管线，`/api/auth/login` 还不存在，此时 GET 它得到的是 404 而非 405。
# Task 9 的 Step 6 会把这三行恢复并重跑本脚本。
#
# r = c.get("/api/auth/login")
# assert r.status_code == 405, r.status_code
# assert r.is_json and r.get_json()["code"] == 405, r.get_data(as_text=True)
# print("GET /api/auth/login -> 405 JSON ✓（说明 api/auth.py 已挂上）")

# config_overrides 生效（测试用）
app2 = create_app({"TESTING": True, "SECRET_KEY": "override"})
assert app2.config["TESTING"] is True and app2.secret_key == "override"
print("config_overrides ✓")

# 每次调用产出互不相同的 app 实例
assert create_app() is not app
print("OK")
```

- [ ] **Step 2: 跑它，确认失败**

```bash
.venv/bin/python _t_create_app.py
```

Expected: `ImportError: cannot import name 'create_app' from 'app'`

- [ ] **Step 3: 改 `app/api/__init__.py`**

```python
"""`/api` 蓝图——全项目接口前缀的唯一来源。

《5-接口清单-V1.0》第 1 节定的 Base URL 是 `/api`。这个前缀只在下面
`API_PREFIX` 这一处写死：业务路由一律写不带前缀的相对路径
（`@api_bp.route("/demos")`），将来要加要改（比如上 `/api/v2`）都只动本文件。

Flask 没有 Spring Boot 的 `server.servlet.context-path` 那样的全局配置项，
蓝图 `url_prefix` 就是它的等价物——但作用范围是挂在蓝图上的路由，不是整个 app。
所以留在 Flask 实例上的路由（如 `app-d.py` 的根路由 `/`）不受这里影响。

演示路由（`app-d.py` 的上传/分析）刻意**不**挂在本蓝图上：它们在
`create_app()` 之后才定义，而 Flask 规定 `register_blueprint()` 之后不能再往
该蓝图加路由（会抛 AssertionError）。它们改用同样读 `API_PREFIX` 的独立
`demo_bp`，详见 app-d.py 里的说明。
"""

from flask import Blueprint

API_PREFIX = "/api"

api_bp = Blueprint("api", __name__, url_prefix=API_PREFIX)

# ↓↓↓ 注册清单 ↓↓↓
# 每新增一个接口模块都必须在此加一行 import，否则它的路由不会生效
# （Blueprint.route 只是把注册动作记进 deferred_functions，模块不被 import
# 就没人执行它）。与 app/models/__init__.py 的约定同构。
#
# import 必须放在 api_bp 定义之后：各子模块要 `from app.api import api_bp`
# 才能挂路由，放前面会循环导入。
```

（此时还没有子模块可 import——`from . import auth` 这行由 Task 9 加上。）

- [ ] **Step 4: 改写 `app/__init__.py`**

```python
"""戏韵AI 后端应用包。

create_app() 是应用的唯一装配点：配置 → 数据库 teardown → 错误处理 → 蓝图。
脚本、测试、celery 都从这里取 app，不要再各自 new 一个 Flask()。
"""

from datetime import timedelta

from flask import Flask

from app.common.errors import register_error_handlers
from app.config import settings
from app.db import init_app


def create_app(config_overrides=None):
    """装配并返回 Flask 应用。

    config_overrides 供测试覆盖配置（如 {"TESTING": True}），生产不传。
    """
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=settings.secret_key,
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),   # 《6》第 3 节：会话 7 天
        SESSION_COOKIE_HTTPONLY=True,                   # 《6》第 3 节：HttpOnly
        SESSION_COOKIE_SAMESITE="Lax",                  # 《6》第 3 节：SameSite=Lax
        SESSION_COOKIE_SECURE=settings.session_cookie_secure,
    )
    if config_overrides:
        app.config.update(config_overrides)

    # Flask 3.x 已移除 JSON_AS_ASCII 配置项，改在这里设。不设的话返回的中文
    # 全是 \uXXXX 转义，虽然前端 JSON.parse 后能正确显示，但抓包与日志都没法读。
    app.json.ensure_ascii = False

    init_app(app)                  # 请求结束关闭数据库会话，与 get_db() 配对
    register_error_handlers(app)

    # import 必须在 register_blueprint 之前：这行会触发 app/api/__init__.py
    # 末尾的注册清单（`from . import auth`），业务路由到那时才挂到 api_bp 上。
    # 若先 register 再 import，注册时蓝图里还是空的，所有路由静默失效。
    from app.api import api_bp

    app.register_blueprint(api_bp)
    return app
```

- [ ] **Step 5: 再跑，应当全绿**

```bash
.venv/bin/python _t_create_app.py
```

Expected:
```
配置 ✓  会话有效期: 7 days, 0:00:00
ensure_ascii ✓
GET /api/nope -> 404 {"code":404,"data":null,"message":"接口不存在"}
config_overrides ✓
OK
```

（`/api/auth/login` 那三行断言在本任务里是注释掉的——路由由 Task 9 挂上，届时恢复。）

- [ ] **Step 6: 确认没有误伤既有功能**

```bash
.venv/bin/python scripts/check_db.py
```

Expected: 末行 `结果：全部一致 ✓`

- [ ] **Step 7: 删临时脚本（Task 9 需要它，可留到 Task 9 结束后再删）**

```bash
# 本步先不删，Task 9 的 Step 6 会用到
```

- [ ] **Step 8: 检查点 —— 停下，交给协调者审查**

**本任务不执行任何 git 命令**（本项目不用 git 管理）。停在这里，把两样东西汇报给协调者，等审查通过后再开始下一个任务：

1. 本任务新增/修改的文件清单（用 `ls` 或 `find` 列，不要用 `git status`）
2. 上一步验证命令的完整输出

协调者审查通过后，直接进入下一个任务；被退回则改完重跑验证再汇报。

---

## Task 9: `app/api/auth.py` —— A1–A4 路由

**Files:**
- Create: `app/api/auth.py`
- Modify: `app/api/__init__.py`（在注册清单处加一行）
- 使用: 前八个任务的全部产物

**Interfaces:**
- Consumes: `api_bp`、`API_PREFIX`、`login_required`、`teacher_required`、`current_user_id`、`BusinessError`、`get_db`、`ok`、`LoginIn`、`PasswordChangeIn`、`UserOut`、`auth_service.login/get_user/change_password`、`create_app`
- Produces（4 条路由，前缀由 `api_bp` 带出）:
  - `POST /api/auth/login` 公开 → `ok(UserOut.model_dump())`，写 `session["user_id"]` / `session["role"]` / `session.permanent = True`
  - `POST /api/auth/logout` 登录 → `session.clear()`，`ok(None)`
  - `GET  /api/auth/me` 登录 → `ok(UserOut.model_dump())`
  - `POST /api/auth/password` 登录 → 成功后 `session.clear()`，`ok(None)`
  - endpoint 名分别为 `api.login` / `api.logout` / `api.me` / `api.change_password`

- [ ] **Step 1: 写端到端验证脚本（先看它失败）**

存成 `_t_auth_api.py`（项目根目录，验证完删除）：

```python
# -*- coding: utf-8 -*-
"""A1–A4 的端到端验证（Flask 测试客户端，无需起服务器）。

会临时改 stu001 的密码，末尾改回 xiyun@2026，可重复执行。
需要真库、且已灌 seed.sql。
"""
from app import create_app

OLD = "xiyun@2026"
TMP = "tmp-pass-2026"

app = create_app()
c = app.test_client()

print("== /api 下的路由表 ==")
for r in sorted(app.url_map.iter_rules(), key=lambda x: str(x)):
    if str(r).startswith("/api"):
        print("  %-28s %s" % (str(r), sorted(r.methods - {"HEAD", "OPTIONS"})))
print()

# ── 未登录基线 ────────────────────────────────────────────
r = c.get("/api/auth/me")
print("未登录 A3 ->", r.status_code, r.get_data(as_text=True))
assert r.status_code == 401 and r.get_json()["message"] == "未登录"

# 中文不转义：正文里应出现字面「未登录」而不是 未登录
raw = r.get_data(as_text=True)
assert "未登录" in raw and "\\u" not in raw, raw
print("中文未被转义成 \\uXXXX ✓")

# ── A1 参数错误 ──────────────────────────────────────────
r = c.post("/api/auth/login", json={})
assert r.status_code == 422, r.get_data(as_text=True)
assert "username: 必填" in r.get_json()["message"], r.get_json()
print("空 body -> 422", r.get_json()["message"])

r = c.post("/api/auth/login", json={"username": "a" * 51, "password": "x"})
assert r.status_code == 422, r.get_data(as_text=True)
assert "长度不能超过 50 个字符" in r.get_json()["message"], r.get_json()
print("username 超长 -> 422", r.get_json()["message"])

# ── A1 登录成功 ──────────────────────────────────────────
r = c.post("/api/auth/login", json={"username": "stu001", "password": OLD})
print("A1 stu001 ->", r.status_code, r.get_data(as_text=True))
assert r.status_code == 200, r.get_data(as_text=True)
b = r.get_json()
assert b["code"] == 0 and b["message"] == "ok"
assert set(b["data"]) == {"id", "username", "display_name", "role"}, b["data"]
assert b["data"]["username"] == "stu001"
assert b["data"]["display_name"] == "张三"
assert b["data"]["role"] == "student"
assert isinstance(b["data"]["id"], int)
assert "password" not in r.get_data(as_text=True)

ck = r.headers.get("Set-Cookie", "")
print("Set-Cookie:", ck)
assert "HttpOnly" in ck, ck
assert "SameSite=Lax" in ck, ck
# session.permanent = True 才会带 Expires；没有它说明写成了普通会话 cookie
assert "Expires=" in ck, "session.permanent 没生效：" + ck
print("Cookie 属性（HttpOnly / SameSite=Lax / Expires）✓")

# 教师账号
c2 = app.test_client()
r = c2.post("/api/auth/login", json={"username": "teacher01", "password": OLD})
assert r.status_code == 200 and r.get_json()["data"]["role"] == "teacher", r.get_data(as_text=True)
assert r.get_json()["data"]["display_name"] == "王老师"
print("A1 teacher01 -> role=teacher ✓")

# ── A1 失败：两种文案一致 ────────────────────────────────
c3 = app.test_client()
r1 = c3.post("/api/auth/login", json={"username": "stu001", "password": "wrong-pw"})
r2 = c3.post("/api/auth/login", json={"username": "no-such-user", "password": "wrong-pw"})
assert r1.status_code == r2.status_code == 401, (r1.status_code, r2.status_code)
assert r1.get_json()["message"] == r2.get_json()["message"] == "用户名或密码错误", r1.get_json()
print("密码错 / 用户不存在 文案一致 ✓:", r1.get_json()["message"])

# ── A3 已登录 ────────────────────────────────────────────
r = c.get("/api/auth/me")
print("A3 已登录 ->", r.status_code, r.get_data(as_text=True))
assert r.status_code == 200, r.get_data(as_text=True)
assert r.get_json()["data"]["username"] == "stu001"
raw = r.get_data(as_text=True)
assert "张三" in raw and "\\u" not in raw, raw
assert "password" not in raw

# ── A4 三种错误 ──────────────────────────────────────────
for payload, want_status, kw in [
    ({"old": "wrong-pw", "new": "newpass123"},  401, "原密码不正确"),
    ({"old": OLD, "new": "123"},                422, "长度不能少于 8 个字符"),
    ({"old": OLD, "new": OLD},                  422, "新密码不能与旧密码相同"),
]:
    r = c.post("/api/auth/password", json=payload)
    print(f"A4 {payload} -> {r.status_code} {r.get_json()['message']}")
    assert r.status_code == want_status, (payload, r.status_code, r.get_data(as_text=True))
    assert kw in r.get_json()["message"], r.get_json()

# ── A4 成功 → 会话立即失效 ───────────────────────────────
r = c.post("/api/auth/password", json={"old": OLD, "new": TMP})
print("A4 改密成功 ->", r.status_code, r.get_data(as_text=True))
assert r.status_code == 200, r.get_data(as_text=True)
assert r.get_json()["data"] is None, r.get_json()

r = c.get("/api/auth/me")
assert r.status_code == 401, "改密后旧会话没失效：" + r.get_data(as_text=True)
print("改密后旧会话立即失效 -> 401 ✓")

# ── 新密码登录 → 改回原密码 ──────────────────────────────
r = c.post("/api/auth/login", json={"username": "stu001", "password": TMP})
assert r.status_code == 200, r.get_data(as_text=True)
r = c.post("/api/auth/password", json={"old": TMP, "new": OLD})
assert r.status_code == 200, r.get_data(as_text=True)
print("用新密码登录并改回原密码 ✓")

# ── A2 登出 ──────────────────────────────────────────────
c.post("/api/auth/login", json={"username": "stu001", "password": OLD})
assert c.get("/api/auth/me").status_code == 200
r = c.post("/api/auth/logout")
print("A2 ->", r.status_code, r.get_data(as_text=True))
assert r.status_code == 200 and r.get_json()["data"] is None, r.get_data(as_text=True)
assert c.get("/api/auth/me").status_code == 401
print("A2 登出后 A3 -> 401 ✓")

# ── 404 是 JSON ──────────────────────────────────────────
c4 = app.test_client()
r = c4.get("/api/nope")
assert r.status_code == 404 and r.is_json and r.get_json()["code"] == 404
print("GET /api/nope -> 404 JSON ✓:", r.get_data(as_text=True))

print("OK")
```

- [ ] **Step 2: 跑它，确认失败**

```bash
.venv/bin/python _t_auth_api.py
```

Expected: 路由表里 `/api` 下只有 Task 8 的 `api_bp`（无 auth 路由），`GET /api/auth/me` 返回 404，第一条断言 `assert r.status_code == 401` 失败。

- [ ] **Step 3: 写 `app/api/auth.py`**

```python
# -*- coding: utf-8 -*-
"""A 组认证接口（《5-接口清单-V1.0》）。

    A1  POST /api/auth/login       公开
    A2  POST /api/auth/logout      登录
    A3  GET  /api/auth/me          登录
    A4  POST /api/auth/password    登录

本层只做三件事：校验入参 → 调 service → 组装响应。
不写 SQL、不写业务规则、不写 try/except（错误由 app/common/errors.py 的
全局 handler 兜）。

session 的读写**只在本文件发生**——service 层不碰 flask.session，
因此可以脱离请求上下文测试；「谁改了会话」全项目只有这一处。
"""

from flask import request, session

from app.api import api_bp
from app.common.decorators import current_user_id, login_required
from app.db import get_db
from app.response import ok
from app.schemas.auth import LoginIn, PasswordChangeIn, UserOut
from app.services import auth_service


def _payload() -> dict:
    """取 JSON 请求体。

    客户端没带 Content-Type: application/json 时 get_json() 会抛 415；
    silent=True 把它压成 None，这里再兜成 {}，让 pydantic 报「字段必填」
    而不是让 Flask 抛一个前端看不懂的 415。
    """
    return request.get_json(silent=True) or {}


@api_bp.route("/auth/login", methods=["POST"])
def login():
    """A1 登录（公开）。成功后写会话，返回 UserOut。"""
    data = LoginIn.model_validate(_payload())
    user = auth_service.login(get_db(), data.username, data.password)

    # permanent=True 才会用 PERMANENT_SESSION_LIFETIME（7 天），
    # 否则退出浏览器会话就没了。
    session.permanent = True
    session["user_id"] = user.id
    session["role"] = user.role

    return ok(UserOut.model_validate(user).model_dump())


@api_bp.route("/auth/logout", methods=["POST"])
@login_required
def logout():
    """A2 登出。"""
    session.clear()
    return ok(None)


@api_bp.route("/auth/me")
@login_required
def me():
    """A3 当前登录用户。"""
    user = auth_service.get_user(get_db(), current_user_id())
    return ok(UserOut.model_validate(user).model_dump())


@api_bp.route("/auth/password", methods=["POST"])
@login_required
def change_password():
    """A4 修改密码。成功后清会话，强制用新密码重新登录。"""
    data = PasswordChangeIn.model_validate(_payload())
    db = get_db()
    user = auth_service.get_user(db, current_user_id())
    auth_service.change_password(db, user, data.old, data.new)

    # 改密后原会话作废（DOC_ISSUES.md 第 11 条）
    session.clear()
    return ok(None)
```

- [ ] **Step 4: 把 auth 加进 `app/api/__init__.py` 的注册清单**

在文件末尾「注册清单」注释之后追加这一行：

```python
from . import auth  # noqa: E402,F401  ← 注册清单：新增模块在此加一行
```

- [ ] **Step 5: 再跑端到端脚本，应当全绿**

```bash
.venv/bin/python _t_auth_api.py
```

Expected（节选，id 视序列起点而定）：
```
== /api 下的路由表 ==
  /api/auth/login               ['POST']
  /api/auth/logout              ['POST']
  /api/auth/me                  ['GET']
  /api/auth/password            ['POST']

未登录 A3 -> 401 {"code":401,"data":null,"message":"未登录"}
中文未被转义成 \uXXXX ✓
空 body -> 422 username: 必填; password: 必填
username 超长 -> 422 username: 长度不能超过 50 个字符
A1 stu001 -> 200 {"code":0,"data":{"display_name":"张三","id":2,"role":"student","username":"stu001"},"message":"ok"}
...
OK
```

- [ ] **Step 6: 恢复 Task 8 里注释掉的三行断言并重跑**

把 `_t_create_app.py` 里 `GET /api/auth/login -> 405` 那三行的 `# ` 前缀去掉（连同上面那段说明注释一起删），然后：

```bash
.venv/bin/python _t_create_app.py
```

Expected:
```
配置 ✓  会话有效期: 7 days, 0:00:00
ensure_ascii ✓
GET /api/nope -> 404 {"code":404,"data":null,"message":"接口不存在"}
GET /api/auth/login -> 405 JSON ✓（说明 api/auth.py 已挂上）
config_overrides ✓
OK
```

- [ ] **Step 7: 确认注册清单确实生效（删掉那行会怎样）**

```bash
# 临时注释掉 app/api/__init__.py 末尾的 from . import auth，重跑应看到路由消失
.venv/bin/python - <<'PY'
import re, pathlib
p = pathlib.Path("app/api/__init__.py")
orig = p.read_text(encoding="utf-8")
p.write_text(orig.replace("from . import auth", "# from . import auth"), encoding="utf-8")
try:
    from app import create_app
    rules = [str(r) for r in create_app().url_map.iter_rules() if str(r).startswith("/api/auth")]
    print("注释掉注册清单后 /api/auth 下的路由:", rules)
    assert rules == [], "注册清单没起作用，路由不是靠它挂上的"
finally:
    p.write_text(orig, encoding="utf-8")
print("注册清单验证通过：不 import 就不生效 ✓")
PY
```

Expected: `注释掉注册清单后 /api/auth 下的路由: []` / `注册清单验证通过：不 import 就不生效 ✓`

- [ ] **Step 8: 删两个临时脚本**

```bash
rm -f _t_create_app.py _t_auth_api.py
ls _t_*.py 2>/dev/null || echo "OK：临时脚本已删净"
ls app/api/
```

Expected: `OK：临时脚本已删净`，且 `app/api/` 下只有 `__init__.py`、`__pycache__`、`auth.py`。

- [ ] **Step 9: 检查点 —— 停下，交给协调者审查**

**本任务不执行任何 git 命令**（本项目不用 git 管理）。停在这里，把两样东西汇报给协调者，等审查通过后再开始下一个任务：

1. 本任务新增/修改的文件清单（用 `ls` 或 `find` 列，不要用 `git status`）
2. 上一步验证命令的完整输出

协调者审查通过后，直接进入下一个任务；被退回则改完重跑验证再汇报。

---

## Task 10: `app-d.py` 改造 —— `create_app()` + `demo_bp`

**Files:**
- Modify: `app-d.py`
  - 顶部 import 与 app 创建（约 12–37 行）
  - **删除用户手写的临时 `login()` 路由（约 224–245 行）**——它占用 `/api/auth/login`，Task 9 的真实实现挂上后会因 endpoint 重名冲突
  - 4 条演示路由的装饰器换成 `@demo_bp.route`
  - `${API}/api/audio/...` 的 `url_for` endpoint 名改 `demo.audio`
  - 文件末尾的 `app.register_blueprint(api_bp)` 换成 `demo_bp` 的注册
- **不动**: 全部 librosa 分析代码（`smooth_series` / `detect_voice_onset` / `extract_pitch` / `hz_to_cents`）、进度存储、4 条路由的函数体

**Interfaces:**
- Consumes: `create_app()`、`API_PREFIX`、`get_db()`、`ok()`
- Produces: 一个由 `create_app()` 装配、另挂 `demo_bp` 的 Flask 应用，监听 8877
  - 演示路由 endpoint 变为 `demo.upload` / `demo.audio` / `demo.get_progress` / `demo.analyze`
  - 根路由 `/` 仍是 `index`，挂在 Flask 实例上（不进任何蓝图）

- [ ] **Step 1: 改 import 段（原 12–29 行）**

把

```python
from flask import Flask, request, jsonify, send_from_directory, url_for
```

改为

```python
from flask import Blueprint, request, jsonify, send_from_directory, url_for
```

（`Flask` 不再直接用——实例由 `create_app()` 产出。）

把

```python
from app.db import get_db, init_app
from app.models.user import User
from app.response import ok
# /api 蓝图：接口前缀只在 app/api/__init__.py 里定义一次，本文件的接口路由
# 全部挂到它上面。注册动作在文件末尾、路由定义之后（原因见那里的注释）。
from app.api import api_bp

app = Flask(__name__)
CORS(app)

# ⚠️ 必须调用 init_app(app)：...(原有 5 行注释保留)
init_app(app)
```

改为

```python
from app import create_app
from app.api import API_PREFIX
from app.db import get_db
from app.models.user import User
from app.response import ok

# ===== 应用装配 =====
# create_app() 负责配置、数据库 teardown、错误 handler、api 蓝图（见 app/__init__.py）。
# init_app(app) 不必再手写——create_app() 里已经调过。
app = create_app()

# pitch_comparison.html 从 file:// 打开时对后端的请求是跨源请求，CORS 必须保留，
# 删了音准对比演示当场失效。
CORS(app)

# ===== 演示蓝图 =====
# 下面 4 条路由（上传/音频/进度/分析）是过渡物，B1–B5 真正实现后连同本文件的
# librosa 代码整块删除。它们必须挂在自己的 demo_bp 上，不能挂 api_bp：
# api_bp 在 create_app() 里就已经注册了，而 Flask 规定 register_blueprint()
# 之后不能再往该蓝图加路由（会抛 AssertionError）。另起一个蓝图后，
# 「先定义路由、再注册」的约束变成局部的——注册紧跟自己的路由定义，
# 不必追溯到远处的 create_app()。
#
# 前缀复用同一个 API_PREFIX 常量，不写字面量。
demo_bp = Blueprint("demo", __name__, url_prefix=API_PREFIX)
```

- [ ] **Step 2: 删除用户手写的临时 login 路由**

整段删掉（原 224–245 行）：

```python
@api_bp.route("/auth/login",methods=["POST"])
def login():
    # 表单
    # username = request.form.get("username")
    # password = request.form.get("password")

    # json
    # data = request.get_json();
    # username = data.get("username")
    # password = data.get("password")

    # jsonArray
    datalist = request.get_json();
    return ok(
        [
            {
                "username": data["username"],
                "password": data["password"]
            }
            for data in datalist
        ]
    )
```

**为什么必须删**：`/api/auth/login` 的真实实现在 `app/api/auth.py`，endpoint 名是 `api.login`。这条临时路由也挂在 `api_bp` 上、函数名也是 `login`，两条路由的同名 endpoint 会让 `register_blueprint` 抛 `AssertionError: View function mapping is overwriting an existing endpoint function`。

- [ ] **Step 3: 4 条演示路由改挂 `demo_bp`**

| 原装饰器 | 改为 |
|---|---|
| `@api_bp.route("/upload", methods=["POST"])` | `@demo_bp.route("/upload", methods=["POST"])` |
| `@api_bp.route("/audio/<path:filename>")` | `@demo_bp.route("/audio/<path:filename>")` |
| `@api_bp.route("/progress")` | `@demo_bp.route("/progress")` |
| `@api_bp.route("/analyze")` | `@demo_bp.route("/analyze")` |

`upload()` 函数体里这行也要改：

```python
        return jsonify({"id": uid, "url": url_for("api.audio", filename=uid)})
```

改为

```python
        return jsonify({"id": uid, "url": url_for("demo.audio", filename=uid)})
```

（`audio` 视图现在属于 `demo` 蓝图，`url_for("api.audio", ...)` 会抛 `BuildError`。前缀仍由 `url_prefix` 带出来，所以返回的 URL 依旧是 `/api/audio/xxx`，`pitch_comparison.html` 的 `${API}${j.url}` 不受影响。）

- [ ] **Step 4: 改文件末尾的注册与注释**

把原 472–478 行

```python
# 蓝图必须在上面所有 @api_bp.route 之后再注册。
# ...
app.register_blueprint(api_bp)
```

改为

```python
# demo_bp 必须在上面所有 @demo_bp.route 之后再注册。
# Blueprint.route() 并不当场注册路由，只是把注册动作记进 deferred_functions，
# 等 register_blueprint() 时才真正执行。反过来写（先注册、后定义路由）
# 会当场抛 AssertionError（Flask 3.1.3 实测）：
#   "The setup method 'route' can no longer be called on the blueprint 'demo'"
# 紧跟自己的路由定义放，是为了让这个顺序局部可见。
app.register_blueprint(demo_bp)
```

- [ ] **Step 5: 静态检查——确认没有残留的 `api_bp` 引用**

```bash
# 只查代码行，排除注释：Step 1 的注释块会正当提及 api_bp / init_app 来解释设计
# 取舍（「为什么另起 demo_bp 而不是挂 api_bp」），那些是说明文字不是残留引用。
grep -n 'api_bp\|Flask(__name__)\|init_app' app-d.py | grep -v ':[[:space:]]*#' || echo "OK：无残留"
grep -n 'demo_bp\|create_app\|Blueprint' app-d.py
```

Expected: 第一条无输出（`app-d.py` 的**代码**里不再出现 `api_bp`、`Flask(__name__)`、`init_app`）；第二条列出 `create_app()`、`Blueprint(...)`、5 处 `demo_bp`（1 处定义 + 4 处装饰器）与 1 处 `register_blueprint(demo_bp)`。

- [ ] **Step 6: 起后端做端到端验证**

```bash
# 先清端口：app-d.py 里 debug=True 会开 Werkzeug 的 reloader，
# 父进程被杀后子进程可能仍在监听 8877，下一个任务就会对着旧代码测。
lsof -ti:8877 | xargs kill 2>/dev/null; sleep 1

.venv/bin/python app-d.py > /tmp/appd.log 2>&1 &
APP_PID=$!
for i in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:8877/ && break; sleep 0.5; done

echo "--- 根路由（数据库接入示例）---"
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8877/
curl -s http://127.0.0.1:8877/ | head -c 200; echo

echo "--- 演示路由 ---"
curl -s -o /dev/null -w '/api/progress -> %{http_code}\n' 'http://127.0.0.1:8877/api/progress?job=x'
curl -s -o /dev/null -w '/api/analyze  -> %{http_code}\n' 'http://127.0.0.1:8877/api/analyze'
curl -s -o /dev/null -w '/api/audio/x  -> %{http_code}\n' 'http://127.0.0.1:8877/api/audio/nope.wav'

echo "--- 旧路径应已 404 ---"
curl -s -o /dev/null -w '/upload -> %{http_code}\n' -X POST http://127.0.0.1:8877/upload

echo "--- A1 真实实现（证明 create_app 装配生效）---"
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"username":"teacher01","password":"xiyun@2026"}' \
  http://127.0.0.1:8877/api/auth/login; echo

echo "--- 临时路由已删：发 JSON 数组应得 422 而不是回显 ---"
curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'Content-Type: application/json' \
  -d '[{"username":"a","password":"b"}]' http://127.0.0.1:8877/api/auth/login

echo "--- 未匹配路由应是 JSON 404 ---"
curl -s http://127.0.0.1:8877/api/nope; echo

kill $APP_PID 2>/dev/null
lsof -ti:8877 | xargs kill 2>/dev/null
```

Expected:
```
--- 根路由（数据库接入示例）---
200
{"code":0,"data":[{"display_name":"王老师","id":1,"role":"teacher","username":"teacher01"}],"message":"ok"}
（若开启了调试美化输出，字段间会有换行与缩进，属正常）
--- 演示路由 ---
/api/progress -> 200
/api/analyze  -> 400
/api/audio/x  -> 404
--- 旧路径应已 404 ---
/upload -> 404
--- A1 真实实现（证明 create_app 装配生效）---
{"code":0,"data":{"display_name":"王老师","id":1,"role":"teacher","username":"teacher01"},"message":"ok"}
--- 临时路由已删：发 JSON 数组应得 422 而不是回显 ---
422
--- 未匹配路由应是 JSON 404 ---
{"code":404,"data":null,"message":"接口不存在"}
```

中文没有出现 `\uXXXX` 转义也是这一步骤的检查点之一。

- [ ] **Step 7: 确认库与模型仍然一致**

```bash
.venv/bin/python scripts/check_db.py
```

Expected: 末行 `结果：全部一致 ✓`

- [ ] **Step 8: 检查点 —— 停下，交给协调者审查**

**本任务不执行任何 git 命令**（本项目不用 git 管理）。停在这里，把两样东西汇报给协调者，等审查通过后再开始下一个任务：

1. 本任务新增/修改的文件清单（用 `ls` 或 `find` 列，不要用 `git status`）
2. 上一步验证命令的完整输出

协调者审查通过后，直接进入下一个任务；被退回则改完重跑验证再汇报。

---

## Task 11: `scripts/smoke_auth.sh` —— A 组冒烟测试

**Files:**
- Create: `scripts/smoke_auth.sh`
- 风格对齐: `scripts/check_db.py`（退出码闸门，可直接接进 CI）

**Interfaces:**
- Consumes: 运行中的后端（默认 `http://127.0.0.1:8877`，可用 `BASE` 环境变量覆盖）、真库与 `seed.sql` 的种子账号（`teacher01` / `stu001` / `stu002`，初始密码均为 `xiyun@2026`）
- Produces: 全部场景通过时退出码 0，任一失败退出码 1
  - 会真实修改 `stu002` 的密码，末尾改回 `xiyun@2026`，可重复执行
  - **不依赖 jq**（本机未安装）——JSON 解析交给 `python3` 标准库

- [ ] **Step 1: 写脚本**

```bash
#!/usr/bin/env bash
# 戏韵AI — A 组认证接口冒烟测试（《5-接口清单-V1.0》A1–A4）
#
# 用法（在项目根目录执行）：
#     scripts/smoke_auth.sh                              # 直连后端 8877
#     BASE=http://127.0.0.1:80 scripts/smoke_auth.sh     # 经 nginx（顺带验证反代）
#
# 前置：后端已启动、数据库已灌 seed.sql。
#     .venv/bin/python app-d.py &
#
# 不依赖 jq（本机没装）：JSON 解析交给 python3 标准库。
# 任一场景不符即打印明细并以退出码 1 结束，风格同 scripts/check_db.py，可接进 CI。
#
# ⚠️ 会真实修改 stu002 的密码，脚本末尾改回 xiyun@2026，因此可重复执行。
set -u

BASE="${BASE:-http://127.0.0.1:8877}"
PY="${PY:-python3}"
OLD_PW="xiyun@2026"
NEW_PW="xiyun@2026-tmp"
# stu002 密码是否停在临时值：0=原密码，1=已改密尚未改回。
# 改密成功那一刻置 1、改回成功后清零；供下方 EXIT trap（cleanup）判断是否要兜底改回。
PW_DIRTY=0

TD="$(mktemp -d)"

# —— EXIT trap：清临时目录 + 兜底恢复 stu002 密码 ——
# 为什么需要它：脚本在「改密成功(186)→改回原密码(197)」这段约 4 个请求的窗口里，
# 一旦连接失败，req() 的 exit 1 会立即终止，把 stu002 密码留在临时值 $NEW_PW；
# 下次运行 Step 2 用 $OLD_PW 登录会 401，「改密成功」也因 old 与实际不符而失败，
# 恢复不再自愈——直接违反脚本「可重复执行」的承诺，故必须在此兜底。
# 断言失败不会走到这里（脚本无 set -e，断言只累计 FAIL 并跑完恢复）；只有 req()
# 的致命 exit 1 与外部中断会触发。若不写这段，后人会误以为它只是清个临时目录。
restore_password() {
  # 兜底恢复：把 stu002 密码从 $NEW_PW 改回 $OLD_PW。
  # 刻意不用 req()——req() 失败会 exit 1，在 EXIT trap 里再 exit 会吞掉脚本原本的
  # 退出码（还可能递归）；这里用裸 curl，失败只打印手动恢复提示、绝不改动退出码。
  local jar="$TD/restore.jar" s_login s_pw
  s_login=$(curl -s -o /dev/null -w '%{http_code}' \
    -c "$jar" -b "$jar" \
    -X POST -H 'Content-Type: application/json' \
    -d "{\"username\":\"stu002\",\"password\":\"$NEW_PW\"}" \
    "$BASE/api/auth/login")
  if [ "$s_login" = "200" ]; then
    s_pw=$(curl -s -o /dev/null -w '%{http_code}' \
      -c "$jar" -b "$jar" \
      -X POST -H 'Content-Type: application/json' \
      -d "{\"old\":\"$NEW_PW\",\"new\":\"$OLD_PW\"}" \
      "$BASE/api/auth/password")
    if [ "$s_pw" = "200" ]; then
      PW_DIRTY=0
      echo "$(green "已自动把 stu002 密码改回 $OLD_PW")"
      return 0
    fi
  fi
  echo "$(red "未能自动改回 stu002 密码")，请手动恢复（任选其一）：" >&2
  echo "  curl -c /tmp/c.jar -X POST -H 'Content-Type: application/json' -d '{\"username\":\"stu002\",\"password\":\"$NEW_PW\"}' $BASE/api/auth/login" >&2
  echo "  curl -b /tmp/c.jar -c /tmp/c.jar -X POST -H 'Content-Type: application/json' -d '{\"old\":\"$NEW_PW\",\"new\":\"$OLD_PW\"}' $BASE/api/auth/password" >&2
  echo "  SQL：UPDATE users SET password_hash='<seed.sql 中 stu002 的 pbkdf2 值>' WHERE username='stu002';" >&2
}

cleanup() {
  local rc=$?
  if [ "$PW_DIRTY" -eq 1 ]; then
    restore_password
  fi
  rm -rf "$TD"
  # 原样还回脚本原本的退出码：成功仍 0、失败仍 1、中断仍 130。
  exit "$rc"
}
trap cleanup EXIT

JAR_T="$TD/teacher.jar"     # teacher01 的 cookie
JAR_S="$TD/student.jar"     # stu002 的 cookie
JAR="$JAR_T"
HDR="$TD/last.headers"
BODY_FILE="$TD/last.body"

PASS=0
FAIL=0
STATUS=""
BODY=""
BODY_N=""                   # 去掉空格与换行的正文，使断言不受 Flask 是否美化输出影响

red()   { printf '\033[31m%s\033[0m' "$1"; }
green() { printf '\033[32m%s\033[0m' "$1"; }
ok()    { PASS=$((PASS + 1)); printf '  %s %s\n' "$(green ✓)" "$1"; }
bad()   { FAIL=$((FAIL + 1)); printf '  %s %s —— %s\n' "$(red ✗)" "$1" "$2"; }

# 发一次请求：结果存进 STATUS / BODY，响应头写 $HDR，cookie 走 $JAR 读写
req() {
  STATUS=$(curl -s -D "$HDR" -o "$BODY_FILE" -c "$JAR" -b "$JAR" -w '%{http_code}' "$@")
  BODY=$(cat "$BODY_FILE")
  BODY_N=$(printf '%s' "$BODY" | tr -d ' \n\t')
  if [ "$STATUS" = "000" ]; then
    echo "$(red "无法连接 $BASE") —— 后端没起？先执行：.venv/bin/python app-d.py" >&2
    exit 1
  fi
}

# 从 JSON 正文按点号路径取值（如 a.b.0.c），取不到返回空串。替代 jq。
jget() {
  printf '%s' "$BODY" | "$PY" -c '
import json, sys
try:
    cur = json.load(sys.stdin)
    for k in sys.argv[1].split("."):
        cur = cur[int(k)] if isinstance(cur, list) else cur[k]
except Exception:
    cur = ""
print(cur if cur is not None else "")
' "$1"
}

expect_status() {   # expect_status <名称> <期望 HTTP 状态码>
  if [ "$STATUS" = "$2" ]; then ok "$1"; else bad "$1" "期望 HTTP ${2}，实际 ${STATUS}；body=$BODY"; fi
}

expect_code() {     # expect_code <名称> <期望 code 字段>
  local got
  got=$(jget code)
  if [ "$got" = "$2" ]; then ok "$1"; else bad "$1" "期望 code=${2}，实际 code=${got}；body=$BODY"; fi
}

expect_in() {       # expect_in <名称> <子串> [body|header]
  local hay needle
  needle=$(printf '%s' "$2" | tr -d ' \n\t')
  if [ "${3:-body}" = "header" ]; then hay=$(tr -d ' ' < "$HDR"); else hay="$BODY_N"; fi
  case "$hay" in
    *"$needle"*) ok "$1" ;;
    *) bad "$1" "找不到「$2」；实际=$hay" ;;
  esac
}

expect_not_in() {   # expect_not_in <名称> <子串>
  case "$BODY_N" in
    *"$2"*) bad "$1" "不该出现「$2」；body=$BODY" ;;
    *) ok "$1" ;;
  esac
}

post_json() {       # post_json <路径> <JSON 字符串>
  req -X POST -H 'Content-Type: application/json' -d "$2" "$BASE$1"
}

echo "冒烟目标：$BASE"
echo

echo "── 1. 未登录基线 ──────────────────────────────"
JAR="$JAR_T"
req "$BASE/api/auth/me"
expect_status "A3 未登录 → 401" 401
expect_code   "A3 未登录 code=401" 401
expect_in     "A3 未登录文案为中文（且未被转义）" "未登录"

req "$BASE/api/nope"
expect_status "未匹配路由 → 404" 404
expect_in     "404 是 JSON 而非 Werkzeug 的 HTML 页" '"code":404'
expect_in     "404 文案为中文" "接口不存在"

echo
echo "── 2. A1 登录 ─────────────────────────────────"
post_json "/api/auth/login" '{"username":"teacher01","password":"xiyun@2026"}'
expect_status "A1 teacher01 登录 → 200" 200
expect_code   "A1 code=0" 0
expect_in     "A1 role=teacher" '"role":"teacher"'
expect_in     "A1 display_name 为中文且未转义" "王老师"
expect_not_in "A1 响应不含 password" "password"
expect_in     "Cookie 带 HttpOnly" "HttpOnly" header
expect_in     "Cookie 带 SameSite=Lax" "SameSite=Lax" header
expect_in     "Cookie 带 Expires（会话 7 天）" "Expires=" header

JAR="$JAR_S"
post_json "/api/auth/login" '{"username":"stu002","password":"xiyun@2026"}'
expect_status "A1 stu002 登录 → 200" 200
expect_in     "A1 stu002 role=student" '"role":"student"'

echo
echo "── 3. A1 失败分支 ─────────────────────────────"
post_json "/api/auth/login" '{}'
expect_status "空 body → 422" 422
expect_code   "空 body code=422" 422
expect_in     "报错点名了字段且中文化" "username: 必填"

post_json "/api/auth/login" \
  '{"username":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","password":"x"}'
expect_status "username 超 50 字符 → 422" 422
expect_in     "长度报错中文化" "长度不能超过 50 个字符"

post_json "/api/auth/login" '{"username":"stu001","password":"wrong-password"}'
expect_status "密码错 → 401" 401
MSG_WRONG_PW=$(jget message)
post_json "/api/auth/login" '{"username":"no-such-user","password":"wrong-password"}'
expect_status "用户不存在 → 401" 401
if [ "$(jget message)" = "$MSG_WRONG_PW" ]; then
  ok "两种失败文案一致，不泄漏账号是否存在（${MSG_WRONG_PW}）"
else
  bad "两种失败文案应一致" "$MSG_WRONG_PW vs $(jget message)"
fi

echo
echo "── 4. A3 / A2 ─────────────────────────────────"
JAR="$JAR_T"
req "$BASE/api/auth/me"
expect_status "A3 已登录 → 200" 200
expect_in     "A3 返回 teacher01" '"username":"teacher01"'
expect_in     "A3 中文 display_name 未转义" "王老师"

req -X POST "$BASE/api/auth/logout"
expect_status "A2 登出 → 200" 200
expect_code   "A2 code=0" 0
expect_in     "A2 data 为 null" '"data":null'
req "$BASE/api/auth/me"
expect_status "A2 之后 A3 → 401" 401

echo
echo "── 5. A4 改密（stu002）────────────────────────"
JAR="$JAR_S"
req "$BASE/api/auth/me"
expect_status "改密前 A3 → 200" 200

post_json "/api/auth/password" "{\"old\":\"wrong-password\",\"new\":\"$NEW_PW\"}"
expect_status "原密码错 → 401" 401
expect_in     "原密码错文案" "原密码不正确"

post_json "/api/auth/password" "{\"old\":\"$OLD_PW\",\"new\":\"123\"}"
expect_status "新密码短于 8 位 → 422" 422
expect_in     "强度报错中文化" "长度不能少于 8 个字符"

post_json "/api/auth/password" "{\"old\":\"$OLD_PW\",\"new\":\"$OLD_PW\"}"
expect_status "新旧密码相同 → 422" 422
expect_in     "自定义校验文案为中文" "新密码不能与旧密码相同"

post_json "/api/auth/password" "{\"old\":\"$OLD_PW\",\"new\":\"$NEW_PW\"}"
expect_status "改密成功 → 200" 200
expect_code   "改密成功 code=0" 0
expect_in     "改密成功 data 为 null" '"data":null'
PW_DIRTY=1   # 改密成功：进入 EXIT trap 兜底窗口，之后任何退出都会自动改回

req "$BASE/api/auth/me"
expect_status "改密后旧会话立即失效 → 401" 401

post_json "/api/auth/login" "{\"username\":\"stu002\",\"password\":\"$NEW_PW\"}"
expect_status "用新密码重新登录 → 200" 200

post_json "/api/auth/password" "{\"old\":\"$NEW_PW\",\"new\":\"$OLD_PW\"}"
expect_status "改回原密码 → 200" 200
PW_DIRTY=0   # 改回成功：退出兜底窗口
post_json "/api/auth/login" "{\"username\":\"stu002\",\"password\":\"$OLD_PW\"}"
expect_status "原密码恢复可用 → 200" 200

echo
if [ "$FAIL" -eq 0 ]; then
  echo "$(green "全部通过")：$PASS 项"
  exit 0
fi
echo "$(red "失败 $FAIL 项")，通过 $PASS 项"
exit 1
```

- [ ] **Step 2: 加可执行位并做语法检查**

```bash
chmod +x scripts/smoke_auth.sh
bash -n scripts/smoke_auth.sh && echo "语法 OK"
```

Expected: `语法 OK`

- [ ] **Step 3: 起后端并跑冒烟（直连 8877）**

```bash
# 起后端前先清端口（debug reloader 会留下仍在监听的子进程，见 Task 10 Step 6）
lsof -ti:8877 | xargs kill 2>/dev/null; sleep 1
.venv/bin/python app-d.py > /tmp/appd.log 2>&1 &
APP_PID=$!
for i in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:8877/ && break; sleep 0.5; done
scripts/smoke_auth.sh; RC=$?
kill $APP_PID 2>/dev/null; lsof -ti:8877 | xargs kill 2>/dev/null
echo "退出码：$RC"
```

Expected: 45 行 `✓`（未登录 6 + A1 登录 10 + 失败分支 8 + A3/A2 7 + A4 改密 14），
末尾 `全部通过：45 项`，`退出码：0`

- [ ] **Step 4: 再跑一遍，确认可重复执行（密码已改回）**

```bash
lsof -ti:8877 | xargs kill 2>/dev/null; sleep 1
.venv/bin/python app-d.py > /tmp/appd.log 2>&1 &
APP_PID=$!
for i in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:8877/ && break; sleep 0.5; done
scripts/smoke_auth.sh; RC=$?
kill $APP_PID 2>/dev/null; lsof -ti:8877 | xargs kill 2>/dev/null
echo "第二次退出码：$RC"
```

Expected: 同样 `全部通过`，`第二次退出码：0`

- [ ] **Step 5: 经 nginx 再跑一遍（验证反代路径）**

```bash
docker exec nginx nginx -t && docker exec nginx nginx -s reload
lsof -ti:8877 | xargs kill 2>/dev/null; sleep 1
.venv/bin/python app-d.py > /tmp/appd.log 2>&1 &
APP_PID=$!
for i in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:8877/ && break; sleep 0.5; done
BASE=http://127.0.0.1:80 scripts/smoke_auth.sh; RC=$?
kill $APP_PID 2>/dev/null; lsof -ti:8877 | xargs kill 2>/dev/null
echo "经 nginx 退出码：$RC"
```

Expected: `全部通过`，`经 nginx 退出码：0`

- [ ] **Step 6: 确认前端一个文件都没动**

本轮改动理应只碰 `scripts/`。用聚合哈希对基线（见计划头部「基线快照」）：

```bash
echo "前端 HTML 聚合哈希: $(md5 -q *.html | md5)"
echo "requirements.txt:   $(md5 -q requirements.txt)"
```

Expected:
```
前端 HTML 聚合哈希: 0bee8fb6f56a6db81d5b8fa5c327a5a3
requirements.txt:   61054cfc633a3a79c13c3fc2d27757da
```

两个值都必须与上面**逐字一致**。不一致说明动到了不该动的文件，停下查清再继续。

- [ ] **Step 7: 检查点 —— 停下，交给协调者审查**

**本任务不执行任何 git 命令**（本项目不用 git 管理）。停在这里，把两样东西汇报给协调者，等审查通过后再开始下一个任务：

1. 本任务新增/修改的文件清单（用 `ls` 或 `find` 列，不要用 `git status`）
2. 上一步验证命令的完整输出

协调者审查通过后，直接进入下一个任务；被退回则改完重跑验证再汇报。

---

## Task 12: 文档收尾 —— `DOC_ISSUES.md` 三条 + `CLAUDE.md` 三条约定

**Files:**
- Modify: `DOC_ISSUES.md`（现有 9 条 + 「待核实」一节，新增第 10–12 条）
- Modify: `CLAUDE.md`（补目录结构、依赖方向、事务边界；同步「数据库接入层」与「运行方式」两节里已过时的说法）

**Interfaces:**
- Consumes: Task 1–11 的最终实现
- Produces: 后续模块开发可照做的书面约定

- [ ] **Step 1: 在 `DOC_ISSUES.md` 的「待核实」一节**之前**插入三条**

```markdown
---

## 10. A4 改密接口未规定新密码强度

**涉及**：《5-接口清单-V1.0》A4 `POST /api/auth/password`

**问题**：文档只写了入参是 `{old, new}`，没说新密码的长度、复杂度要求，也没说不许与旧密码相同。

**影响**：实现者只能自行取值，不同人做出来不一致，前端也没法给出统一的输入提示。

**当前处理**：本项目取 `new` 至少 8 位（`app/schemas/auth.py` 的 `min_length=8`），且不得与 `old` 相同（自定义 validator，报「新密码不能与旧密码相同」）。待文档方确认后可放宽或收紧。

---

## 11. A4 改密后是否强制下线未规定

**涉及**：《5-接口清单-V1.0》A4 `POST /api/auth/password`

**问题**：文档未说明改密成功后原会话是否作废。两种做法都常见：保留会话（体验好）或清会话强制重新登录（更安全）。

**影响**：影响前端改密成功后的跳转逻辑——若强制下线，前端必须跳登录页；若保留，跳回个人页即可。

**当前处理**：**强制下线**——`app/api/auth.py` 的 `change_password()` 在成功后 `session.clear()`，前端应跳登录页并用新密码重新登录。选它的理由是：改密的常见动机就是怀疑密码已泄漏，此时保留旧会话等于没改干净。

---

## 12. A1 登录成功的返回体未规定

**涉及**：《5-接口清单-V1.0》A1 `POST /api/auth/login`

**问题**：文档只写了「成功后 session 写入 user_id / role」，没有规定响应体的 `data` 装什么。而 A3 `/api/auth/me` 明确要返回用户信息，两者形态不一致会让前端多写一套解析。

**影响**：前端登录后拿不到用户角色与显示名，还得再调一次 A3 才能渲染界面。

**当前处理**：A1 与 A3 同形，`data` 都返回 `UserOut`：`{"id":2,"username":"stu001","display_name":"张三","role":"student"}`。前端一次请求即可完成登录 + 渲染。

```

- [ ] **Step 2: 校验 `DOC_ISSUES.md` 的编号连续**

```bash
grep -n '^## ' DOC_ISSUES.md
```

Expected: 依次为 `## 1.` … `## 12.`，最后是 `## 待核实`

- [ ] **Step 3: 在 `CLAUDE.md` 的「数据库接入层（`app/` 包）」一节**之前**插入新一节**

```markdown
### 后端分层结构（新增接口照此办理）

```
api  →  services  →  repositories  →  models
 ↓         ↓             ↓
common ←───┴─────────────┘
```

依赖**单向**，禁止反向：`repositories/` 不得 import `services/` 或 `api/`，`models/` 不得 import 任何上层。`common/` 被各层引用，自身不引用上层。判断方法就是看 import 语句的方向——**没有自动化检查脚本，这一条靠 Code Review 把关**。

| 层 | 目录 | 职责 | 硬约束 |
|---|---|---|---|
| ① 路由 | `app/api/` | 校验入参 → 调 service → 组装响应 | 不写 SQL、不写业务规则、不写 `try/except`；**session 的读写只在本层** |
| ② 业务 | `app/services/` | 业务规则、编排、**事务边界** | 不引用 `flask.session` / `flask.request`，脱离请求上下文也能测；写操作显式 `db.commit()` |
| ③ 数据 | `app/repositories/` | SQL 封装 | 第一个参数永远是 `db: Session`（由 service 传下来）；写操作只 `db.flush()`，**不 commit** |
| ④ 校验 | `app/schemas/` | pydantic v2 入参/出参模型 | 出参用 `UserOut` 这类白名单模型，避免把 `password_hash` 带出去 |
| ⑤ 横切 | `app/common/` | `errors.py` 异常与全局处理、`decorators.py` 鉴权、`security.py` 密码哈希 | — |

**`/api` 前缀只在 `app/api/__init__.py` 的 `API_PREFIX` 里写一次**，其余文件写相对路径（`@api_bp.route("/demos")`）或引用该常量。

**错误处理一条出口**：路由与 service 都不写 `try/except`。业务错误抛 `BusinessError(code, message)`，参数错误由 pydantic 抛 `ValidationError`，四类异常（`BusinessError` / `ValidationError` / `HTTPException` / `Exception`）统一由 `app/common/errors.py` 注册的 handler 转成 `{"code","message","data"}`。pydantic 与 HTTP 异常的文案在 `errors.py` 里做了中文化——**新加校验规则时留意 `_MSG_CN` 是否需要补 type**。

**事务边界**：`get_db()` 只借出会话、不管提交，`init_app()` 的 teardown 只 `close()`——未提交的改动会被回滚。所以写操作必须在 service 层显式 `db.commit()`。**不要改成「teardown 时自动提交」**：teardown 在响应构造完成后才跑，提交失败时客户端已经拿到 `code:0` 的成功响应，会变成静默的数据丢失。

**应用装配**：`app/__init__.py` 的 `create_app()` 是唯一入口（配置 → `init_app` → 错误 handler → 注册 `api_bp`）。`app-d.py`、脚本、将来的 celery 都从这里取 app，不要再各自 `new Flask()`。

**新增一个接口模块的完整动作**：

1. `app/schemas/<模块>.py` 定义入参/出参模型
2. `app/repositories/<实体>_repo.py` 定义查询（写操作只 `flush`）
3. `app/services/<模块>_service.py` 定义业务规则（写操作显式 `commit`）
4. `app/api/<模块>.py` 定义路由，挂 `api_bp`，按需加 `@login_required` / `@teacher_required`（**叠放顺序：`login_required` 在外、`teacher_required` 在内**）
5. **在 `app/api/__init__.py` 末尾的注册清单里加一行 `from . import <模块>`**——不加路由不生效
6. 更新或新增 `scripts/smoke_*.sh`

每个路由必须挂 `login_required`，或在注释里显式标注「公开」——这是 Code Review 检查项。

**接口前缀的唯一字面量在 `app/api/__init__.py`**（`API_PREFIX = "/api"`），这与「设计 token 逐页重复粘贴」是两类约定，别混：前者是后端代码，后者是自包含的静态 HTML 原型。

```

- [ ] **Step 4: 更新 `CLAUDE.md` 里已被取代的两处旧说法**

「运行方式」一节里 `- **例外 1 — pitch_comparison.html**` 那条**不需要改**（上一轮已把端点列表更新成 `/api/upload` 等，并注明前端仍走旧路径会 404）。只改下面两处。

**① 「数据库接入层」一节里 `app/response.py` 那条（`CLAUDE.md:63`）。**

把这段（用 `grep -n 'app/response.py 提供统一响应助手' CLAUDE.md` 定位）：

```
**目前只有 `app-d.py` 的根路由 `/` 用了它**；`/api/upload`、`/api/progress`、`/api/analyze` 仍返回裸字段
```

替换为：

```
**A 组认证接口（`app/api/auth.py`）与 `app-d.py` 的根路由 `/` 都在用它**；`/api/upload`、`/api/progress`、`/api/analyze` 仍返回裸字段
```

该行其余部分（`app/response.py 提供统一响应助手……`、错误码约定、以及「因为 `pitch_comparison.html` 直接消费那些字段（`j.url`、`data.logs`、`data.score`），改了会当场打断音准对比演示——要统一必须先改前端。」）**原样保留**。

**② 「数据库接入层」一节里 `app/config.py` 那条（`CLAUDE.md:58`）。**

把该行结尾这句：

```
**Flask 请求内用 `init_app(app)` + `get_db()` 配对**（只借出会话、不管提交，靠 `teardown_appcontext` 收尾），目前只有 `app-d.py` 的根路由 `/` 在用；业务接口挂上 `api_bp` 后再逐个接上。两者契约不同，不可互换。
```

替换为：

```
**Flask 请求内用 `create_app()` 里的 `init_app(app)` + `get_db()` 配对**（只借出会话、不管提交，靠 `teardown_appcontext` 收尾），A 组认证接口（`app/api/auth.py`）与 `app-d.py` 的根路由 `/` 都在用。两者契约不同，不可互换。
```

- [ ] **Step 5: 确认这两处改到位，且没漏掉其它过时说法**

```bash
grep -n 'app/response.py 提供统一响应助手' CLAUDE.md
grep -n 'A 组认证接口' CLAUDE.md
echo "--- 以下应为空：仍说 init_app 尚未接入 / 业务接口尚未实现 ---"
grep -n '目前尚未调用\|等 `/api` 蓝图建立后接上\|业务接口挂上 `api_bp` 后再逐个接上' CLAUDE.md || echo "OK：无残留"
echo "--- 顺带确认除此之外没有其它过时的「尚未实现」 ---"
grep -n '尚未实现' CLAUDE.md || echo "OK：无"
```

Expected: 前两条各输出命中行；后两条各输出 `OK：无残留` / `OK：无`。

- [ ] **Step 6: 检查点 —— 停下，交给协调者审查**

**本任务不执行任何 git 命令**（本项目不用 git 管理）。停在这里，把两样东西汇报给协调者，等审查通过后再开始下一个任务：

1. 本任务新增/修改的文件清单（用 `ls` 或 `find` 列，不要用 `git status`）
2. 上一步验证命令的完整输出

协调者审查通过后，直接进入下一个任务；被退回则改完重跑验证再汇报。

---

## Task 13: 收尾验证

**Files:** 无（只跑命令）

**Interfaces:**
- Consumes: Task 1–12 的全部产物
- Produces: 一份「实现完成」的证据

- [ ] **Step 1: 库与模型一致性**

```bash
.venv/bin/python scripts/check_db.py
```

Expected: 末行 `结果：全部一致 ✓`，退出码 0

- [ ] **Step 2: 全量冒烟（直连 + 经 nginx 各一遍）**

```bash
lsof -ti:8877 | xargs kill 2>/dev/null; sleep 1
.venv/bin/python app-d.py > /tmp/appd.log 2>&1 &
APP_PID=$!
for i in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:8877/ && break; sleep 0.5; done
scripts/smoke_auth.sh; RC1=$?
BASE=http://127.0.0.1:80 scripts/smoke_auth.sh; RC2=$?
kill $APP_PID 2>/dev/null; lsof -ti:8877 | xargs kill 2>/dev/null
echo "直连退出码：$RC1 ｜ 经 nginx 退出码：$RC2"
```

Expected: `直连退出码：0 ｜ 经 nginx 退出码：0`

- [ ] **Step 3: 依赖方向自查（人工，替代自动化脚本）**

```bash
echo "== repositories 不得引用上层 =="
grep -rn 'from app\.\(services\|api\)' app/repositories/ || echo "OK"
echo "== models 不得引用上层 =="
grep -rn 'from app\.\(services\|api\|repositories\|schemas\)' app/models/ || echo "OK"
echo "== common 不得引用上层 =="
grep -rn 'from app\.\(services\|api\|repositories\|schemas\)' app/common/ || echo "OK"
echo "== services 不得引用 api 层，且不得 import flask =="
grep -rn 'from app\.api' app/services/ || echo "OK（无 app.api）"
grep -rn '^from flask\|^import flask' app/services/ || echo "OK（无 flask）"
echo "== schemas 只应依赖 pydantic =="
grep -rn '^from \|^import ' app/schemas/auth.py
```

Expected: 前四条各输出 `OK`；最后一条只列出 `from pydantic import ...`

- [ ] **Step 4: 前缀字面量唯一性**

```bash
grep -rn '"/api' app/ app-d.py
```

Expected: 只有 `app/api/__init__.py` 的 `API_PREFIX = "/api"` 一行；其余都是 `/auth/login` 这类相对路径或注释。

- [ ] **Step 5: 新增依赖为零**

```bash
md5 -q requirements.txt
diff <(printf 'flask\nflask-cors\nlibrosa\nnumpy\nscipy\nfastdtw\nsqlalchemy\npsycopg2-binary\npydantic-settings\nwerkzeug\n') \
     <(grep -oE '^[a-zA-Z0-9_.-]+(?===)' requirements.txt | sort -u | grep -E '^(flask|flask-cors|librosa|numpy|scipy|fastdtw|sqlalchemy|psycopg2-binary|pydantic-settings|werkzeug)$' | sort) \
  && echo "OK：直接依赖未增减"
```

Expected: `61054cfc633a3a79c13c3fc2d27757da`，且 `OK：直接依赖未增减`

> `pydantic` 不在 `requirements.txt` 里——它是 `pydantic-settings` 的传递依赖。这正是本计划「零新增依赖」的依据：A 组用到的 pydantic 本来就在。

- [ ] **Step 6: 前端文件与依赖清单未被触碰**

```bash
echo "前端 HTML 聚合哈希: $(md5 -q *.html | md5)"
echo "requirements.txt:   $(md5 -q requirements.txt)"
```

Expected（与计划头部「基线快照」逐字一致）:
```
前端 HTML 聚合哈希: 0bee8fb6f56a6db81d5b8fa5c327a5a3
requirements.txt:   61054cfc633a3a79c13c3fc2d27757da
```

- [ ] **Step 7: 没有残留的临时文件**

执行过程中各任务用 `_t_*.py` 做过验证，都应已删除。

```bash
find . -maxdepth 2 -name '_t_*' -not -path './.venv/*' -not -path './.git/*' -print
ls app/common app/schemas app/services app/repositories app/api
```

Expected: 第一条**无输出**；第二条各目录内容为：

```
app/common:       __init__.py  __pycache__  decorators.py  errors.py  security.py
app/schemas:      __init__.py  __pycache__  auth.py
app/services:     __init__.py  __pycache__  auth_service.py
app/repositories: __init__.py  __pycache__  user_repo.py
app/api:          __init__.py  __pycache__  auth.py
```

- [ ] **Step 8: 提醒用户收尾（不由本计划执行）**

以下两件**不在本计划范围内**，实现完成后告知用户：

1. `pitch_comparison.html` 有 3 处调用旧路径，需用户自行改：`:522` `/upload` → `/api/upload`、`:804` `/progress` → `/api/progress`、`:824` `/analyze` → `/api/analyze`。（`:529` 的 `${API}${j.url}` 不用改——后端返回的 `url` 已带 `/api` 前缀。）
2. 停止后端进程（`kill $APP_PID` 或 `lsof -ti:8877 | xargs kill`），避免 8877 端口被占。
