#!/usr/bin/env bash
# 戏韵AI — 学生提交作业冒烟测试（F3 `POST /api/homeworks/<id>/submit`）
#
# 用法（在项目根目录执行）：
#     scripts/smoke_homework_submit.sh
#     BASE=http://127.0.0.1:80 scripts/smoke_homework_submit.sh
#
# 前置（缺一不可）：
#     1. 后端已启动：.venv/bin/python app-d.py &
#     2. Celery default worker 已启动：
#        .venv/bin/celery -A app.worker:celery_app worker -n default@%h --loglevel=info --concurrency=2
#     3. 数据库已灌 seed.sql；库里有一个绑了教师轨的分段
#     4. 真实测试音频：默认 $HOME/Desktop/test_audio/01_xipi_1931.wav
#
# ⚠️ 单轮约 2 分钟，链路真的跑 librosa，不是桩。
# ⚠️ 2026-10-21 起页面的动作是「先练习、再提交」：本脚本先走 D1
#    (`POST /api/practice/submit`) 练一遍、等 B3 出结果，再调 F3 归档。
#    F3 命中 practice_records 时同步返回 submission_id，不再投分析任务。
# ⚠️ 会真实写入 homeworks / submissions / practice_records / bkt_history /
#    audio_files。脚本退出时（含中断）由 EXIT trap 清理本次创建的全部数据与
#    磁盘文件，包括练习链路写入的 practice 来源 BKT 行（不清会让 stu001 的
#    掌握度被冒烟测试逐步推高）。
set -u

BASE="${BASE:-http://127.0.0.1:8877}"
PY="${PY:-python3}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PY="${VENV_PY:-$ROOT/.venv/bin/python}"
[ -x "$VENV_PY" ] || VENV_PY="$PY"
AUDIO_DIR="${AUDIO_DIR:-$HOME/Desktop/test_audio}"
AUDIO_FILE="${AUDIO_FILE:-01_xipi_1931.wav}"
POLL_INTERVAL="${POLL_INTERVAL:-2}"
POLL_MAX="${POLL_MAX:-200}"

TD="$(mktemp -d)"
CREATED_HW=""
AUDIO_IDS=""

cleanup() {
  local rc=$?
  if [ -n "$CREATED_HW" ] || [ -n "$AUDIO_IDS" ]; then
    ( cd "$ROOT" && "$VENV_PY" - "$CREATED_HW" "$AUDIO_IDS" <<'PY'
import sys
from app.common import storage
from app.db import session_scope
from app.models import AudioFile, BktHistory, Homework, PracticeRecord, Submission

hw_ids = [int(x) for x in sys.argv[1].split()] if sys.argv[1].strip() else []
audio_ids = [int(x) for x in sys.argv[2].split()] if sys.argv[2].strip() else []
with session_scope() as s:
    subs = list(s.query(Submission).filter(Submission.homework_id.in_(hw_ids)).all()) if hw_ids else []
    sub_ids = [x.id for x in subs]
    if sub_ids:
        s.query(BktHistory).filter(
            BktHistory.source_type == "homework",
            BktHistory.source_id.in_(sub_ids),
        ).delete(synchronize_session=False)
    for sub in subs:
        s.delete(sub)
    for hid in hw_ids:
        row = s.get(Homework, hid)
        if row is not None:
            s.delete(row)
    # D1 练习链路的数据：BKT 行挂的是 practice_records.id，先删 BKT 再删记录。
    # 不清的话每跑一次冒烟都会把 stu001 的掌握度往前推一格。
    recs = list(s.query(PracticeRecord).filter(PracticeRecord.audio_id.in_(audio_ids)).all()) if audio_ids else []
    rec_ids = [x.id for x in recs]
    if rec_ids:
        s.query(BktHistory).filter(
            BktHistory.source_type == "practice",
            BktHistory.source_id.in_(rec_ids),
        ).delete(synchronize_session=False)
    for rec in recs:
        s.delete(rec)
    paths = []
    for aid in audio_ids:
        row = s.get(AudioFile, aid)
        if row is not None:
            paths.append(row.file_path)
            s.delete(row)
for path in paths:
    storage.remove(path)
print("已清理测试数据：homeworks", hw_ids, "audio_files", audio_ids)
PY
    ) || echo "⚠️ 清理失败，请手动删除 homeworks id=$CREATED_HW、audio_files id=$AUDIO_IDS" >&2
  fi
  rm -rf "$TD"
  exit "$rc"
}
trap cleanup EXIT

