#!/usr/bin/env bash
# 戏韵AI — F2 布置新作业冒烟测试（`POST /api/homeworks`，功能 4.2）
#
# 用法（在项目根目录执行）：
#     scripts/smoke_homework_create.sh                          # 直连后端 8877
#     BASE=http://127.0.0.1:80 scripts/smoke_homework_create.sh # 经 nginx
#
# 前置：后端已启动、数据库已灌 seed.sql，且库里至少有一个带分段的曲目
# （C1 的 segment_count > 0）。
#     .venv/bin/python app-d.py &
#
# 不依赖 jq（本机没装）：JSON 解析交给 python3 标准库。
# 任一场景不符即打印明细并以退出码 1 结束，风格同 scripts/smoke_auth.sh。
#
# ⚠️ 会真实写入 homeworks 行。每条成功的布置都会记下 id，脚本退出时（含中断）
# 由 EXIT trap 直连数据库删除，因此可重复执行、不留脏数据。
# 最后一条「落库校验」直连数据库（读 .env 的 DATABASE_URL），与 BASE 指向哪台
# 前端无关——两者必须指向同一套环境。
set -u

BASE="${BASE:-http://127.0.0.1:8877}"
PY="${PY:-python3}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# 落库校验与清理要 import app（SQLAlchemy/psycopg2），必须用项目 venv。
VENV_PY="${VENV_PY:-$ROOT/.venv/bin/python}"
[ -x "$VENV_PY" ] || VENV_PY="$PY"

TD="$(mktemp -d)"
# 本次真实写入的 homeworks.id（空格分隔），供 EXIT trap 清理。
# 用字符串而不是数组：`set -u` 下旧版 bash 展开空数组会报 unbound variable。
CREATED_IDS=""

cleanup() {
  local rc=$?
  if [ -n "$CREATED_IDS" ]; then
    ( cd "$ROOT" && "$VENV_PY" - $CREATED_IDS <<'PY'
import sys
from app.db import session_scope
from app.models import Homework

ids = [int(x) for x in sys.argv[1:]]
with session_scope() as s:
    gone = []
    for hid in ids:
        row = s.get(Homework, hid)
        if row is not None:
            s.delete(row)
            gone.append(hid)
    print("已删除测试作业：", gone)
PY
    ) || echo "⚠️ 清理失败，请手动删除 homeworks id=$CREATED_IDS" >&2
  fi
  rm -rf "$TD"
  exit "$rc"
}
trap cleanup EXIT

JAR_T="$TD/teacher.jar"
JAR_S="$TD/student.jar"
JAR_A="$TD/anon.jar"
JAR="$JAR_T"
HDR="$TD/last.headers"
BODY_FILE="$TD/last.body"

PASS=0
FAIL=0
STATUS=""
BODY=""
BODY_N=""

red()   { printf '\033[31m%s\033[0m' "$1"; }
green() { printf '\033[32m%s\033[0m' "$1"; }
ok()    { PASS=$((PASS + 1)); printf '  %s %s\n' "$(green ✓)" "$1"; }
bad()   { FAIL=$((FAIL + 1)); printf '  %s %s —— %s\n' "$(red ✗)" "$1" "$2"; }

req() {
  STATUS=$(curl -s -D "$HDR" -o "$BODY_FILE" -c "$JAR" -b "$JAR" -w '%{http_code}' "$@")
  BODY=$(cat "$BODY_FILE")
  BODY_N=$(printf '%s' "$BODY" | tr -d ' \n\t')
  if [ "$STATUS" = "000" ]; then
    echo "$(red "无法连接 $BASE") —— 后端没起？先执行：.venv/bin/python app-d.py" >&2
    exit 1
  fi
}

# 从 JSON 正文按点号路径取值（如 data.0.id），取不到返回空串。替代 jq。
jget() {
  printf '%s' "$BODY" | "$PY" -c '
import json, sys
try:
    cur = json.load(sys.stdin)
    for k in sys.argv[1].split("."):
        cur = cur[int(k)] if isinstance(cur, list) else cur[k]
except Exception:
    cur = ""
print("" if cur is None else cur)
' "$1"
}

