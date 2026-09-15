# 页面级登录鉴权设计

日期：2026-09-15 ｜ 状态：已评审待实现 ｜ 关联：《6-登录与数据隔离方案-V1.0》第 3、5 节

## 1. 背景与目标

后端 A 组认证接口（A1–A4）与 `login_required` / `teacher_required` 装饰器已于 2026-09-11 落地，但**只有 `/api/` 下的接口受保护，页面一个都没保护**：任何人直接访问 `http://<host>/dashboard.html` 都能看到完整页面。

本次要交付的是**页面级鉴权闭环**：

1. 新增 `login.html` 登录页（项目当前没有）
2. 12 个 HTML 页面全部接入登录校验，未登录跳转登录页
3. 登录成功后进入班级看板 `dashboard.html`
4. 页面内提供登出入口

## 2. 范围之外（明确不做）

- 不做基于角色的页面分流。教师与学生看到同一套页面，本次只校验「是否登录」，不校验「是什么角色」——《6》第 4 节的数据隔离规则落在接口层，不在页面层
- 不改动 `app/api/auth.py` 的 A1–A4 契约（`scripts/smoke_auth.sh` 依赖其 401-JSON 行为）
- 不给 `app-d.py` 的 4 条演示路由（`/api/upload`、`/api/progress`、`/api/analyze`、`/api/audio/demo/<f>`）加鉴权——它们是等 B1–B5 落地后整块删除的过渡物
- 不做「已登录访问 login.html 自动跳走」——浏览器返回键的场景已由 `location.replace` 覆盖，手动敲地址栏看到登录页无害（YAGNI）
- 不抽公共 JS/CSS。项目约定「每页自包含」（`common/` 下 8 个文件仍是 0 字节占位），本次片段逐页内联
- 不引入任何新 Python/JS 依赖

## 3. 现状：页面为什么没被鉴权

nginx（容器 `nginx`，配置在项目外的 `~/nginx/conf.d/default.conf`）把站点根 `/srv/operaAI` 只读挂载到项目目录，`.html` 由 `try_files` **静态直供**，压根不进 Flask：

```nginx
location ~ ^/[^/]+\.html$ { try_files $uri =404; }   # ← 鉴权在这里被绕过
location ^~ /api/         { proxy_pass http://host.docker.internal:8877; }
```

所以 `login_required` 装饰器再怎么加也作用不到页面上——**必须先让页面请求流经 Flask**。

## 4. 架构：请求分流

```
浏览器 ──► nginx:80
             ├─ /static/*        ──► try_files 静态直供（公开）
             ├─ /{page}.html     ──► proxy_pass 8877 ──► Flask page_bp + page_login_required
             ├─ /                ──► 302 /index.html
             └─ /api/*           ──► proxy_pass 8877 ──► Flask api_bp（一行不动）
```

`login.html` 走同一条 `.html` location，但在 Flask 侧注册为**公开路由**——鉴权粒度是「每页一个路由」，不是「整个 location 放行/拦截」。

### 4.1 鉴权决策表

| 路径 | 由谁服务 | 是否需登录 |
|---|---|---|
| `/login.html` | Flask `page_bp` | ❌ 公开 |
| `/static/*` | nginx 静态 | ❌ 公开 |
| 其余 12 个 `.html` | Flask `page_bp` | ✅ |
| `/api/*` | Flask `api_bp` | 各自路由决定（不变） |
| 其它路径 | nginx | 404（不变） |

## 5. 鉴权装饰器：新增 `page_login_required`

`app/common/decorators.py` 新增一个函数，与既有 `login_required` **并列**而非替代：

```python
def page_login_required(fn):
    """页面版鉴权：未登录 302 到登录页，而不是抛 401。

    与 login_required 的唯一区别是「未登录怎么表达」——接口请求回 401 JSON
    给前端 JS 判断，浏览器地址栏的页面请求要给一个能直接渲染的跳转。
    「是否已登录」的判断与 login_required 共用同一个 current_user_id()，
    不存在第二套登录判定逻辑。
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if current_user_id() is None:
            return redirect(url_for("page.login"))
        return fn(*args, **kwargs)
    return wrapper
```

**为什么不直接复用 `login_required`**：它抛 `BusinessError(401)`，全局 handler 转成 JSON 401。在浏览器地址栏里，用户会看到 `{"code":401,"message":"未登录","data":null}` 而不是跳转。要复用就得改 401 handler 让它按请求路径分流，等于把「跳转」这个业务决定藏进错误处理层，且浏览器直接访问 `/api/xxx` 时会误判。独立装饰器显式、可读，且 `login_required` 的既有契约纹丝不动。

