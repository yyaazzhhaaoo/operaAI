#!/usr/bin/env bash
# 戏韵AI — 摸底测试 J1–J3 + skip 冒烟测试
#
# 用法（项目根目录）：
#     scripts/smoke_cat.sh
#
# 前置：后端已启动、默认 Celery worker 已启动、已执行 scripts/seed_cat_questions.py。
# ⚠️ 非只读：会清空 stu002（students.id=56）的 bkt_history 并写入测试记录。
set -u

BASE="${BASE:-http://127.0.0.1:8877}"
PY="${PY:-python3}"
APP_PY="${APP_PY:-.venv/bin/python}"
PW="xiyun@2026"

TD="$(mktemp -d)"
cleanup() { rm -rf "$TD"; }
trap cleanup EXIT

JAR="$TD/stu.jar"
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

jget() {
  printf '%s' "$BODY" | "$PY" -c '
import json, sys
try:
    cur = json.load(sys.stdin)
    if isinstance(cur, dict) and "code" in cur and "data" in cur:
        cur = cur["data"]
    for k in sys.argv[1].split("."):
        cur = cur[int(k)] if isinstance(cur, list) else cur[k]
except Exception:
    cur = ""
print(cur if cur is not None else "")
' "$1"
}

echo "== 准备：清空 stu002 的 BKT =="
"$APP_PY" - <<'PY'
from sqlalchemy import delete
from app.db import session_scope
from app.models import BktHistory
with session_scope() as db:
    db.execute(delete(BktHistory).where(BktHistory.student_id == 56))
PY

echo "== 登录 =="
req -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"stu002\",\"password\":\"$PW\"}"
[ "$STATUS" = "200" ] && ok "stu002 登录" || bad "stu002 登录" "$STATUS $BODY"

echo "== skip =="
req -X POST "$BASE/api/cat/skip"
[ "$STATUS" = "200" ] && ok "skip 200" || bad "skip 200" "$STATUS $BODY"
[ "$(jget created)" = "5" ] && ok "skip 写入 5 行" || bad "skip 写入 5 行" "$BODY"
[ "$(jget profile.0.p_l)" = "0.35" ] && ok "skip 默认 P(L)=0.35" || bad "skip 默认 P(L)" "$BODY"
req -X POST "$BASE/api/cat/skip"
[ "$(jget created)" = "0" ] && ok "skip 幂等" || bad "skip 幂等" "$BODY"

echo "== J1 =="
req "$BASE/api/cat/questions"
[ "$STATUS" = "200" ] && ok "J1 200" || bad "J1 200" "$STATUS $BODY"
[ "$(jget questions.0.segment_id)" = "207" ] && ok "首题 segment_id=207" || bad "首题 segment_id" "$BODY"
[ -n "$(jget questions.0.audio_url)" ] && ok "首题有 audio_url" || bad "首题 audio_url" "$BODY"

echo "== 上传样例音频 =="
AUDIO=$("$APP_PY" - <<'PY'
from sqlalchemy import select
from app.db import session_scope
from app.models import AudioFile, Segment
with session_scope() as db:
    seg = db.scalar(select(Segment).where(
        Segment.title == "辕门外三声炮如同雷震",
        Segment.audio_id.is_not(None),
    ).order_by(Segment.demo_id.desc()).limit(1))
    audio = db.get(AudioFile, seg.audio_id)
    print("uploads/" + audio.file_path)
PY
)
[ -f "$AUDIO" ] && ok "样例音频存在" || bad "样例音频" "$AUDIO"
req -X POST "$BASE/api/audio/upload" -F "audio=@$AUDIO;filename=cat_smoke.wav"
AUDIO_ID=$(jget file_id)
[ -n "$AUDIO_ID" ] && ok "B1 上传 file_id=$AUDIO_ID" || bad "B1 上传" "$STATUS $BODY"

echo "== J2 =="
req -X POST "$BASE/api/cat/submit" -F "segment_id=207" -F "audio_id=$AUDIO_ID" -F "duration_sec=12.0"
TASK_ID=$(jget task_id)
[ -n "$TASK_ID" ] && ok "J2 task_id=$TASK_ID" || bad "J2" "$STATUS $BODY"