expect_status() {
  if [ "$STATUS" = "$2" ]; then ok "$1"; else bad "$1" "期望 HTTP ${2}，实际 ${STATUS}；body=$BODY"; fi
}

expect_code() {
  local got
  got=$(jget code)
  if [ "$got" = "$2" ]; then ok "$1"; else bad "$1" "期望 code=${2}，实际 code=${got}；body=$BODY"; fi
}

expect_eq() {       # expect_eq <名称> <实际> <期望>
  if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "期望「$3」，实际「$2」；body=$BODY"; fi
}

expect_in() {
  local needle
  needle=$(printf '%s' "$2" | tr -d ' \n\t')
  case "$BODY_N" in
    *"$needle"*) ok "$1" ;;
    *) bad "$1" "找不到「$2」；body=$BODY" ;;
  esac
}

post_json() {
  req -X POST -H 'Content-Type: application/json' -d "$2" "$BASE$1"
}

# —— 测试所需的日期与数据：全部取自真实接口/数据库，不写死 ——
read -r TODAY FUTURE PAST <<EOF
$("$PY" -c 'from datetime import datetime, timedelta; from zoneinfo import ZoneInfo
t = datetime.now(ZoneInfo("Asia/Shanghai")).date()
print(t, t + timedelta(days=7), t - timedelta(days=1))')
EOF
LONG_TITLE=$("$PY" -c 'print("长" * 101)')

echo "冒烟目标：$BASE"
echo

echo "── 1. 登录与数据准备 ──────────────────────────"
JAR="$JAR_T"
post_json "/api/auth/login" '{"username":"teacher01","password":"xiyun@2026"}'
expect_status "teacher01 登录 → 200" 200
TEACHER_ID=$(jget data.id)

# 选第一个带分段的曲目（C1 不保证顺序，按 id 升序取第一个可复现）
req "$BASE/api/demos"
expect_status "C1 曲目列表 → 200" 200
read -r DEMO_ID DEMO_TITLE <<EOF
$(printf '%s' "$BODY" | "$PY" -c '
import json, sys
rows = [r for r in json.load(sys.stdin).get("data", []) if r.get("segment_count", 0) > 0]
rows.sort(key=lambda r: r["id"])
print(rows[0]["id"], rows[0]["title"]) if rows else print("", "")
')
EOF
if [ -z "$DEMO_ID" ]; then
  echo "$(red "库里没有带分段的曲目，无法覆盖 segment_ids 分支") —— 先跑 scripts/seed 或上传一份示范" >&2
  exit 1
fi
echo "  · 用曲目 id=$DEMO_ID（$DEMO_TITLE），截止日 $FUTURE，今天 $TODAY"

req "$BASE/api/demos/$DEMO_ID/segments"
expect_status "C2 分段列表 → 200" 200
read -r SEG1 SEG2 <<EOF
$(printf '%s' "$BODY" | "$PY" -c '
import json, sys
rows = json.load(sys.stdin).get("data", [])
ids = [r["id"] for r in rows if r.get("id") is not None]
print(ids[0], ids[1] if len(ids) > 1 else ids[0])
')
EOF
expect_eq "C2 至少返回一段" "$([ -n "$SEG1" ] && echo yes)" "yes"
# 该曲目只有一段时别再塞第二段——schema 会按「唱段不能重复」回 422
if [ "$SEG1" = "$SEG2" ]; then SEG_LIST="[$SEG1]"; else SEG_LIST="[$SEG1,$SEG2]"; fi

# 一个不属于该曲目的分段 id：优先取别的曲目的真实分段，取不到用一个大号兜底
SEG_ALIEN=$( ( cd "$ROOT" && "$VENV_PY" - "$DEMO_ID" <<'PY'
import sys
from app.db import session_scope
from app.models import Segment
demo_id = int(sys.argv[1])
with session_scope() as s:
    row = s.query(Segment).filter(Segment.demo_id != demo_id, Segment.id.isnot(None)).first()
    print(row.id if row else 999999999)
PY
) )

echo
echo "── 2. 权限 ────────────────────────────────────"
JAR="$JAR_A"
post_json "/api/homeworks" "{\"title\":\"冒烟作业\",\"demo_id\":$DEMO_ID,\"deadline\":\"$FUTURE\"}"
expect_status "未登录 → 401" 401
expect_code   "未登录 code=401" 401

JAR="$JAR_S"
post_json "/api/auth/login" '{"username":"stu001","password":"xiyun@2026"}'
expect_status "stu001 登录 → 200" 200
post_json "/api/homeworks" "{\"title\":\"冒烟作业\",\"demo_id\":$DEMO_ID,\"deadline\":\"$FUTURE\"}"
expect_status "学生身份 → 403" 403
expect_code   "学生身份 code=403" 403

echo
echo "── 3. 入参校验（与前端表单严格对齐）──────────"
JAR="$JAR_T"
# 缺少必填字段
post_json "/api/homeworks" "{\"demo_id\":$DEMO_ID,\"deadline\":\"$FUTURE\"}"
expect_status "缺 title → 422" 422
expect_in     "报错点名 title" "title"
post_json "/api/homeworks" "{\"title\":\"冒烟作业\",\"deadline\":\"$FUTURE\"}"
expect_status "缺 demo_id → 422" 422
post_json "/api/homeworks" "{\"title\":\"冒烟作业\",\"demo_id\":$DEMO_ID}"
expect_status "缺 deadline → 422" 422
# 格式
post_json "/api/homeworks" "{\"title\":\"   \",\"demo_id\":$DEMO_ID,\"deadline\":\"$FUTURE\"}"
expect_status "title 全空白 → 422" 422
expect_in     "空白标题文案" "作业标题不能为空"
post_json "/api/homeworks" "{\"title\":\"$LONG_TITLE\",\"demo_id\":$DEMO_ID,\"deadline\":\"$FUTURE\"}"
expect_status "title 101 字符 → 422" 422
expect_in     "长度报错中文化" "长度不能超过 100 个字符"
post_json "/api/homeworks" "{\"title\":\"冒烟作业\",\"demo_id\":$DEMO_ID,\"deadline\":\"$PAST\"}"
expect_status "截止日早于今天 → 422" 422
expect_in     "截止日报错文案" "截止日期不能早于今天"
post_json "/api/homeworks" "{\"title\":\"冒烟作业\",\"demo_id\":999999999,\"deadline\":\"$FUTURE\"}"
expect_status "曲目不存在 → 404" 404
expect_in     "曲目不存在文案" "曲目不存在"
post_json "/api/homeworks" "{\"title\":\"冒烟作业\",\"demo_id\":$DEMO_ID,\"segment_ids\":[$SEG_ALIEN],\"deadline\":\"$FUTURE\"}"
expect_status "唱段不属于该曲目 → 422" 422
expect_in     "跨曲目唱段文案" "唱段不属于该曲目"
post_json "/api/homeworks" "{\"title\":\"冒烟作业\",\"demo_id\":$DEMO_ID,\"segment_ids\":[$SEG1,$SEG1],\"deadline\":\"$FUTURE\"}"
expect_status "唱段重复 → 422" 422
expect_in     "重复唱段文案" "唱段不能重复"
post_json "/api/homeworks" "{\"title\":\"冒烟作业\",\"demo_id\":$DEMO_ID,\"focus_skills\":[\"不存在的技法\"],\"deadline\":\"$FUTURE\"}"
expect_status "未知技法 → 422" 422
expect_in     "未知技法文案" "不支持的重点技法"
post_json "/api/homeworks" "{\"title\":\"冒烟作业\",\"demo_id\":$DEMO_ID,\"focus_skills\":[\"颤音\",\"颤音\"],\"deadline\":\"$FUTURE\"}"
expect_status "技法重复 → 422" 422
expect_in     "重复技法文案" "重点技法不能重复"

echo
echo "── 4. 成功路径 ────────────────────────────────"
# 4a. 指定唱段 + 多个技法
post_json "/api/homeworks" "{\"title\":\" 冒烟作业-指定唱段 \",\"demo_id\":$DEMO_ID,\"segment_ids\":$SEG_LIST,\"focus_skills\":[\"音准控制\",\"颤音\",\"归韵咬字\"],\"deadline\":\"$FUTURE\"}"
expect_status "指定唱段布置 → 200" 200
expect_code   "指定唱段 code=0" 0
HW1=$(jget data.homework_id)
if [ -n "$HW1" ] && [ "$HW1" -gt 0 ] 2>/dev/null; then
  CREATED_IDS="$CREATED_IDS $HW1"
  ok "返回自增 homework_id=$HW1"
else
  bad "返回自增 homework_id" "实际「$HW1」；body=$BODY"
fi
expect_eq "出参 title 已去首尾空格" "$(jget data.title)" "冒烟作业-指定唱段"
expect_eq "出参 status=ongoing"    "$(jget data.status)" "ongoing"
expect_eq "出参 submitted_count=0" "$(jget data.submitted_count)" "0"
expect_eq "出参 pending=0"         "$(jget data.pending_review_count)" "0"
expect_eq "出参 progress=0"        "$(jget data.progress)" "0.0"
expect_eq "出参 deadline"          "$(jget data.deadline)" "$FUTURE"
expect_eq "出参 demo_title"        "$(jget data.demo_title)" "$DEMO_TITLE"
expect_in "出参带 total 分母"      '"total":'

# 4b. 不选唱段 = 按整曲布置
post_json "/api/homeworks" "{\"title\":\"冒烟作业-整曲\",\"demo_id\":$DEMO_ID,\"segment_ids\":[],\"focus_skills\":[],\"deadline\":\"$FUTURE\"}"
expect_status "整曲布置（segment_ids 空）→ 200" 200
HW2=$(jget data.homework_id)
if [ -n "$HW2" ] && [ "$HW2" -gt 0 ] 2>/dev/null; then CREATED_IDS="$CREATED_IDS $HW2"; fi

echo
echo "── 5. 落库校验 ────────────────────────────────"
# 直连库看 JSONB 是否原样写入（F1 的出参不含这两列，接口层断言不到）
if [ -n "$HW1" ] && [ -n "$HW2" ]; then
  DB_CHECK=$( ( cd "$ROOT" && "$VENV_PY" - "$HW1" "$HW2" "$TEACHER_ID" "$SEG1" "$SEG2" <<'PY'
import json, sys
from app.db import session_scope
from app.models import Homework
hw1, hw2, teacher_id, seg1, seg2 = (int(x) for x in sys.argv[1:6])
expect_segments = [seg1] if seg1 == seg2 else [seg1, seg2]
with session_scope() as s:
    a, b = s.get(Homework, hw1), s.get(Homework, hw2)
    print(json.dumps({
        "found": bool(a and b),
        "teacher_ok": bool(a and a.teacher_id == teacher_id),
        "segments_ok": bool(a and a.segment_ids == expect_segments),
        "skills_ok": bool(a and a.focus_skills == ["音准控制", "颤音", "归韵咬字"]),
        "whole_song_ok": bool(b and b.segment_ids == [] and b.focus_skills == []),
        "status_ok": bool(a and a.status == "open"),
    }))
PY
  ) )
  BODY="$DB_CHECK"
  BODY_N=$(printf '%s' "$BODY" | tr -d ' \n\t')
  expect_eq "两行都已落库"          "$(jget found)" "True"
  expect_eq "teacher_id 取自会话"   "$(jget teacher_ok)" "True"
  expect_eq "segment_ids 原样落库"  "$(jget segments_ok)" "True"
  expect_eq "focus_skills 原样落库" "$(jget skills_ok)" "True"
  expect_eq "空数组按整曲落库"      "$(jget whole_song_ok)" "True"
  expect_eq "status 落库为 open"    "$(jget status_ok)" "True"
else
  bad "落库校验" "成功路径没有拿到 homework_id，跳过落库校验"
fi

echo
echo "── 6. F1 列表回显 ─────────────────────────────"
req "$BASE/api/homeworks"
expect_status "F1 作业列表 → 200" 200
expect_in "新作业出现在 F1 列表" "\"homework_id\":$HW1,"
expect_in "整曲作业也在列表中"   "\"homework_id\":$HW2,"

echo
if [ "$FAIL" -eq 0 ]; then
  echo "$(green "全部通过")：$PASS 项"
  exit 0
fi
echo "$(red "失败 $FAIL 项")，通过 $PASS 项"
exit 1