## 6. `login.html`（新建）

单文件自包含，与现有页同风格：

- `<head>` 内嵌 `:root` 设计 token，**从 `index.html` 原样复制**（宣纸底 + 景泰蓝主色），不另起配色
- 无侧边栏（未登录无导航可言），居中卡片布局
- 顶部「戏韵AI」标题 + 朱砂印章，与 `index.html` 的 `.hero` 同款
- 表单：用户名、密码（`type="password"`）、登录按钮、错误提示区
- 交互：
  - 回车提交；提交中禁用按钮并显示「登录中…」
  - `POST /api/auth/login`，`credentials: 'same-origin'`
  - 成功（`body.code === 0`）→ `location.replace('dashboard.html')`
  - 失败 → 在提示区展示后端返回的 `message`（A1 已是中文文案：`用户名或密码错误` / `账号已停用` / `参数错误`）
  - 网络异常 → 提示「无法连接服务器」

用 `location.replace` 而非 `href`，避免用户按返回键退回登录表单。

### 6.1 登录数据流

```
login.html 提交
  └─ POST /api/auth/login  {username, password}
       └─ nginx ^~ /api/ ──► Flask api_bp → api/auth.py::login()
            ├─ 失败 → 401/403/422 JSON → 页面展示 message
            └─ 成功 → session.permanent=True; session["user_id"], session["role"]
                      → Set-Cookie (HttpOnly, SameSite=Lax)
                      → 200 {code:0, data:{id,username,display_name,role}}
  └─ location.replace('dashboard.html')
       └─ GET /dashboard.html（带 Cookie）→ page_login_required 放行 → 返回页面
```

## 7. `app/pages.py`（新建）

**位置说明**：放在 `app/` 下、与 `app/api/` 平级，**不放进 `app/api/`**。因为 `CLAUDE.md` 已把 `app/api/` 的语义定为「挂在 `api_bp` 上、带 `/api` 前缀的接口模块」，页面路由不带该前缀、不挂该蓝图，塞进去会破坏这个语义。

同时它**不进 `app/api/__init__.py` 的注册清单**（那份清单只管 `api_bp` 的子模块），改由 `create_app()` 显式导入并注册——与 `app-d.py` 的 `demo_bp` 同一模式。

```python
# -*- coding: utf-8 -*-
"""页面路由：把 12 个 HTML 收进 Flask，逐页挂鉴权。

页面不是接口，所以这个蓝图**没有 url_prefix**——/api 是接口的 Base URL，
页面挂在站点根下（/dashboard.html）。也因此它不进 app/api/__init__.py 的
注册清单，由 create_app() 显式导入注册。
"""

from pathlib import Path

from flask import Blueprint, send_from_directory

from app.common.decorators import page_login_required

PAGES_DIR = Path(__file__).resolve().parents[1]      # app/pages.py → 项目根

page_bp = Blueprint("page", __name__)

# 公开页：只有登录页
@page_bp.route("/login.html")
def login():
    return send_from_directory(PAGES_DIR, "login.html")

# 受保护页：除登录页外的全部页面
PROTECTED_PAGES = [
    "index", "dashboard", "demo_library", "annotation", "homework",
    "tracking", "knowledge_graph", "cdm_report", "recommendation",
    "sing_along", "AI_teacher", "pitch_comparison",
]


def _serve(name: str):
    """返回一个把 name.html 发出去的视图函数。"""
    def view():
        return send_from_directory(PAGES_DIR, f"{name}.html")
    return view


for _name in PROTECTED_PAGES:
    page_bp.add_url_rule(
        f"/{_name}.html",
        endpoint=f"page_{_name}",
        view_func=page_login_required(_serve(_name)),
    )
```

三点说明：

- **用 `add_url_rule` 循环注册而非写 12 个 `@page_bp.route` 函数**：12 个视图函数体完全相同，逐个写只是把同一个字符串抄 12 遍。`endpoint` 显式命名为 `page_<name>`，避免 Flask 从函数名 `view` 推导导致重名冲突
- **`send_from_directory` 而非 `send_file`**：它接受目录与文件名的分离入参，对 `..` 做了转义校验。这里文件名全部来自代码内的字面量列表，不来自请求，但保持这个习惯
- **`Cache-Control` 不需要手动加**：`send_from_directory` 的 `max_age` 默认 `None`，Flask 据此设 `Cache-Control: no-cache`，与 nginx 原先 `add_header` 的效果一致（实现时实测确认）

## 8. `app/__init__.py` 改动

```python
from app.api import api_bp
app.register_blueprint(api_bp)

from app.pages import page_bp        # 页面路由：无前缀，独立于 /api
app.register_blueprint(page_bp)
```

