# 后端接口分层结构设计

日期：2026-09-11 ｜ 状态：已评审待实现 ｜ 模板接口：`POST /api/auth/login`

## 1. 背景与目标

后端此前只有 `app-d.py` 一个自包含文件：Flask 实例、librosa 分析代码、演示路由全混在一起，接口直接写在路由函数里（表单/JSON 解析、业务判断、返回组装不分层）。随着《5-接口清单-V1.0》那 49 个接口要陆续落地，需要先把分层结构建起来，否则每个模块各写各的，越往后越难收敛。

本次要交付的是**一套可复制给后续模块的分层骨架**，并以 A 组认证接口（A1–A4）作为跑得通的模板。

范围之外（明确不做）：

- 不实现 A 组之外的任何接口（B–K 组留给后续迭代）
- 不搬迁 `app-d.py` 的 4 条演示路由与 librosa 分析代码
- **不做 `app-d.py` 的演示路由与 `api` 蓝图合流**——它们改用独立的 `demo_bp`，等 B1–B5 真正实现时整块删除
- 不引入 JWT / Flask-Login / marshmallow / Alembic（《6-登录与数据隔离方案》已明确排除前三者的前两项；Alembic 见 `CLAUDE.md`）
- 不新增任何 Python 依赖

## 2. 目录结构

```
app/
├── __init__.py            create_app() 工厂
├── config.py              Settings（已有；新增两个字段）
├── db.py                  engine/SessionLocal/Base/session_scope/init_app/get_db（不动）
├── response.py            ok / fail（不动）
├── models/                15 个 ORM 模型（不动）
│
├── api/                   ① 路由层
│   ├── __init__.py        API_PREFIX + api_bp + 子模块注册清单
│   └── auth.py            A1–A4
│
├── services/              ② 业务逻辑层
│   ├── __init__.py
│   └── auth_service.py
│
├── repositories/          ③ 数据访问层
│   ├── __init__.py
│   └── user_repo.py
│
├── schemas/               ④ 入参校验（pydantic v2）
│   ├── __init__.py
│   └── auth.py
│
└── common/                ⑤ 横切关注点
    ├── __init__.py
    ├── errors.py          BusinessError + register_error_handlers()
    ├── decorators.py      login_required / teacher_required / current_user_id()
    └── security.py        hash_password / verify_password

scripts/
└── smoke_auth.sh          认证接口冒烟脚本
```

## 3. 依赖方向（唯一硬约束）

```
api  →  services  →  repositories  →  models
 ↓         ↓             ↓
common ←───┴─────────────┘
```

- 单向，禁止反向：`repositories/` 不得 import `services/` 或 `api/`；`models/` 不得 import 任何上层
- `common/` 被各层引用，自身不引用任何上层模块
- 判断方法：看 import 语句的方向

本次不写自动化检查脚本，此约束作为 `CLAUDE.md` 的 Code Review 检查项维护。

## 4. 各层职责

### 4.1 `api/` 路由层

只做三件事：**校验入参 → 调 service → 组装响应**。不写 SQL、不写业务规则、不写 `try/except`（错误由全局 handler 兜）。

**`app/api/__init__.py`** —— `/api` 前缀的全项目唯一字面量：

```python
API_PREFIX = "/api"
api_bp = Blueprint("api", __name__, url_prefix=API_PREFIX)
from . import auth      # noqa: E402,F401  ← 注册清单
```

> 末尾那行 import 是**注册清单**：每新增一个模块（`homework.py`、`analyze.py`…）都必须在此加一行，否则路由不生效。与 `app/models/__init__.py` 的既有约定同构。

**`app/api/auth.py`** —— A1–A4。session 的读写**只在本层**发生。

### 4.2 `services/` 业务逻辑层

业务规则、编排、**事务边界**。不引用 `flask.session`、不引用 `request`——因此脱离请求上下文也能测。

### 4.3 `repositories/` 数据访问层

SQL 封装。约定：

- 第一个参数永远是 `db: Session`（由路由层从 `get_db()` 取好传下来），仓储层不自己拿全局会话
- 写操作只 `db.flush()`（拿 id、触发约束检查），**不 commit**
- 数据隔离规则（《6-登录与数据隔离方案》第 4 节）后续集中落在本层，例如 `student_repo.get_visible(db, student_id, current_user)`，越权直接抛 `BusinessError(403, ...)`，所有调用方自动继承

### 4.4 `schemas/` 入参校验层

