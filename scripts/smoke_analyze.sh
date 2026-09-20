#!/usr/bin/env bash
# 戏韵AI — B 组音频/分析接口冒烟测试（《5-接口清单-V1.0》B1–B5）
#
# 用法（在项目根目录执行）：
#     scripts/smoke_analyze.sh                              # 直连后端 8877
#     BASE=http://127.0.0.1:80 scripts/smoke_analyze.sh     # 经 nginx（顺带验证反代）
#
# 前置（三者缺一不可）：
#     1. 后端已启动：        .venv/bin/python app-d.py &
#     2. Celery worker 已起：.venv/bin/celery -A app.worker:celery_app worker --loglevel=info --concurrency=2
#     3. 数据库已灌 seed.sql
#   缺 worker 的表现是任务永远停在 queued，最后以「轮询超时」失败。
#
# ⚠️ 单轮约 2 分钟 —— 这条链路是真的跑 librosa 分析，不是桩。
#    实测单对 77–99 秒，瓶颈在 librosa.pyin。
#
# ⚠️ 「基准线」那组断言里的 overall=92.6 **不是** 100，这是对的，不是 bug：
#    五个维度各过一条 _logistic(差值, mid, k)，而 mid 都不为 0，所以即使
#    学生和老师唱得一模一样（同一条轨对同一条轨），也只有「音准」能到 100。
#    详细推导见 $AUDIO_DIR/README.md 的「满分不可达」一节。**不要为了让它变 100
#    去改 mid** —— 那组阈值是从 app-d.py 原样照搬、拿真实录音调过的。
#
# 不依赖 jq（本机没装）：JSON 解析交给 python3 标准库。
# 任一场景不符即打印明细并以退出码 1 结束，风格同 scripts/smoke_auth.sh / check_db.py，可接进 CI。
set -u

BASE="${BASE:-http://127.0.0.1:8877}"
PY="${PY:-python3}"
AUDIO_DIR="${AUDIO_DIR:-$HOME/Desktop/test_audio}"
AUDIO_FILE="${AUDIO_FILE:-01_xipi_1931.wav}"
POLL_INTERVAL="${POLL_INTERVAL:-2}"      # 轮询间隔（秒）
POLL_MAX="${POLL_MAX:-200}"              # 最多轮询次数，200×2s=400s；实测上限 99s，留足余量

# 文档 3.1 规定的 stage 枚举。断言 stage 必须落在其中——doc 的示例里出现过
# "DTW时间对齐" 这个**不在枚举里**的值（DOC_ISSUES 第 10 条），一旦实现跟着
# 示例走，前端认不出 stage、进度条卡住却一路 200，是最难查的一类错配。
VALID_STAGES='上传完成|人声分离|音高提取|八度修正|时间对齐|评分计算'

TD="$(mktemp -d)"
cleanup() { rm -rf "$TD"; }
trap cleanup EXIT

JAR="$TD/anon.jar"
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

