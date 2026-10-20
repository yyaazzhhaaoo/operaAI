#!/usr/bin/env bash
# 戏韵AI — 示范解析 + 分段音频 + 跟唱对比 全链路验收
#
# 用法（项目根目录）：
#     scripts/smoke_demo_segment.sh
#     BASE=http://127.0.0.1:80 scripts/smoke_demo_segment.sh
#
# 前置：
#   1. Flask 已启动：.venv/bin/python app-d.py
#   2. 默认 Celery worker 已起（D1/B2 分析）：
#      .venv/bin/celery -A app.worker:celery_app worker -n default@%h --concurrency=2
#   3. Demucs worker 已起（-Q demucs，解析）：
#      .venv/bin/celery -A app.worker:celery_app worker -Q demucs -n demucs@%h --concurrency=1
#   4. 活库已执行 segments.audio_id 的 ALTER TABLE
#
# ⚠️ 解析单条约 8–15 分钟，脚本默认最多等 25 分钟。
set -u

BASE="${BASE:-http://127.0.0.1:8877}"
PY="${PY:-python3}"
AUDIO_FILE="${AUDIO_FILE:-uploads/demos/muguaying_yuanmenwai.wav}"
PARSE_MAX="${PARSE_MAX:-300}"          # 300 × 5s = 25 分钟
ANALYZE_MAX="${ANALYZE_MAX:-120}"      # 120 × 2s = 4 分钟

TD="$(mktemp -d)"
cleanup() { rm -rf "$TD"; }
trap cleanup EXIT

TEACHER_JAR="$TD/teacher.jar"
STUDENT_JAR="$TD/student.jar"
BODY_FILE="$TD/body.json"
STATUS=""
BODY=""

PASS=0
FAIL=0
red()   { printf '\033[31m%s\033[0m' "$1"; }
green() { printf '\033[32m%s\033[0m' "$1"; }
ok()    { PASS=$((PASS + 1)); printf '  %s %s\n' "$(green ✓)" "$1"; }
bad()   { FAIL=$((FAIL + 1)); printf '  %s %s —— %s\n' "$(red ✗)" "$1" "$2"; }

req() {
  STATUS=$(curl -s -o "$BODY_FILE" -w '%{http_code}' "$@")
  BODY=$(cat "$BODY_FILE")
  if [ "$STATUS" = "000" ]; then
    echo "$(red "无法连接 $BASE") —— 后端没起？" >&2
    exit 1
  fi
}

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

login() {
  local jar="$1" user="$2"
  req -c "$jar" -b "$jar" -X POST -H 'Content-Type: application/json' \
    -d "{\"username\":\"$user\",\"password\":\"xiyun@2026\"}" "$BASE/api/auth/login"
  [ "$STATUS" = "200" ] || { echo "登录 $user 失败：HTTP $STATUS $BODY" >&2; exit 1; }
}

echo "== 1. 教师登录并上传示范 =="
login "$TEACHER_JAR" teacher01
req -c "$TEACHER_JAR" -b "$TEACHER_JAR" -X POST \
  -F "audio=@$AUDIO_FILE" -F "title=验收-分段音频-$(date +%s)" \
  -F "access=public" "$BASE/api/demo/library/upload"
DEMO_ID=$(jget data.demo_id)
TASK_ID=$(jget data.task_id)
if [ -n "$DEMO_ID" ]; then
  ok "上传成功 demo_id=$DEMO_ID task_id=$TASK_ID"
else
  bad "上传失败" "HTTP $STATUS $BODY"
fi

echo "== 2. 轮询解析状态（最多 $((PARSE_MAX * 5)) 秒）=="
ST=""
for _ in $(seq 1 "$PARSE_MAX"); do
  req -c "$TEACHER_JAR" -b "$TEACHER_JAR" "$BASE/api/demo/library/$DEMO_ID/parse/status"
  ST=$(jget data.status)
  [ "$ST" = "parsed" ] && break
  [ "$ST" = "error" ] && break
  sleep 5
done
if [ "$ST" = "parsed" ]; then
  ok "解析完成：$(jget data.message)"
else
  bad "解析未完成" "status=$ST message=$(jget data.message)"
