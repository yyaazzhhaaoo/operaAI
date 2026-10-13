#!/usr/bin/env bash
# 戏韵AI — E 组 AI 教练接口冒烟测试（《5-接口清单-V1.0》2.5 节 E1–E3 / 模块3）
#
# 用法（在项目根目录执行）：
#     scripts/smoke_coach.sh                              # 直连后端 8877
#     BASE=http://127.0.0.1:80 scripts/smoke_coach.sh     # 经 nginx（顺带验证反代）
#
# 前置：后端已启动、**内网 LLM 可达**、数据库已灌 seed.sql。
#     .venv/bin/python app-d.py &
#
# 不依赖 jq（本机没装）：JSON 解析交给 python3 标准库。
# 任一场景不符即打印明细并以退出码 1 结束，风格同 scripts/check_db.py，可接进 CI。
#
# ⚠️ 本脚本会真实调用内网模型（每轮约 2–3 秒），并往 chat_messages 写两轮记录。
#    E2 部分因此是**非只读**的，但可重复执行——断言不依赖库里原有条数。
#
# 账号：s01（users.id=50 → students.id=48 李小燕，有 8 个技法的 BKT 数据）为学生侧主用；
#       teacher01 验 403；stu001（students.id=2，无任何教学数据）验空态。
set -u

BASE="${BASE:-http://127.0.0.1:8877}"
PY="${PY:-python3}"
PW="xiyun@2026"

TD="$(mktemp -d)"
cleanup() { rm -rf "$TD"; }
trap cleanup EXIT

JAR_T="$TD/teacher.jar"     # teacher01 的 cookie
JAR_S="$TD/s01.jar"         # s01 的 cookie
JAR_A="$TD/anon.jar"        # 从不登录，用来验 401
JAR="$JAR_A"
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

echo "── 1. 鉴权门 ──────────────────────────────────"
JAR="$JAR_A"
req "$BASE/api/coach/context/48"
expect_status "E1 未登录 → 401" 401
expect_code   "E1 未登录 code=401" 401

# 本人便捷入口：无 id，页面登进来时用它探出 students.id（前端唯一入口，必须验）
req "$BASE/api/coach/context/me"
expect_status "E1 /me 未登录 → 401" 401

JAR="$JAR_T"
post_json "/api/auth/login" "{\"username\":\"teacher01\",\"password\":\"$PW\"}"
expect_status "teacher01 登录 → 200" 200
req "$BASE/api/coach/context/48"
expect_status "E1 教师 → 403" 403
req "$BASE/api/coach/context/me"
expect_status "E1 /me 教师 → 403" 403
# 教师是被路由上的 @student_required 挡的，文案是「需要学生权限」；
# 不是 service 里那句「AI 教练仅学生可用」——那句要到「是学生、但 students
# 表里查不到档案」的账号才会出现。库里现在没有这种账号了（stu002 2026-10-13
# 已补上档案），要复现得手工把某人的 students 行删掉。
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

# /me 必须与带 id 的那条回同一份数据——前端正是靠它的 student.id 去调 E2/E3
req "$BASE/api/coach/context/me"
expect_status "E1 /me 本人 → 200" 200
expect_code   "E1 /me code=0" 0
expect_in     "E1 /me 同样是李小燕" "李小燕"
expect_in     "E1 /me 报回 student.id=48" '"id":48'

echo
echo "── 3. E1 空态（stu001，students.id=2 无教学数据）──"
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
# 变量紧跟中文时必须写成 ${VAR}：macOS 自带 bash 3.2 解析 "$VAR）" 时会把
# 「）」的第一个字节当成变量名的一部分，报 `STRATEGY?: unbound variable`。
STRATEGY=$(jget data.strategy)
case "$STRATEGY" in
  引导|提示|鼓励|降难度) ok "E2 strategy 在枚举内（${STRATEGY}）" ;;
  *) bad "E2 strategy 越界" "$STRATEGY" ;;
esac
EMOTION=$(jget data.emotion)
case "$EMOTION" in
  positive|neutral|concerned) ok "E2 emotion 在枚举内（${EMOTION}）" ;;
  *) bad "E2 emotion 越界" "$EMOTION" ;;
esac

post_json "/api/coach/chat" '{"student_id":48,"message":""}'
expect_status "E2 空 message → 422" 422
expect_in     "空 message 报错中文化" "长度不能少于 1 个字符"

# 挫败表达应被模型识别为鼓励模式
post_json "/api/coach/chat" '{"student_id":48,"message":"太难了，算了，不想练"}'
expect_status "E2 挫败表达 → 200" 200
S2=$(jget data.strategy)
if [ "$S2" = "鼓励" ] || [ "$S2" = "降难度" ]; then
  ok "挫败表达触发鼓励/降难度（${S2}）"
else
  bad "挫败表达应切鼓励模式" "实际 strategy=$S2"
fi

echo
echo "── 5. E3 历史 ─────────────────────────────────"
req "$BASE/api/coach/history/48?limit=3"
expect_status "E3 limit=3 → 200" 200
expect_code   "E3 code=0" 0
expect_not_in "历史不暴露 context_snapshot" "context_snapshot"

req "$BASE/api/coach/history/48?limit=abc"
expect_status "E3 非法 limit → 200（回落默认值，不 500）" 200

req "$BASE/api/coach/history/48"
expect_status "E3 无 limit → 200" 200

echo
echo "── 6. 对话确实落了库 ──────────────────────────"
# 上面刚写过 2 轮（各 user+assistant 两条），E3 至少能读回 4 条
COUNT=$(printf '%s' "$BODY" | "$PY" -c 'import json,sys; print(len(json.load(sys.stdin)["data"]))')
if [ "$COUNT" -ge 4 ]; then ok "E3 读回 $COUNT 条（含本次写入）"; else bad "E3 条数偏少" "$COUNT"; fi

echo
if [ "$FAIL" -eq 0 ]; then
  echo "$(green "全部通过")：$PASS 项"
  exit 0
fi
echo "$(red "失败 $FAIL 项")，通过 $PASS 项"
exit 1