JAR_T="$TD/teacher.jar"
JAR_S1="$TD/stu001.jar"
JAR_S2="$TD/stu002.jar"
JAR_A="$TD/anon.jar"
JAR="$JAR_A"
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

expect_eq() {
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

if [ ! -f "$AUDIO_DIR/$AUDIO_FILE" ]; then
  echo "$(red "找不到测试音频：$AUDIO_DIR/$AUDIO_FILE")" >&2
  echo "  该目录不在仓库里（.gitignore 排除），需另行获取；也可用 AUDIO_DIR=<路径> 指定" >&2
  exit 1
fi

FUTURE=$("$PY" -c 'from datetime import datetime, timedelta; from zoneinfo import ZoneInfo
print(datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=7))')

echo "冒烟目标：$BASE"
echo "测试音频：$AUDIO_DIR/$AUDIO_FILE"
echo "（本轮约 2 分钟，瓶颈是 librosa 提音高）"
echo

echo "── 1. 准备：找一条绑了教师轨的分段 ─────────────"
read -r DEMO_ID SEG_ID SEG_OTHER <<EOF
$( cd "$ROOT" && "$VENV_PY" - <<'PY'
from sqlalchemy import select
from app.db import session_scope
from app.models import Segment, TeacherDemo

with session_scope() as s:
    rows = s.execute(
        select(Segment, TeacherDemo)
        .join(TeacherDemo, TeacherDemo.id == Segment.demo_id)
        .order_by(Segment.demo_id, Segment.seq)
    ).all()
    usable = [(seg, demo) for seg, demo in rows
              if seg.audio_id is not None or demo.audio_id is not None]
    if not usable:
        print("", "", "")
    else:
        seg, demo = usable[0]
        others = [r[0].id for r in rows if r[0].demo_id == demo.id and r[0].id != seg.id]
        print(demo.id, seg.id, others[0] if others else 999999999)
PY
)
EOF
if [ -z "$DEMO_ID" ]; then
  echo "$(red "库里没有绑定教师轨的分段") —— 先上传/解析一份示范，或灌 seed.sql" >&2
  exit 1
fi
echo "  · 曲目 id=$DEMO_ID，作业唱段 id=$SEG_ID，越界唱段 id=$SEG_OTHER"

echo
echo "── 2. 教师布置作业 ────────────────────────────"
JAR="$JAR_T"
post_json "/api/auth/login" '{"username":"teacher01","password":"xiyun@2026"}'
expect_status "teacher01 登录 → 200" 200
post_json "/api/homeworks" "{\"title\":\"冒烟-学生提交作业\",\"demo_id\":$DEMO_ID,\"segment_ids\":[$SEG_ID],\"focus_skills\":[\"音准控制\",\"气息支撑\"],\"deadline\":\"$FUTURE\"}"
expect_status "F2 布置作业 → 200" 200
HW_ID=$(jget data.homework_id)
if [ -n "$HW_ID" ]; then CREATED_HW="$HW_ID"; fi
if [ -z "$HW_ID" ]; then
  echo "$(red "没拿到 homework_id，后续无法继续")" >&2
  exit 1
fi
ok "作业 id=$HW_ID"

echo
echo "── 3. 权限 ────────────────────────────────────"
JAR="$JAR_A"
req "$BASE/api/homeworks/mine"
expect_status "匿名 GET /mine → 401" 401
expect_code   "匿名 code=401" 401

JAR="$JAR_T"
req "$BASE/api/homeworks/mine"
expect_status "教师 GET /mine → 403" 403
expect_code   "教师 code=403" 403

JAR="$JAR_S1"
post_json "/api/auth/login" '{"username":"stu001","password":"xiyun@2026"}'
expect_status "stu001 登录 → 200" 200

echo
echo "── 4. 学生列表与详情 ──────────────────────────"
req "$BASE/api/homeworks/mine"
expect_status "GET /mine → 200" 200
expect_code   "列表 code=0" 0
expect_in     "新作业出现在列表" "\"homework_id\":$HW_ID,"

req "$BASE/api/homeworks/mine/$HW_ID"
expect_status "GET /mine/<id> → 200" 200
expect_eq "详情 homework_id" "$(jget data.homework_id)" "$HW_ID"
expect_eq "详情 status=todo" "$(jget data.status)" "todo"
expect_eq "详情 can_submit=true" "$(jget data.can_submit)" "True"
expect_eq "详情 overdue=false" "$(jget data.overdue)" "False"
expect_eq "可选唱段=作业指定唱段" "$(jget data.allowed_segment_ids.0)" "$SEG_ID"

req "$BASE/api/homeworks/mine/999999999"
expect_status "详情不存在 → 404" 404
expect_in     "作业不存在文案" "作业不存在"

echo
echo "── 5. F3 入参校验 ─────────────────────────────"
# 5a. 缺字段
req -X POST "$BASE/api/homeworks/$HW_ID/submit"
expect_status "缺表单字段 → 400" 400
expect_in     "报错点名 segment_id" "segment_id"

# 5b. 音频不存在
req -X POST -F "segment_id=$SEG_ID" -F "audio_id=999999999" "$BASE/api/homeworks/$HW_ID/submit"
expect_status "音频不存在 → 404" 404
expect_in     "音频不存在文案" "音频不存在"

# 5c. 用另一个学生的录音
JAR="$JAR_S2"
post_json "/api/auth/login" '{"username":"stu002","password":"xiyun@2026"}'
expect_status "stu002 登录 → 200" 200
req -X POST -F "audio=@$AUDIO_DIR/$AUDIO_FILE" "$BASE/api/audio/upload"
expect_status "stu002 B1 上传 → 200" 200
OTHER_FILE_ID=$(jget data.file_id)
if [ -n "$OTHER_FILE_ID" ]; then AUDIO_IDS="$AUDIO_IDS $OTHER_FILE_ID"; fi

JAR="$JAR_S1"
req -X POST -F "segment_id=$SEG_ID" -F "audio_id=$OTHER_FILE_ID" "$BASE/api/homeworks/$HW_ID/submit"
expect_status "用别人的录音 → 403" 403
expect_in     "越权录音文案" "只能提交本人录音"

# 5d. 越界唱段（需要先有本人录音）
req -X POST -F "audio=@$AUDIO_DIR/$AUDIO_FILE" "$BASE/api/audio/upload"
expect_status "stu001 B1 上传 → 200" 200
FILE_ID=$(jget data.file_id)
if [ -n "$FILE_ID" ]; then AUDIO_IDS="$AUDIO_IDS $FILE_ID"; fi
req -X POST -F "segment_id=$SEG_OTHER" -F "audio_id=$FILE_ID" "$BASE/api/homeworks/$HW_ID/submit"
expect_status "唱段不在作业范围 → 422" 422
expect_in     "越界唱段文案" "唱段不在本次作业范围内"
if [ -z "$FILE_ID" ]; then
  echo "$(red "没拿到 B1 file_id，无法跑成功路径")" >&2
  exit 1
fi

echo
echo "── 6. 学生先练习（D1 → B3 → B4）───────────────"
JAR="$JAR_S1"
req -X POST -F "segment_id=$SEG_ID" -F "audio_id=$FILE_ID" "$BASE/api/practice/submit"
expect_status "D1 练习提交 → 200" 200
expect_code   "D1 code=0" 0
PRACTICE_TASK=$(jget data.task_id)
if printf '%s' "$PRACTICE_TASK" | grep -qE '^[0-9a-fA-F]{8,}$'; then
  ok "D1 返回 task_id（=$PRACTICE_TASK）"
else
  bad "D1 应返回 task_id" "实际='$PRACTICE_TASK'；body=$BODY"
  exit 1
fi

echo
echo "── 7. B3 轮询（最多 $((POLL_MAX * POLL_INTERVAL)) 秒）─────"
FINAL=""
n=0
while [ "$n" -lt "$POLL_MAX" ]; do
  n=$((n + 1))
  req "$BASE/api/analyze/status/$PRACTICE_TASK"
  ST=$(jget data.status)
  if [ "$ST" = "done" ] || [ "$ST" = "failed" ]; then
    FINAL="$ST"
    printf '  · 第 %d 轮到达终态：status=%s message=%s\n' "$n" "$ST" "$(jget data.message)"
    break
  fi
  sleep "$POLL_INTERVAL"
done
expect_eq "B3 终态为 done" "$FINAL" "done"
if [ "$FINAL" != "done" ]; then
  echo "$(red "分析未完成，跳过提交与落库断言")" >&2
  exit 1
fi

req "$BASE/api/analyze/result/$PRACTICE_TASK"
expect_status "B4 → 200" 200
printf '%s' "$BODY" > "$TD/b4.json"

req "$BASE/api/practice/last/$SEG_ID"
expect_status "D3 回显最近练习 → 200" 200
expect_eq "D3 记录对应本次录音" "$(jget data.record.audio_id)" "$FILE_ID"
expect_eq "D3 记录段正确" "$(jget data.record.segment_id)" "$SEG_ID"
PRACTICE_SCORE=$(jget data.record.ai_score)
if [ -n "$PRACTICE_SCORE" ]; then
  ok "练习成绩已落库（ai_score=$PRACTICE_SCORE）"
else
  bad "练习成绩应非空" "D3 返回 record=null 或 ai_score=null；body=$BODY"
  exit 1
fi

echo
echo "── 8. 提交作业（F3 复用练习成绩）──────────────"
req -X POST -F "segment_id=$SEG_ID" -F "audio_id=$FILE_ID" "$BASE/api/homeworks/$HW_ID/submit"
expect_status "F3 提交 → 200" 200
expect_code   "F3 code=0" 0
SUB_ID=$(jget data.submission_id)
TASK_ID=$(jget data.task_id)
if printf '%s' "$SUB_ID" | grep -qE '^[0-9]+$'; then
  ok "F3 同步归档，返回 submission_id（=$SUB_ID）"
else
  bad "F3 应返回 submission_id" "实际='$SUB_ID'；body=$BODY"
  exit 1
fi
expect_eq "复用练习成绩时不返回 task_id" "$TASK_ID" ""

req -X POST -F "segment_id=$SEG_ID" -F "audio_id=$FILE_ID" "$BASE/api/homeworks/$HW_ID/submit"
expect_status "立即重复提交 → 422" 422
expect_code   "重复提交 code=422" 422
expect_in     "重复提交文案" "该作业已提交，不能重复提交"

echo
echo "── 9. 落库校验 ────────────────────────────────"
STUDENT_ID=$( cd "$ROOT" && "$VENV_PY" - <<'PY'
from sqlalchemy import select
from app.db import session_scope
from app.models import Student, User
with session_scope() as s:
    print(s.scalar(select(Student.id).join(User, User.id == Student.user_id)
                   .where(User.username == "stu001")))
PY
)
DB_CHECK=$( cd "$ROOT" && "$VENV_PY" - "$HW_ID" "$STUDENT_ID" "$SEG_ID" "$FILE_ID" <<'PY'
import json, sys
from app.db import session_scope
from app.models import BktHistory, PracticeRecord, Submission

hw_id, student_id, seg_id, audio_id = (int(x) for x in sys.argv[1:5])
with session_scope() as s:
    sub = s.query(Submission).filter(
        Submission.homework_id == hw_id,
        Submission.student_id == student_id,
    ).one_or_none()
    homework_bkt = []
    if sub is not None:
        homework_bkt = s.query(BktHistory).filter(
            BktHistory.source_type == "homework",
            BktHistory.source_id == sub.id,
        ).all()
    pr = s.query(PracticeRecord).filter(
        PracticeRecord.student_id == student_id,
        PracticeRecord.audio_id == audio_id,
    ).one_or_none()
    practice_bkt = []
    if pr is not None:
        practice_bkt = s.query(BktHistory).filter(
            BktHistory.source_type == "practice",
            BktHistory.source_id == pr.id,
        ).all()
    print(json.dumps({
        "submission_id": sub.id if sub else None,
        "found": sub is not None,
        "status": sub.status if sub else None,
        "ai_score": sub.ai_score if sub else None,
        "detail_keys": "|".join(sorted((sub.ai_detail or {}).keys())) if sub else "",
        "segment_id_ok": bool(sub and sub.segment_id == seg_id),
        "audio_id_ok": bool(sub and sub.audio_id == audio_id),
        "submitted_at_ok": bool(sub and sub.submitted_at is not None),
        "ai_score_eq_practice": bool(sub and pr and sub.ai_score == pr.ai_score),
        # 复用练习成绩只归档：BKT 在 D1 练习时已更新过，提交行不该再带一份
        "bkt_before_none": bool(sub and sub.bkt_before is None),
        "bkt_after_none": bool(sub and sub.bkt_after is None),
        "bkt_homework_rows": len(homework_bkt),
        "practice_found": pr is not None,
        "practice_segment_ok": bool(pr and pr.segment_id == seg_id),
        "practice_bkt_rows": len(practice_bkt),
        "practice_bkt_source_ok": bool(pr and all(
            r.source_type == "practice" and r.source_id == pr.id
            for r in practice_bkt)),
    }))
PY
)
BODY="$DB_CHECK"
BODY_N=$(printf '%s' "$BODY" | tr -d ' \n\t')
expect_eq "提交行已落库" "$(jget found)" "True"
SUB_ID_DB=$(jget submission_id)
expect_eq "submission_id 与接口一致" "$SUB_ID_DB" "$SUB_ID"
expect_eq "status=ai_scored" "$(jget status)" "ai_scored"
expect_eq "ai_score 与练习成绩一致" "$(jget ai_score_eq_practice)" "True"
expect_eq "ai_detail 三个键" "$(jget detail_keys)" "defects|overallConfidence|words"
expect_eq "segment_id 正确" "$(jget segment_id_ok)" "True"
expect_eq "audio_id 正确" "$(jget audio_id_ok)" "True"
expect_eq "submitted_at 非空" "$(jget submitted_at_ok)" "True"
expect_eq "bkt_before 为空（不重复计分）" "$(jget bkt_before_none)" "True"
expect_eq "bkt_after 为空（不重复计分）" "$(jget bkt_after_none)" "True"
expect_eq "没有 homework 来源的 BKT 行" "$(jget bkt_homework_rows)" "0"
expect_eq "练习记录已落库" "$(jget practice_found)" "True"
expect_eq "练习记录 segment_id 正确" "$(jget practice_segment_ok)" "True"
expect_eq "练习链路 BKT 5 行" "$(jget practice_bkt_rows)" "5"
expect_eq "练习 BKT source 正确" "$(jget practice_bkt_source_ok)" "True"
if [ -z "$SUB_ID" ]; then
  echo "$(red "没拿到 submission_id，跳过教师端回显")" >&2
  exit 1
fi

echo
echo "── 10. 教师端 F4/F5 回显 ──────────────────────"
JAR="$JAR_T"
req "$BASE/api/homeworks/$HW_ID/submissions"
expect_status "F4 待批列表 → 200" 200
expect_in     "F4 能看到该提交" "\"submission_id\":$SUB_ID,"

req "$BASE/api/submissions/$SUB_ID/detail"
expect_status "F5 批改详情 → 200" 200
printf '%s' "$BODY" > "$TD/f5.json"
LYRICS_MATCH=$("$PY" - "$TD/b4.json" "$TD/f5.json" <<'PY'
import json, sys
b4 = json.load(open(sys.argv[1], encoding="utf-8"))["data"]
f5 = json.load(open(sys.argv[2], encoding="utf-8"))["data"]
keys = ("index", "word", "start", "end", "deviation_cents", "warning")
expected = [{k: w.get(k) for k in keys} for w in (b4.get("words") or [])]
print("match" if expected == (f5.get("lyrics") or []) else "mismatch")
PY
)
expect_eq "F5 的 lyrics 与 B4 words 同形" "$LYRICS_MATCH" "match"

echo
if [ "$FAIL" -eq 0 ]; then
  echo "$(green "全部通过")：$PASS 项"
  exit 0
fi
echo "$(red "失败 $FAIL 项")，通过 $PASS 项"
exit 1
