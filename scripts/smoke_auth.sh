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
echo "── 6. 页面鉴权 ────────────────────────────────"
# 干净的 cookie jar：第 4 段末尾 teacher01 已登出，但显式换一个匿名 jar，
# 让「未登录」这个前提不依赖前面几段的收尾状态。
# 静态资源只由 nginx 直供（nginx 配置里的 location /static/），Flask 侧没有
# /static/ 路由——create_app() 用的是 Flask(__name__)，static_folder 指向
# 并不存在的 app/static，所以直连 8877 时这里必然是 404 JSON「接口不存在」。
# 因此这条断言只在经 nginx 访问时成立，用 NGINX=1 显式开启：
#     NGINX=1 BASE=http://127.0.0.1:80 scripts/smoke_auth.sh
# 直连 Flask 时跳过并打印一行，避免它看起来像是通过了。
NGINX="${NGINX:-0}"
JAR="$TD/anon.jar"
rm -f "$JAR"

req "$BASE/dashboard.html"
expect_status "未登录 /dashboard.html → 302" 302
expect_in     "302 指向登录页" "Location:/login.html" header

req "$BASE/index.html"
expect_status "未登录 /index.html → 302" 302

req "$BASE/pitch_comparison.html"
expect_status "未登录 /pitch_comparison.html → 302" 302

req "$BASE/login.html"
expect_status "登录页公开 → 200" 200
expect_in     "登录页有用户名输入框" 'id="username"'
expect_in     "登录页有密码输入框" 'id="password"'
expect_in     "登录页提交到 A1 接口" "/api/auth/login"

# 回归闸门：页面鉴权不得波及接口契约。这两条一旦失败，说明 401 被改成了
# 302，A 组接口的所有消费方（前端 fetch 判断 r.ok）会当场失效。
req "$BASE/api/auth/me"
expect_status "未登录 /api/auth/me 仍是 401（非 302）" 401
expect_code   "A3 code 仍为 401" 401

# 静态资源不受影响
if [ "$NGINX" = "1" ]; then
  req "$BASE/static/echarts.min.js"
  expect_status "静态资源无需登录 → 200" 200
else
  echo "  · 跳过「静态资源无需登录」——该断言只对 nginx 层成立，需 NGINX=1"
fi

# 登录后页面应放行
JAR="$JAR_T"
post_json "/api/auth/login" '{"username":"teacher01","password":"xiyun@2026"}'
expect_status "重新登录 teacher01 → 200" 200

req "$BASE/dashboard.html"
expect_status "登录后 /dashboard.html → 200" 200
expect_in     "返回的是看板页面正文" "班级看板"
expect_in     "页面已注入登录脚本" "/api/auth/me"
expect_in     "页面已注入登出脚本" "/api/auth/logout"

req "$BASE/index.html"
expect_status "登录后 /index.html → 200" 200

req "$BASE/pitch_comparison.html"
expect_status "登录后 /pitch_comparison.html → 200" 200

# 登出后立刻失效
req -X POST "$BASE/api/auth/logout"
expect_status "登出 → 200" 200
req "$BASE/dashboard.html"
expect_status "登出后 /dashboard.html → 302" 302

echo
if [ "$FAIL" -eq 0 ]; then
  echo "$(green "全部通过")：$PASS 项"
  exit 0
fi
echo "$(red "失败 $FAIL 项")，通过 $PASS 项"
exit 1