expect_eq() {       # expect_eq <名称> <实际> <期望>
  if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "期望 $3，实际 $2"; fi
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
echo "测试音频：$AUDIO_DIR/$AUDIO_FILE"
echo "（本轮约 2 分钟，瓶颈是 librosa 提音高）"
echo

echo "── 1. 未登录基线 ──────────────────────────────"
post_json "/api/analyze/submit" '{"teacher_audio_id":1,"student_audio_id":1}'
expect_status "未登录调 B2 → 401（非 302）" 401
expect_code   "B2 未登录 code=401" 401

echo
echo "── 2. A1 登录 + B1 上传 ───────────────────────"
post_json "/api/auth/login" '{"username":"teacher01","password":"xiyun@2026"}'
expect_status "A1 teacher01 登录 → 200" 200

if [ ! -f "$AUDIO_DIR/$AUDIO_FILE" ]; then
  echo "$(red "找不到测试音频：$AUDIO_DIR/$AUDIO_FILE")" >&2
  echo "  该目录不在仓库里（.gitignore 排除），需另行获取；来源见该目录的 README.md" >&2
  echo "  也可用 AUDIO_DIR=<路径> scripts/smoke_analyze.sh 指定" >&2
  exit 1
fi

# access=public 是示范音频，只有教师能设；B5 据此判定所有登录用户可听
req -X POST -F "audio=@$AUDIO_DIR/$AUDIO_FILE" -F "access=public" "$BASE/api/audio/upload"
expect_status "B1 上传 → 200" 200
expect_code   "B1 code=0" 0

FILE_ID=$(jget data.file_id)
if printf '%s' "$FILE_ID" | grep -qE '^[0-9]+$'; then
  # ${FILE_ID} 而非 $FILE_ID：macOS 的 bash 3.2 在 UTF-8 locale 下会把紧跟的全角
  # 「）」并进变量名（$FILE_ID）→ 变量 FILE_ID）），配合 set -u 报 unbound variable。
  # 加花括号显式定界。其余三处同此（$TASK_ID / $STATUS / $BAD_STAGE）。
  ok "B1 返回整数 data.file_id（=${FILE_ID}）"
else
  bad "B1 应返回整数 data.file_id" "实际 data.file_id='$FILE_ID'；body=$BODY"
fi
# 红态兜底：上面这条失败时（B1 还在回 data.id）也让链路跑完，
# 否则后面每条断言都会变成连带失败，看不出真正的问题在哪。
if [ -z "$FILE_ID" ]; then FILE_ID=$(jget data.id); fi

expect_not_in "B1 响应不含 filePath（服务端存储路径不外泄）" "filePath"

URL_VAL=$(jget data.url)
expect_eq "B1 的 data.url 指向 B5" "$URL_VAL" "/api/audio/$FILE_ID"

echo
echo "── 3. B2 提交 ─────────────────────────────────"
# 同一条轨既作教师又作学生 —— 这是基准线，偏差必须严格为 0
post_json "/api/analyze/submit" "{\"teacher_audio_id\":$FILE_ID,\"student_audio_id\":$FILE_ID}"
expect_status "B2 提交 → 200" 200
expect_code   "B2 code=0" 0

TASK_ID=$(jget data.task_id)
if printf '%s' "$TASK_ID" | grep -qE '^[0-9a-fA-F]{8,}$'; then
  ok "B2 返回 data.task_id（=${TASK_ID}）"
else
  bad "B2 应返回 data.task_id" "实际='$TASK_ID'；body=$BODY"
fi
# 红态兜底：B2 改回文档形状之前，data 是裸字符串
if [ -z "$TASK_ID" ]; then
  TASK_ID=$(printf '%s' "$BODY" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("data") or "")')
fi

if [ -z "$TASK_ID" ]; then
  echo "$(red "拿不到 task_id，后面的轮询无法进行")" >&2
  exit 1
fi

echo
echo "── 4. B3 轮询（最多 $((POLL_MAX * POLL_INTERVAL)) 秒）─────────"
PREV_PROGRESS=-1
MONO=1                 # progress 是否单调不减
STAGES_OK=1            # stage 是否始终落在文档枚举内
BAD_STAGE=""
FINAL_STATUS=""
n=0
while [ "$n" -lt "$POLL_MAX" ]; do
  n=$((n + 1))
  req "$BASE/api/analyze/status/$TASK_ID"
  if [ "$STATUS" != "200" ]; then
    bad "B3 轮询 → 200" "第 $n 轮实际 ${STATUS}；body=$BODY"
    break
  fi
  ST=$(jget data.status)
  PG=$(jget data.progress)
  SG=$(jget data.stage)

  if ! printf '%s' "$SG" | grep -qE "^($VALID_STAGES)$"; then
    STAGES_OK=0
    BAD_STAGE="$SG"
  fi
  case "$PG" in
    ''|*[!0-9]*) : ;;                                   # 非数字就跳过这条检查
    *) if [ "$PG" -lt "$PREV_PROGRESS" ]; then MONO=0; fi
       PREV_PROGRESS=$PG ;;
  esac

  if [ "$ST" = "done" ] || [ "$ST" = "failed" ]; then
    FINAL_STATUS="$ST"
    printf '  · 第 %d 轮到达终态：status=%s progress=%s stage=%s\n' "$n" "$ST" "$PG" "$SG"
    break
  fi
  sleep "$POLL_INTERVAL"
done

expect_eq "B3 终态为 done" "$FINAL_STATUS" "done"
expect_eq "B3 的 progress 单调不减" "$MONO" 1
if [ "$STAGES_OK" = "1" ]; then
  ok "B3 的 stage 始终落在文档 3.1 枚举内"