`app/pages.py` 的 import 必须在 `register_blueprint` 之前，理由同 `api_bp`（`Blueprint.route` 只把动作记进 `deferred_functions`，模块不被 import 就没人执行）。这里 `page_bp` 的路由在模块级 `for` 循环里就已执行，顺序天然正确。

## 9. nginx 改动（`~/nginx/conf.d/default.conf`）

```nginx
# 根路径 → 导航首页。首页本身受登录保护，这里只做跳转，
# 不能再用 try_files 直供（那会绕过鉴权）。
location = / {
    return 302 /index.html;
}

# 受保护的页面：转发给 Flask 的 page_bp。
# 原来是 try_files 静态直供——那正是鉴权被绕过的地方。
# /login.html 走同一条 location，由 Flask 侧注册为公开路由。
location ~ ^/[^/]+\.html$ {
    proxy_pass http://host.docker.internal:8877;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# 静态资源保持直供、公开（无鉴权需求）
location /static/ {
    try_files $uri =404;
    add_header Cache-Control "no-cache";
}
```

- `location ^~ /api/` **一行不改**。`^~` 前缀匹配优先于正则，所以 `/api/xxx` 不会被上面的 `.html` 正则抢走
- 页面响应不再经 nginx 加 `Cache-Control`，改由 Flask 的 `send_from_directory` 提供（同为 `no-cache`），行为等价
- 改完需 `docker exec nginx nginx -s reload`

## 10. 页面侧的用户条与登出

### 10.1 两类页面，两种处理

| 页面 | 现状 | 处理 |
|---|---|---|
| 10 个页面<br>`AI_teacher` `annotation` `cdm_report` `dashboard` `demo_library` `homework` `knowledge_graph` `recommendation` `sing_along` `tracking` | 有 `.navbar`，右上角 `.nav-user` **写死了假数据** | **复用该区域**：替换为真实用户 + 追加登出按钮 |
| 2 个页面<br>`index` `pitch_comparison` | 无导航栏 | 注入右上角固定浮条 |

10 个页面的 `.nav-user` 结构完全一致，仅缩进不同（4/8 空格）：

```html
<div class="nav-user">
  <div class="avatar">👩🏫</div>
  <span>王慧芳</span>
  <span style="color:var(--text-muted);font-size:13px">|</span>
  <span style="color:var(--text-secondary);font-size:13px">中国戏曲学院</span>
</div>
```

写死的描述文字（`中国戏曲学院` / `初级班`）**在数据库里没有对应字段**——`users` 表只有 `username` / `role` / `display_name` / `is_active`，A3 的 `UserOut` 也只返回前三个加 `id`。所以描述位改为展示**角色中文名**（`教师` / `学生`），不编造院校班级信息。

### 10.2 注入片段

每页 `</body>` 前内联一段（片段本身自包含，样式与脚本都在里面）：

```html
<style>
  .logout-btn{background:none;border:1px solid var(--border-medium);color:var(--text-secondary);
    font-size:12px;padding:3px 10px;border-radius:6px;cursor:pointer;font-family:inherit}
  .logout-btn:hover{border-color:var(--danger);color:var(--danger)}
</style>
<script>
(async () => {
  let user;
  try {
    const r = await fetch('/api/auth/me', {credentials: 'same-origin'});
    if (!r.ok) return location.replace('login.html');   // 会话已失效
    user = (await r.json()).data;
  } catch { return location.replace('login.html'); }     // 后端不可达
  if (!user) return;

  const isTeacher = user.role === 'teacher';
  const box = document.querySelector('.nav-user');
  if (box) {
    box.innerHTML =
      `<div class="avatar">${isTeacher ? '👩🏫' : '🎭'}</div>
       <span>${user.display_name}</span>
       <span style="color:var(--text-muted);font-size:13px">|</span>
       <span style="color:var(--text-secondary);font-size:13px">${isTeacher ? '教师' : '学生'}</span>
       <button class="logout-btn" id="logoutBtn">登出</button>`;
  } else {
    // index.html / pitch_comparison.html：无导航栏，注入固定浮条
    const bar = document.createElement('div');
    bar.className = 'logout-bar';
    bar.innerHTML = `${user.display_name} · ${isTeacher ? '教师' : '学生'}
      <button class="logout-btn" id="logoutBtn">登出</button>`;
    document.body.appendChild(bar);
  }

  document.getElementById('logoutBtn').onclick = async () => {
    try { await fetch('/api/auth/logout', {method: 'POST', credentials: 'same-origin'}); }
    catch {}
    location.replace('login.html');
  };
})();
</script>
```

配套的 `.logout-bar` 样式（仅两个无导航栏页面需要，一并内联）：