pydantic v2（`pydantic 2.13.5` 已由 `pydantic-settings` 传递依赖引入，**零新增依赖**）。每个接口一个请求模型，出参用 `UserOut` 这类模型统一形态。

### 4.5 `common/` 横切关注点

`errors.py`（异常与全局处理）、`decorators.py`（鉴权装饰器）、`security.py`（密码哈希）。

## 5. 错误处理

**一条出口**：路由与 service 层不写 `try/except`，所有错误汇到 `app/common/errors.py` 注册的四个 handler。

```python
class BusinessError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def register_error_handlers(app):
    @app.errorhandler(BusinessError)     # service 抛，转 fail(code, message)
    @app.errorhandler(ValidationError)   # pydantic  → 422，文案中文化（见下）
    @app.errorhandler(HTTPException)     # 404/405 … → JSON（默认是 HTML）
    @app.errorhandler(Exception)         # 500：堆栈只进日志，响应不回内部细节
```

要点：

- `HTTPException` 那条必须有。当前未匹配的 `/api/*` 返回 Werkzeug 的 **HTML** 404 页，前端无法解析，也不符合文档的「统一返回」
- `Exception` 那条对外只回「服务器内部错误」，完整堆栈进 `app.logger.exception`
- **已实测**：Flask 3.1.3 下这四个 handler 在 `DEBUG=True` 时同样生效（`handle_user_exception` 先查已注册 handler，不会走到 `PROPAGATE_EXCEPTIONS` 分支）

### 5.1 pydantic 报错必须中文化

**实测**：pydantic v2 的默认文案是**英文**，直接透给前端不可接受——本项目是中文 UI。

```
{'old': 'x'}                        → loc=('new',)  msg='Field required'
{'old': 'x', 'new': '123'}          → loc=('new',)  msg='String should have at least 8 characters'
{'old': 'aaa...', 'new': 'aaa...'}  → loc=('new',)  msg='Value error, 新密码不能与旧密码相同'
```

所以 `_format_validation_error` 做三层处理：

```python
_MSG_CN = {                      # 已知 type → 中文，参数从 err["ctx"] 取
    "missing":          lambda c: "必填",
    "string_too_short": lambda c: f"长度不能少于 {c['min_length']} 个字符",
    "string_too_long":  lambda c: f"长度不能超过 {c['max_length']} 个字符",
    "int_parsing":      lambda c: "必须是整数",
}

def _format_validation_error(exc):
    parts = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err["loc"]) or "body"
        # ① 已知 type 走中文映射；② 自定义 validator 抛的 ValueError 本就是中文，
        #    只需去掉 pydantic 加的 "Value error, " 前缀；
        # ③ 其余回退英文原文，保证信息不被吞掉（宁可英文也不要「参数错误」四个字）。
        if fmt := _MSG_CN.get(err["type"]):
            msg = fmt(err.get("ctx") or {})
        else:
            msg = err["msg"].removeprefix("Value error, ")
        parts.append(f"{loc}: {msg}")
    return "; ".join(parts)
```

输出示例：`new: 长度不能少于 8 个字符`、`old: 必填`、`new: 新密码不能与旧密码相同`。

错误码沿用 HTTP 语义、与 HTTP 状态码一致（`DOC_ISSUES.md` 第 9 条）。

## 6. 认证与配置

### 6.1 密码

```python
# app/common/security.py
HASH_METHOD = "pbkdf2:sha256"        # 必须显式指定
```

不显式指定会退回 werkzeug 3.x 的 scrypt 默认值，输出 162 字符、超出 `users.password_hash` 的 `VARCHAR(128)`，插入时报表错（`DOC_ISSUES.md` 第 8 条）。封装在本文件，避免第二处再踩。

### 6.2 鉴权装饰器

按《6-登录与数据隔离方案》第 5 节的参考实现，返回体改走 `response.fail()`。**叠放顺序有意义**：

```python
@login_required        # 外层：未登录先 401
@teacher_required      # 内层：已登录再判 403
```

### 6.3 配置

`app/config.py` 的 `Settings` 新增两个字段：

```python
class Settings(BaseSettings):
    database_url: str
    secret_key: str
    session_cookie_secure: bool = False
```

`.env` 已写入 `SECRET_KEY`（`secrets.token_urlsafe(48)`，64 字符）。

`session_cookie_secure` 默认 `False` 是刻意的：本地 nginx 走 HTTP，`Secure` 属性会让浏览器静默丢弃 Cookie，表现为「登录返回成功、后续每个请求都 401」。生产上 HTTPS 后置 `True`。