echo "== B3 轮询 =="
STATUS_DONE=0
for _ in $(seq 1 120); do
  req "$BASE/api/analyze/status/$TASK_ID"
  S=$(jget status)
  [ "$S" = "done" ] && { STATUS_DONE=1; break; }
  [ "$S" = "failed" ] && break
  sleep 1
done
[ "$STATUS_DONE" = "1" ] && ok "分析完成" || bad "分析完成" "$BODY"

echo "== B4 =="
req "$BASE/api/analyze/result/$TASK_ID"
RECORD_ID=$(jget record_id)
[ -n "$RECORD_ID" ] && ok "B4 record_id=$RECORD_ID" || bad "B4 record_id" "$BODY"
[ "$(jget bkt.after.音准控制)" != "" ] && ok "B4 含 BKT" || bad "B4 含 BKT" "$BODY"

echo "== J3 =="
req "$BASE/api/cat/report/$RECORD_ID"
[ "$STATUS" = "200" ] && ok "J3 200" || bad "J3 200" "$STATUS $BODY"
[ "$(jget profile.0.skill)" = "音准控制" ] && ok "画像 5 维首项" || bad "画像首项" "$BODY"
[ "$(jget top3.2.skill)" != "" ] && ok "Top3 有 3 项" || bad "Top3" "$BODY"

echo "== 查库 =="
if RECORD_ID="$RECORD_ID" "$APP_PY" - <<'PY'
import os

from sqlalchemy import select

from app.db import session_scope
from app.models import BktHistory, PracticeRecord

record_id = int(os.environ["RECORD_ID"])
with session_scope() as db:
    rec = db.get(PracticeRecord, record_id)
    assert rec is not None and rec.source == "cat_test", rec
    rows = list(db.scalars(select(BktHistory).where(
        BktHistory.source_type == "cat_test",
        BktHistory.source_id == record_id,
    )).all())
    assert len(rows) == 5, len(rows)
print("ok")
PY
then
  ok "库内 cat_test 记录 + 5 行 BKT"
else
  bad "库内断言" "见上方 traceback"
fi

echo "== 权限 =="
JAR_T="$TD/teacher.jar"
STATUS=$(curl -s -o "$BODY_FILE" -w '%{http_code}' -c "$JAR_T" -b "$JAR_T" \
  -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"teacher01\",\"password\":\"$PW\"}")
[ "$STATUS" = "200" ] && ok "teacher01 登录" || bad "teacher01 登录" "$STATUS"
STATUS=$(curl -s -o "$BODY_FILE" -w '%{http_code}' -c "$JAR_T" -b "$JAR_T" \
  -X POST "$BASE/api/cat/skip")
[ "$STATUS" = "403" ] && ok "教师 skip 403" || bad "教师 skip 403" "$STATUS $BODY"
STATUS=$(curl -s -o "$BODY_FILE" -w '%{http_code}' -c "$JAR_T" -b "$JAR_T" \
  -X POST "$BASE/api/cat/submit" -F "segment_id=207" -F "audio_id=$AUDIO_ID")
[ "$STATUS" = "403" ] && ok "教师 J2 403" || bad "教师 J2 403" "$STATUS $BODY"

JAR_S="$TD/stu001.jar"
STATUS=$(curl -s -o "$BODY_FILE" -w '%{http_code}' -c "$JAR_S" -b "$JAR_S" \
  -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"stu001\",\"password\":\"$PW\"}")
[ "$STATUS" = "200" ] && ok "stu001 登录" || bad "stu001 登录" "$STATUS"
STATUS=$(curl -s -o "$BODY_FILE" -w '%{http_code}' -c "$JAR_S" -b "$JAR_S" \
  "$BASE/api/cat/report/$RECORD_ID")
[ "$STATUS" = "403" ] && ok "学生查他人报告 403" || bad "学生查他人报告 403" "$STATUS $BODY"

req "$BASE/api/cat/report/99999999"
[ "$STATUS" = "404" ] && ok "未知 record 404" || bad "未知 record 404" "$STATUS $BODY"

echo
printf '通过 %s，失败 %s\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