else
  bad "B3 的 stage 落在文档 3.1 枚举内" "出现了枚举外的值「${BAD_STAGE}」——见 DOC_ISSUES 第 10 条"
fi
expect_eq "B3 终态 progress=100" "$PREV_PROGRESS" 100

echo
echo "── 5. B4 结果 ─────────────────────────────────"
req "$BASE/api/analyze/result/$TASK_ID"
expect_status "B4 取结果 → 200" 200
expect_code   "B4 code=0" 0

cat > "$TD/check_result.py" <<'PYEOF'
# 对 B4 的 body 做数值断言，把结论打成 KEY=VALUE 让 bash 认。
import json, math, sys

d = json.load(open(sys.argv[1]))["data"]
tl = d["timeline"]

# 本次新增的 4 个字段：前端展示必需，但文档 3.2 未定义（DOC_ISSUES 第 14 条）
for k in ("octave_shift", "teacher_onset", "student_onset", "ref_hz"):
    print("HAS_%s=%d" % (k.upper(), 1 if k in d else 0))

print("OVERALL=%s" % d["overall"])
print("PITCH=%s" % d["dimensions"]["音准"])

ref = d.get("ref_hz")
print("REF_HZ_PLAUSIBLE=%d" % (1 if isinstance(ref, (int, float)) and 65 < ref < 1000 else 0))

# 自洽性：deviation_cents 必须等于两条 Hz 曲线换算出的音分差。
# 注意这个式子与 ref_hz 无关 —— s_cents − t_cents = 1200·log2(s_hz/t_hz)，
# 基准在相减时约掉了。所以即使 ref_hz 缺失，这条检查依然有效（不会假通过）。
mx = 0.0
for (_, f1), (_, f2), (_, dv) in zip(tl["teacher_pitch"], tl["student_pitch"], tl["deviation_cents"]):
    if f1 > 0 and f2 > 0:
        mx = max(mx, abs(1200 * math.log2(f2 / f1) - dv))
print("CONSIST_MAXERR=%.4f" % mx)

# 基准线：同一条轨对同一条轨，逐字偏差必须严格为 0
print("MAXDEV=%.4f" % max(abs(p[1]) for p in tl["deviation_cents"]))
print("ALL_GREEN=%d" % (1 if all(r["level"] == "green" for r in d["regions"]) else 0))
print("REGION_COUNT=%d" % len(d["regions"]))
PYEOF

eval "$("$PY" "$TD/check_result.py" "$BODY_FILE")"

expect_eq "B4 含 octave_shift（八度修正量）" "$HAS_OCTAVE_SHIFT" 1
expect_eq "B4 含 teacher_onset（同步播放起点）" "$HAS_TEACHER_ONSET" 1
expect_eq "B4 含 student_onset" "$HAS_STUDENT_ONSET" 1
expect_eq "B4 含 ref_hz（音分基准）" "$HAS_REF_HZ" 1
expect_eq "ref_hz 落在 pyin 的可信基频范围内" "$REF_HZ_PLAUSIBLE" 1
expect_eq "偏差与两条曲线自洽（误差 < 0.5 音分）" \
  "$(awk -v e="$CONSIST_MAXERR" 'BEGIN{print (e < 0.5) ? 1 : 0}')" 1

echo
echo "── 6. 基准线（同轨对同轨，流水线健康度标尺）────"
# 同一条轨做 DTW，偏差必然严格为 0；任何非零都说明对齐或基准音高算错了，
# 与录音质量无关。overall=92.6 而非 100 是评分公式决定的，见脚本头部说明。
expect_eq "偏差严格为 0" "$MAXDEV" "0.0000"
expect_eq "音准 = 100.0" "$PITCH" "100.0"
expect_eq "overall = 92.6" "$OVERALL" "92.6"
expect_eq "regions 全绿" "$ALL_GREEN" 1
echo "  · regions 共 $REGION_COUNT 段（无歌词时走 2 秒滑窗，约 87 段属正常）"

echo
if [ "$FAIL" -eq 0 ]; then
  echo "$(green "全部通过")：$PASS 项"
  exit 0
fi
echo "$(red "失败 $FAIL 项")，通过 $PASS 项"
exit 1