### 6.4 create_app()

```python
def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=settings.secret_key,
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),   # 文档 3：会话 7 天
        SESSION_COOKIE_HTTPONLY=True,                   # 文档 3：HttpOnly
        SESSION_COOKIE_SAMESITE="Lax",                  # 文档 3：SameSite=Lax
        SESSION_COOKIE_SECURE=settings.session_cookie_secure,
    )
    if config_overrides:
        app.config.update(config_overrides)             # 测试用
    app.json.ensure_ascii = False                       # 中文不转义成 \uXXXX
    init_app(app)                                       # db 会话 teardown
    register_error_handlers(app)
    from app.api import api_bp
    app.register_blueprint(api_bp)
    return app
```

`app.json.ensure_ascii = False` 对应 Flask 3.x 已移除的旧配置项 `JSON_AS_ASCII`。当前后端返回的中文全是 `\uXXXX` 转义。

**蓝图注册顺序约束在此结构上自动成立**：`from app.api import api_bp` 会触发 `app/api/__init__.py` 末尾的 `from . import auth`，业务路由在那时已挂好。演示路由在独立的 `demo_bp` 上，互不干扰——不靠约定维持，是结构上成立的。

## 7. 演示路由的处理

`app-d.py` 里的 4 条演示路由（`/api/upload`、`/api/analyze`、`/api/progress`、`/api/audio/<filename>`）挂到独立蓝图，复用同一个前缀常量：

```python
from app.api import API_PREFIX

demo_bp = Blueprint("demo", __name__, url_prefix=API_PREFIX)

@demo_bp.route("/upload", methods=["POST"])
def upload(): ...          # 4 条路由，librosa 代码一行不动

app = create_app()
app.register_blueprint(demo_bp)     # 紧跟自己的路由定义，顺序局部可见

@app.route("/")                     # 根路由仍挂 Flask 实例
def index(): ...
```

理由：注册蓝图的时机约束（`register_blueprint` 之后不能再往该蓝图加路由，否则抛 `AssertionError`）变成**局部**的——每个文件注册紧跟自己的路由定义，不像把演示路由也挂 `api_bp` 那样，约束藏在远处的 `create_app()` 里。

两个蓝图同前缀在 Flask 中合法：endpoint 名（`api.login` / `demo.upload`）不冲突，URL 也不重叠。`demo_bp` 是过渡物，B1–B5 落地后连同 `app-d.py` 的 librosa 代码整块删除。

## 8. 接口契约（A 组）

统一返回 `{"code":0,"message":"ok","data":{...}}`（成功）/ `{"code":<4xx|5xx>,"message":"...","data":null}`（失败）。

`UserOut`（A1/A3 共用）：

```json
{"id": 2, "username": "stu001", "display_name": "张三", "role": "student"}
```

| 编号 | 接口 | 鉴权 | 入参 | 成功 data | 失败 |
|---|---|---|---|---|---|
| A1 | `POST /api/auth/login` | 公开 | `{username, password}` | `UserOut` | 401 用户名或密码错误 / 403 账号已停用 / 422 参数错误 |
| A2 | `POST /api/auth/logout` | 登录 | 无 | `null` | 401 未登录 |
| A3 | `GET /api/auth/me` | 登录 | 无 | `UserOut` | 401 未登录 / 401 登录状态已失效 |
| A4 | `POST /api/auth/password` | 登录 | `{old, new}` | `null` | 401 原密码不正确 / 422 参数错误 |

A1 成功后：`session.permanent = True`，写入 `session["user_id"]`、`session["role"]`。
A4 成功后：`session.clear()`，强制重新登录。

### A1 数据流

```
POST /api/auth/login   {"username":"stu001","password":"..."}
  ├─ nginx  location ^~ /api/   ── 路径原样转发
  ├─ Flask  api_bp → api/auth.py::login()
  │     LoginIn.model_validate(request.get_json() or {})   ← 失败 → ValidationError → 422
  │     db = get_db()
  │     auth_service.login(db, username, password)
  │        └ user_repo.get_by_username(db, username)
  │        └ verify_password(...) 失败 → BusinessError(401, "用户名或密码错误")
  │        └ 账号停用            → BusinessError(403, "账号已停用")
  │     session.permanent = True；写入 user_id / role
  │     return ok(UserOut.model_validate(user).model_dump())
  └─ 任何一层抛出 → 全局 handler → fail(code, message)
```