fi

echo "== 3. 校验分段与音频 URL =="
req -c "$TEACHER_JAR" -b "$TEACHER_JAR" "$BASE/api/demos/$DEMO_ID/segments"
SEG_COUNT=$(printf '%s' "$BODY" | "$PY" -c 'import json,sys; print(len(json.load(sys.stdin)["data"]))')
if [ "$SEG_COUNT" -gt 0 ]; then ok "分段数=$SEG_COUNT"; else bad "没有分段" "$BODY"; fi
SEG_ID=$(jget data.0.id)
SEG_URL=$(jget data.0.url)
SEG_DUR=$(jget data.0.duration)
if [ -n "$SEG_URL" ]; then ok "第 1 段 url=$SEG_URL"; else bad "第 1 段没有 url" "$BODY"; fi

echo "== 4. 学生登录并下载分段音频（验证 public 可听）=="
login "$STUDENT_JAR" stu001
SEG_FILE="$TD/seg.wav"
STATUS=$(curl -s -o "$SEG_FILE" -w '%{http_code}' -c "$STUDENT_JAR" -b "$STUDENT_JAR" "$BASE$SEG_URL")
if [ "$STATUS" = "200" ]; then ok "分段音频可下载"; else bad "分段音频下载失败" "HTTP $STATUS"; fi
if "$PY" - "$SEG_FILE" "$SEG_DUR" <<'PY'
import sys, librosa
path, expect = sys.argv[1], float(sys.argv[2])
got = librosa.get_duration(path=path)
assert abs(got - expect) < 0.15, f"时长不符：文件 {got:.3f}s，字段 {expect}s"
print(f"  \033[32m✓\033[0m 时长一致：{got:.3f}s")
PY
then
  PASS=$((PASS + 1))
else
  bad "分段音频时长不符" "见上"
fi

echo "== 5. 学生上传录音并提交跟唱分析 =="
req -c "$STUDENT_JAR" -b "$STUDENT_JAR" -X POST \
  -F "audio=@$SEG_FILE" "$BASE/api/audio/upload"
AUDIO_ID=$(jget data.file_id)
if [ -n "$AUDIO_ID" ]; then ok "学生录音上传 file_id=$AUDIO_ID"; else bad "学生录音上传失败" "$BODY"; fi

req -c "$STUDENT_JAR" -b "$STUDENT_JAR" -X POST \
  -F "segment_id=$SEG_ID" -F "audio_id=$AUDIO_ID" \
  -F "duration_sec=$SEG_DUR" "$BASE/api/practice/submit"
PRACTICE_TASK=$(jget data.task_id)
if [ -n "$PRACTICE_TASK" ]; then ok "D1 提交 task_id=$PRACTICE_TASK"; else bad "D1 提交失败" "$BODY"; fi

echo "== 6. 轮询分析结果 =="
AST=""
for _ in $(seq 1 "$ANALYZE_MAX"); do
  req -c "$STUDENT_JAR" -b "$STUDENT_JAR" "$BASE/api/analyze/status/$PRACTICE_TASK"
  AST=$(jget data.status)
  [ "$AST" = "done" ] && break
  [ "$AST" = "failed" ] && break
  sleep 2
done
if [ "$AST" = "done" ]; then ok "分析完成"; else bad "分析未完成" "status=$AST message=$(jget data.message)"; fi

req -c "$STUDENT_JAR" -b "$STUDENT_JAR" "$BASE/api/analyze/result/$PRACTICE_TASK"
OVERALL=$(jget data.overall)
DIM_COUNT=$(printf '%s' "$BODY" | "$PY" -c 'import json,sys; print(len(json.load(sys.stdin)["data"]["dimensions"]))')
if [ -n "$OVERALL" ]; then ok "综合评分=$OVERALL"; else bad "结果缺 overall" "$BODY"; fi
if [ "$DIM_COUNT" = "5" ]; then ok "五维齐全"; else bad "维度数=$DIM_COUNT" "$BODY"; fi

echo
echo "通过 $PASS 项，失败 $FAIL 项"
[ "$FAIL" -eq 0 ] || exit 1