```css
.logout-bar{position:fixed;top:16px;right:20px;z-index:60;display:flex;align-items:center;gap:10px;
  background:var(--bg-secondary);border:1px solid var(--border-light);border-radius:10px;
  padding:6px 12px;font-size:13px;color:var(--text-secondary);box-shadow:0 2px 10px rgba(0,0,0,.05)}
```

`z-index:60` 高于 `.navbar` 的 `50`；`annotation.html` 的 `.toast-container` 在 `top:72px`，与本条的 `top:16px` 不重叠。

### 10.3 为什么不写 `if (未登录) 跳转`

页面已被服务端保护，**能加载出来就说明会话有效**。这段脚本因此不做守卫，只在两个边缘情况兜底跳转：会话在页面打开后过期（`/api/auth/me` 返回 401）、后端不可达。真正的拦截在 Flask 侧，前端这段是纯展示。

## 11. 副作用与取舍

1. **`file://` 双击打开彻底失效**。此前多数页面可脱离服务端直接打开（`CLAUDE.md` 记为使用方式之一），接入鉴权后必须经 nginx/Flask 的 HTTP 访问。这是服务端强制鉴权的必然代价
2. **Flask 根路由 `/` 的 users-JSON 示例从 80 端口不可达**。nginx 的 `location = /` 改为 302 到 `/index.html`。该示例仍在，直连 `:8877` 可访问；`CLAUDE.md` 中「根路由是数据库接入示例」的记载需要补一句说明
3. **页面经过 Python 进程**。静态直供的性能优势消失，对原型场景无影响
4. **10 个页面的 `.nav-user` 假数据被真实数据覆盖**。`王慧芳`／`李小燕` 这些演示姓名不再出现，改为数据库里的 `display_name`（种子数据是「王老师」／「张三」／「李四」）

## 12. 验证

扩展 `scripts/smoke_auth.sh`（沿用既有退出码闸门风格），新增页面鉴权段：

| 场景 | 期望 |
|---|---|
| 未登录 GET `/dashboard.html` | 302，`Location: /login.html` |
| 未登录 GET `/login.html` | 200，含登录表单 |
| 未登录 GET `/index.html` | 302 → `/login.html` |
| 未登录 GET `/pitch_comparison.html` | 302 → `/login.html` |
| 登录后 GET `/dashboard.html` | 200，含页面正文 |
| GET `/`（登录与否都一样） | 302，`Location: /index.html`——这条重定向在 nginx 层无条件发生，鉴权点是它跳过去的 `/index.html` |
| **登录后 GET `/api/auth/me`** | 200（**契约未变**） |
| **未登录 GET `/api/auth/me`** | **401 JSON**（**契约未变**） |
| 未登录 GET `/static/echarts.min.js` | 200 |
| 登出后 GET `/dashboard.html` | 302 → `/login.html` |

加粗的两行是回归闸门：确认本次改动**没有**把 API 的 401-JSON 行为改成 302。

手工验收：浏览器走一遍 `login.html` → 输入 `teacher01` / `xiyun@2026` → 落到 `dashboard.html` → 右上角显示「王老师 · 教师」→ 点登出 → 回登录页 → 直接敲地址栏 `/dashboard.html` → 仍被弹回登录页。

## 13. 待登记的文档空白

《6-登录与数据隔离方案》只定义了接口级鉴权（`login_required` / `teacher_required` 作用在接口上），**未规定页面本身是否需要登录**，也未规定未登录时的表现（跳转还是报错）。本次按右侧取值实现，登记到 `DOC_ISSUES.md`：

| # | 空白 | 本设计取值 |
|---|---|---|
| 1 | 页面级鉴权是否要求、粒度如何 | 全部 12 个页面均需登录，唯一公开页是 `login.html` |
| 2 | 未登录访问页面时的表现 | 302 跳转 `/login.html`（非 401） |
| 3 | 登出后的落点 | `/login.html` |
| 4 | 页面是否需要按角色区分 | 不区分，只校验是否登录 |

## 14. 实施顺序

1. `app/common/decorators.py` 加 `page_login_required`
2. 新建 `login.html`
3. 新建 `app/pages.py`
4. `app/__init__.py` 注册 `page_bp`
5. 改 `~/nginx/conf.d/default.conf`，`docker exec nginx nginx -s reload`
6. 12 个页面注入用户条 / 浮条
7. 扩展 `scripts/smoke_auth.sh`，跑通全部场景
8. 手工浏览器验收
9. `DOC_ISSUES.md` 登记 4 条
10. `CLAUDE.md` 补页面鉴权约定与 `/` 根路由的变化