三个刻意的取舍：

1. **session 读写只在路由层**，service 不碰 `flask.session`。service 因此脱离请求上下文也能测；「谁改了会话」全项目只有 `api/` 一处。
2. **用户不存在与密码错误返回同一句文案**，不泄漏账号是否存在。
3. **事务边界在 service 层，显式 `db.commit()`**（下节展开）。

## 9. 事务边界

`get_db()` 按现有契约**只借出会话、不管提交**，`init_app()` 注册的 teardown 只 `close()`——未提交的改动会被回滚。因此：

- `repositories/` 的写函数只 `db.flush()`
- `services/` 在写操作完成时显式 `db.commit()`

不采用「teardown 时自动提交」：teardown 在响应构造完成后才跑，提交失败时客户端已经拿到 `code:0` 的成功响应，会变成静默的数据丢失。显式提交能让失败在构造响应前就冒泡成 500。

## 10. 验证

`scripts/smoke_auth.sh`（curl，零新增依赖，沿用 `scripts/check_db.py` 的退出码闸门风格）。前置：Flask 后端运行中、数据库已灌 `seed.sql`。种子账号初始密码均为 `xiyun@2026`。

| 场景 | 期望 |
|---|---|
| A1 登录 teacher01 / stu002 | 200，`Set-Cookie` 带 `HttpOnly` + `SameSite=Lax`，body 含 role |
| A2 登出 → 再查 A3 | 401 |
| A3 未登录 / 登录后 | 401 / 200 带角色 |
| A4 原密码错 | 401 |
| A4 改密成功 → 用新密码重新登录 | 200 / 200 |
| 空 body、超长 username、新密码短于 8 位 | 422，message 可读 |
| `/api/nope` | JSON 404（非 HTML） |
| 中文响应 | 不转义成 `\uXXXX` |

学生角色的成功登录用例走 **`stu002`** 而非 `stu001`：A4 改密那一步复用的就是这条会话，末尾还要用 `stu002` 的新密码重新登录，两者必须是同一个账号，否则改的是 `stu001` 的密码却拿 `stu002` 去登录。`stu001` 仍保留在「密码错 → 401」失败分支里。

**数据隔离三规则本次验不到**：A 组接口不带 `student_id` 查询，没有可越权的目标。待第一个按 `student_id` 查询的接口（预计 D2 练习日志或 H1 学生列表）落地时补测。

## 11. 待登记的文档空白

以下三处《5-接口清单》未规定，按项目惯例不动文档、登记到 `DOC_ISSUES.md`，实现按右侧取值：

| # | 空白 | 本设计取值 |
|---|---|---|
| 1 | A4 新密码强度未规定 | `min_length=8`，且不得与旧密码相同 |
| 2 | A4 改密后是否踢下线未规定 | 踢下线（`session.clear()`） |
| 3 | A1 返回体未规定（文档只写「session 写入 user_id/role」） | 与 A3 同形，返回 `UserOut` |

## 12. 实施顺序

1. `app/config.py` 加 `secret_key` / `session_cookie_secure`
2. `app/common/`：`errors.py`、`decorators.py`、`security.py`
3. `app/schemas/auth.py`
4. `app/repositories/user_repo.py`
5. `app/services/auth_service.py`
6. `app/api/__init__.py` 提出 `API_PREFIX` + 注册清单；新增 `app/api/auth.py`
7. `app/__init__.py`：`create_app()`
8. `app-d.py` 改造成 `create_app()` + `demo_bp`
9. `scripts/smoke_auth.sh`
10. `DOC_ISSUES.md` 登记 3 条
11. `CLAUDE.md` 补目录结构、依赖方向、事务边界三条约定
12. 跑冒烟脚本验证

## 13. 对后续模块的约定（写进 CLAUDE.md 的部分）

新增一个接口模块的完整动作：

1. `app/schemas/<模块>.py` 定义入参/出参模型
2. `app/repositories/<实体>_repo.py` 定义查询（写操作只 flush）
3. `app/services/<模块>_service.py` 定义业务规则（写操作显式 commit）
4. `app/api/<模块>.py` 定义路由，挂 `api_bp`，按需加 `@login_required` / `@teacher_required`
5. **在 `app/api/__init__.py` 的注册清单里加一行 import**
6. 更新 `scripts/smoke_*.sh` 或新增对应冒烟脚本

每个路由必须挂 `login_required` 或在注释中标注「公开」——`CLAUDE.md` 已列为 Code Review 检查项。
