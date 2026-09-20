# 音准对比页异步化改造 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `pitch_comparison.html` 的音准对比分析从 `app-d.py` 的同步阻塞接口迁到 B2/B3/B4 异步协议，并让该页其余请求全部走 `audio_analyze.py` 的业务接口。

**Architecture:** 后端只做两处改动——`analyze_service._analyze()` 往 `result` 里补 4 个前端展示必需、但文档 3.2 未定义的字段；`audio_analyze.py` 的 B1/B2 响应改回文档形状。前端新增 `adaptResult()` 作为契约转换层，把 3.2 的 `timeline` 还原成绘图函数认识的形状；`doAnalyze()` 由「单请求挂 80–100 秒」改为「B2 提交 → B3 每秒轮询 → B4 取结果」。`demo_bp` 按决策保留未删，仅登记为无调用方。（完整设计见 `docs/superpowers/specs/2026-09-20-pitch-comparison-async-design.md`）

**Tech Stack:** Python 3.11 ｜ Flask 3.1.3 ｜ Celery 5.x + redis（broker 库 0 / 任务状态库 1）｜ librosa ｜ 前端纯静态 HTML + 内联 JS（WaveSurfer + Canvas 2D）

## Global Constraints

以下约束适用于**每一个任务**，不再逐条重复：

- **零新增依赖。** 不装 pytest、不装 jq、不引入任何 Python/JS 库。所有验证用 `.venv/bin/python` 内联脚本 / `curl` / 现成的 `scripts/*.sh`。本项目**没有 `tests/` 目录、没有 pytest**，测试约定就是 `scripts/` 下的冒烟脚本（风格见 `scripts/smoke_auth.sh`、`scripts/check_db.py`）。
- **解释器一律用 `.venv/bin/python`**（后端运行时）。PATH 上的 `python`/`pip` 是 pyenv 3.12，不是本项目 venv（Python 3.11）。冒烟脚本里解析 JSON 的 `python3` 是例外——它只用标准库 `json`，与 `smoke_auth.sh` 一致。
- **`/api` 前缀字面量只在 `app/api/__init__.py` 的 `API_PREFIX` 出现一次。** 其余文件写相对路径或引用该常量。
- **统一返回** `{"code":0,"message":"ok","data":...}`；`code` 沿用 HTTP 语义且与 HTTP 状态码一致（`DOC_ISSUES.md` 第 9 条）。错误由 `app/common/errors.py` 的全局 handler 兜，**路由与 service 层不写 `try/except`**。
- **中文**：UI 文案、注释、文档、commit message 全用中文；代码标识符保持英文；文件 UTF-8。
- **不改 `../艺校_docs/` 下的文档。** 发现的文档空白一律登记到根目录 `DOC_ISSUES.md`。
- **`demo_bp` 一行都不动。** `app-d.py` 的 4 条演示路由本次原样保留（见 spec 第 2 节）。
- **前端页面自包含**：`<style>` 与 `<script>` 全部内联，不抽公共文件、不新增文件。
- 命令一律在项目根目录 `/Users/meiyazhao/Documents/lianshu/operaAI` 执行。

### 运行前置（Task 2 起每次验证都需要，三者缺一不可）

```bash
# 1. 后端（监听 8877）
.venv/bin/python app-d.py &

# 2. Celery worker（B2 只投队列，真正跑 librosa 的是它；不起则任务永远停在 queued）
.venv/bin/celery -A app.worker:celery_app worker --loglevel=info --concurrency=2

# 3. redis 与数据库（redis 带口令，见 .env；数据库是 Docker 容器 docker_postgres）
```

改完 Python 代码必须**重启后端**才生效（`app-d.py` 带 `debug=True`，但 Celery worker 不会自动重载，改了 `analyze_service.py` 也要重启 worker）。

### 测试素材

`test_audio/` 不在本仓库（被 `.gitignore` 排除），实际位置由 `AUDIO_DIR` 指定，默认 `$HOME/Desktop/test_audio`。该目录的 `README.md` 记录了每条的实测结果与来源。本项目统一用 **`01_xipi_1931.wav`**（西皮，16kHz 单声道 PCM_16，182.8s）。

单轮完整分析实测 **77–99 秒**（瓶颈是 `librosa.pyin` 对两条 3 分钟音轨各跑一遍）。

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `scripts/smoke_analyze.sh` | **新建** | B1–B5 的端到端冒烟闸门。唯一的自动化测试，Task 1 先写、Task 2 转绿 |
| `app/services/analyze_service.py` | 修改 | 往 `_analyze()` 的 `result` 补 4 个字段（第 283–292 行那块） |
| `app/api/audio_analyze.py` | 修改 | B1/B2 响应改回文档形状；更新文件末尾关于 `pitch_comparison.html` 去留的注释 |
| `pitch_comparison.html` | 修改 | 前端迁移主体：契约转换层 + 异步分析流程 + 删除死代码 |
| `DOC_ISSUES.md` | 修改 | 新增第 14、15 条；更新第 11、12 条 |
| `CLAUDE.md` | 修改 | 「例外 1」段、两条演示路由警示、「仍返回裸字段」句 |
| `$AUDIO_DIR/README.md` | 修改 | curl 示例更新成新响应形状 |

**任务切分依据**：Task 1 是测试夹具（先红）；Task 2 是后端契约（转绿）；Task 3 是前端迁移——它**不拆**，因为 `adaptResult` 的调用方、被删的 `estimateProgressFromLogs`、被改的 `filePath` 读取点全在同一个文件的同一条分析路径上，拆开会产生「中间态页面是坏的」的提交，而半迁移的 HTML 不具备可审性；Task 4 是文档同步，收尾。

---

### Task 1: 冒烟脚本 `scripts/smoke_analyze.sh`（先写，红）

**Files:**
- Create: `scripts/smoke_analyze.sh`

**Interfaces:**
- Consumes: 无（纯新增）
- Produces: 一个可执行脚本，退出码 0=全通过 / 1=有失败。后续任务的验收标准就是它全绿。脚本读取环境变量 `BASE`（默认 `http://127.0.0.1:8877`）、`AUDIO_DIR`（默认 `$HOME/Desktop/test_audio`）、`AUDIO_FILE`（默认 `01_xipi_1931.wav`）。

- [ ] **Step 1: 写脚本**

创建 `scripts/smoke_analyze.sh`，内容如下（逐字照抄，不要改动断言里的期望值）：

```bash
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
  ok "B1 返回整数 data.file_id（=$FILE_ID）"
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
  ok "B2 返回 data.task_id（=$TASK_ID）"
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
    bad "B3 轮询 → 200" "第 $n 轮实际 $STATUS；body=$BODY"
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
  bad "B3 的 stage 落在文档 3.1 枚举内" "出现了枚举外的值「$BAD_STAGE」——见 DOC_ISSUES 第 10 条"
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
```

- [ ] **Step 2: 给脚本加执行权限**

```bash
chmod +x scripts/smoke_analyze.sh
```

- [ ] **Step 3: 确认运行前置都在**

```bash
curl -s -o /dev/null -w 'backend=%{http_code}\n' http://127.0.0.1:8877/api/auth/me
ps aux | grep "[c]elery -A app.worker" | wc -l
ls "$HOME/Desktop/test_audio/01_xipi_1931.wav"
```

Expected：`backend=401`（401 说明后端活着且未登录，是正常的）；worker 计数 `1`（或更多）；音频文件路径打印出来。
若 worker 计数为 `0`，先起：`.venv/bin/celery -A app.worker:celery_app worker --loglevel=info --concurrency=2 &`

- [ ] **Step 4: 跑脚本，确认它**失败**，且失败项正好是预期的那 7 条**

```bash
scripts/smoke_analyze.sh
```

Expected：退出码 1，末尾打印 `失败 8 项`。失败的必须是这 8 条：

```
✗ B1 应返回整数 data.file_id
✗ B1 响应不含 filePath（服务端存储路径不外泄）
✗ B2 应返回 data.task_id
✗ B4 含 octave_shift（八度修正量）
✗ B4 含 teacher_onset（同步播放起点）
✗ B4 含 student_onset
✗ B4 含 ref_hz（音分基准）
✗ ref_hz 落在 pyin 的可信基频范围内
```

最后一条与倒数第二条是同一个缺失字段引起的两条断言：`ref_hz` 不存在时，`isinstance(None, (int, float))` 为假，所以 `REF_HZ_PLAUSIBLE` 也是 0。**这是预期的，不要去「修」它**——两轮之后 `ref_hz` 一补上，两条会一起转绿。

**其余断言必须全过**，特别是 `偏差与两条曲线自洽`、`偏差严格为 0`、`音准 = 100.0`、`overall = 92.6`、`regions 全绿`、`B1 的 data.url 指向 B5`、`B3 的 stage 始终落在文档 3.1 枚举内`。

若这 8 条之外还有失败，**先停下来查清楚**——尤其是基准线那 4 条。它们失败意味着 `analyze_service` 已存在问题，与本次迁移无关，但也绝不能带着这个问题往下走。

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke_analyze.sh
git commit -m "test: 新增 B 组音频/分析接口冒烟脚本

覆盖 B1–B5 完整链路（登录 → 上传 → 提交 → 轮询 → 取结果），
并按 test_audio/README.md 的实测记录把「同轨对同轨 overall=92.6、
偏差严格为 0、regions 全绿」立为流水线健康度基准线。

当前 8 条失败，正是待迁移项（B1/B2 响应形状、B4 缺 4 个字段，其中
ref_hz 一个字段占两条断言）。"
```

---

### Task 2: 后端补字段 + B1/B2 改回文档形状（转绿）

**Files:**
- Modify: `app/services/analyze_service.py`（`_analyze()` 末尾组装 `result` 的那一段）
- Modify: `app/api/audio_analyze.py`（`audio_upload()` 的返回、`analyze_submit()` 的返回、文件末尾注释）
- Modify: `DOC_ISSUES.md`（新增第 14、15 条，更新第 12 条）
- Modify: `$AUDIO_DIR/README.md`（「怎么用」一节的 curl 示例）

**Interfaces:**
- Consumes: Task 1 的 `scripts/smoke_analyze.sh`
- Produces: B4 的 `result` 多出 `octave_shift: int`、`teacher_onset: float`、`student_onset: float`、`ref_hz: float`；B1 返回 `{"file_id": int, "url": str}`；B2 返回 `{"task_id": str}`。Task 3 的前端按这些名字取值。

- [ ] **Step 1: 给 `result` 补 4 个字段**

打开 `app/services/analyze_service.py`，找到 `_analyze()` 里组装 `result` 的那一段（现在的样子是 `result = {` 开头、包含 `"overall"` / `"dimensions"` / `"timeline"` / `"regions"` / `"words"`，结尾是 `}`）。把它替换成：

```python
    result = {
        # overall 是五个维度的均值：文档 3.2 的例子（80/85/78/84/86 → 82.5）
        # 与算术平均只差 0.1，看不出另有加权，这里就按等权处理。
        "overall": round(float(np.mean(list(dimensions.values()))), 1),
        "dimensions": dimensions,
        "timeline": _timeline(t_track.times, t_cents, s_aligned, ref_hz),
        # regions 由逐字结果合并而来（没有歌词时退回滑窗），所以必须在 words 之后。
        "regions": _regions(words, t_track.times, s_aligned - t_cents),
        "words": words,
        # ↓↓↓ 文档 3.2 未定义这四个字段，但前端展示需要 → DOC_ISSUES 第 14 条。
        # 尤其 octave_shift：student_pitch 已经是它修正之后的结果，不单独给出，
        # 前端无从知道修正发生过（也就无法提示「学生整体低了八度」），
        # 更无从还原学生原始音高。这四个值在上面的管线里都已经算好了。
        "octave_shift": octave_shift,
        "teacher_onset": round(float(t_onset), 3),
        "student_onset": round(float(s_onset), 3),
        "ref_hz": round(float(ref_hz), 2),
    }
```

- [ ] **Step 2: 确认这四个变量在作用域内**

```bash
grep -n "octave_shift = \|t_onset, s_onset\|ref_hz = \|t_onset =\|s_onset =" app/services/analyze_service.py
```

Expected：能看到 `t_vocal, t_onset = _load_vocal(...)`、`s_vocal, s_onset = _load_vocal(...)`、`ref_hz = float(np.median(voiced)) ...`、`octave_shift = _best_octave(...)` 四行，且它们都出现在 `result = {` **之前**。

若某一行的行号大于 `result = {` 的行号，说明放错了位置，把它们移到 `result` 组装之前。

- [ ] **Step 3: 冒烟脚本转绿（后端部分）**

重启后端与 worker（改了 `analyze_service.py`，worker 不会自动重载）：

```bash
# Ctrl-C 掉原来的两个进程，然后
.venv/bin/python app-d.py &
.venv/bin/celery -A app.worker:celery_app worker --loglevel=info --concurrency=2 &
```

```bash
scripts/smoke_analyze.sh
```

Expected：退出码 1，失败项从 8 条降到 3 条——只剩 B1 的两条与 B2 的一条：

```
✗ B1 应返回整数 data.file_id
✗ B1 响应不含 filePath（服务端存储路径不外泄）
✗ B2 应返回 data.task_id
```

4 条 `B4 含 ...` 必须已转为通过。

- [ ] **Step 4: B1/B2 改回文档形状**

打开 `app/api/audio_analyze.py`，把 `audio_upload()` 末尾的返回改成：

```python
    # 文档 B1 定义的返回是 {"file_id": ...}。额外给一个 url：前端要拿它喂给
    # WaveSurfer 加载音频，由 url_for 生成能保证路径永远跟着 B5 的真实路由走，
    # 前端就不必硬编码 /api/audio/<id>——硬编码路径与后端漂移正是 DOC_ISSUES
    # 第 1 条记录的那类问题。多出的这个字段见 DOC_ISSUES 第 14 条。
    #
    # 刻意**不**返回 audio.file_path：那是服务端存储名，而 common/storage.py
    # 的模块文档写明「不会把服务器目录结构泄漏到接口响应里」。B2 认的是
    # audio_files.id（数据库主键），前端不需要也不该拿到存储路径。
    return ok({
        "file_id": audio.id,
        "url": url_for("api.audio_download", file_id=audio.id),
    })
```

再把 `analyze_submit()` 的返回改成：

```python
    return ok({"task_id": task_id})
```

- [ ] **Step 5: 更新文件末尾那段注释**

`app/api/audio_analyze.py` 文件末尾有一段以 `# 仍未了结的是 pitch_comparison.html 的去留` 开头的注释。把那最后一段（从 `# 仍未了结的是` 到文件结尾）替换成：

```python
# pitch_comparison.html 的去留已了结：该页 2026-09-20 已迁到 B1/B2/B3/B4/B5，
# 不再调用 app-d.py 的 demo_bp。DOC_ISSUES 第 11 条记的两个悬案随之解决
# ——「音频加载是坏的」由 B1 返回 B5 的 url 解决，「结果契约无法平滑切换」
# 由前端新增的 adaptResult() 转换层解决。
#
# 但 demo_bp 那 4 条演示路由**保留未删**（本次的明确决策），已无任何调用方，
# 是后续的独立清理项。
```

- [ ] **Step 6: 冒烟脚本全绿**

重启后端（改了 `audio_analyze.py`；worker 不必重启）：

```bash
# Ctrl-C 掉后端，然后
.venv/bin/python app-d.py &
```

```bash
scripts/smoke_analyze.sh
```

Expected：退出码 0，末尾打印 `全部通过：N 项`，其中约 25 项。基准线 4 条（偏差 0 / 音准 100.0 / overall 92.6 / regions 全绿）必须都在。

- [ ] **Step 7: 登记 DOC_ISSUES**

在 `DOC_ISSUES.md` 的 `## 13. 页面级鉴权文档完全未规定` 一节之后、`## 待核实` 之前，插入两条：

```markdown
## 14. 3.2 结果契约与 B1 响应缺前端展示所必需的字段

**涉及**：《5-接口清单-V1.0》3.2、B1

**问题**：3.2 只定义了 `overall / dimensions / timeline / regions / words` 五个字段，但 `pitch_comparison.html` 要把它画成曲线图，还需要四个结果里没有的值：

| 缺失字段 | 用途 | 为什么前端反推不出 |
|---|---|---|
| `octave_shift` | 「学生整体低 N 个八度，已自动对齐」提示；tooltip 里的原始 Hz | `student_pitch` 是**八度修正之后**的值，原始音高已丢失 |
| `teacher_onset` | 同步播放起点的 seek 位置 | `words[].start` 已经减掉了 onset |
| `student_onset` | 同上 | 同上 |
| `ref_hz` | 把 Hz 曲线还原成音分（绘图坐标系） | 前端只能在抽稀后的 1500 点上估中位数，与后端在全帧上算的有微差 |

同一个问题在 B1 上也存在：文档只定义了 `file_id`，但前端需要拿到一个能加载音频的地址。

**影响**：不是报错，是「画出来不对」——曲线基准偏了、八度提示消失、同步播放从文件开头而不是开唱点开始。属于靠肉眼比对才能发现的偏差。

**当前处理**：实现按上表补齐（`app/services/analyze_service.py` 的 `_analyze()`），B1 额外返回 `url`（由 `url_for("api.audio_download", ...)` 生成，指向 B5）。四个值在分析管线里本来就已经算好，只是没往 `result` 里放。**同时刻意不返回 `audio_files.file_path`**——它是服务端存储名，回给客户端违背 `common/storage.py` 模块文档里的承诺。

**关联**：本条给出的 `octave_shift` 同时了结了第 12 条第 2 项「全局偏移量没有单独字段可放」。

---

## 15. 3.1 未规定 B2 是否校验音频归属

**涉及**：《5-接口清单-V1.0》3.1（B2）

**问题**：文档规定了 B2 的入参（`teacher_audio_id` / `student_audio_id` / `segment_id`）与返回，但没有规定**提交分析时是否要校验这两个 `audio_id` 属于调用者**。

**影响**：实现现状是只查存在性（`analyze_service._require_audio()` 调 `audio_repo.get_by_id()`，不比对 `uploader_id`），于是任何登录用户拿任意 `audio_id` 就能提交分析、并读到 B4 返回的完整音高曲线——**包括他人 `access=private` 的学生录音**。《6-登录与数据隔离方案》第 4 节第 2 条定的可听范围（private 仅上传者本人与教师可听）在 B2 这条路径上被绕过了。B5 有 `audio_service.get_playable()` 做权限判定，B2 没有对应的一层。

**当前处理**：未修，仅登记。修它要先定「教师能否分析他人的学生录音」「跨学生比对是否允许」这类业务规则，文档没给依据，不属于前端迁移的范围。
```

- [ ] **Step 8: 更新 DOC_ISSUES 第 12 条第 2 项**

在 `DOC_ISSUES.md` 第 12 条的「**当前处理**」列表里，把这一行：

```
- `octave_fixed` 按**字**判断：全局修正之外，若某字的中位偏差仍落在 1200±400 cents 内，再折一次并置真。全局偏移量没有单独字段可放（契约里没有），仅进日志。
```

替换成：

```
- `octave_fixed` 按**字**判断：全局修正之外，若某字的中位偏差仍落在 1200±400 cents 内，再折一次并置真。全局偏移量原先「没有单独字段可放，仅进日志」，2026-09-20 起 `result.octave_shift` 就是它（见第 14 条）。
```

- [ ] **Step 9: 更新 `$AUDIO_DIR/README.md` 的 curl 示例**

打开 `$HOME/Desktop/test_audio/README.md`。

⚠️ **这个文件在仓库外，改动不会进版本库，也不要 `git add` 它。** 实测：仓库根目录下**没有** `test_audio/` 这个目录，`.gitignore` 里的 `test_audio/*.wav` 等几行是给「仓库内同名目录」写的规则，但素材实际落在 `~/Desktop/test_audio`，`git -C ~/Desktop/test_audio rev-parse` 会回 `fatal: not a git repository`。所以对它 `git add` 会当场报 `fatal: ... is outside repository`。改它是为了让本地素材文档与代码同步（这文件就是上一个项目调接口时的操作手册），改完即可，不提交。

在「怎么用」一节里，把 B1 上传那段注释：

```
# → {"code":0,...,"data":{"file_id":<N>}}，把 N 记下来
```

替换成：

```
# → {"code":0,...,"data":{"file_id":<N>,"url":"/api/audio/<N>"}}，把 N 记下来
#   url 是 B5 的取音频地址，由后端 url_for 生成，前端据此加载音频
```

并把 B2 提交那段注释：

```
# → {"data":{"task_id":"..."}}，然后轮询 B3、取 B4
```

替换成：

```
# → {"data":{"task_id":"..."}}，然后轮询 B3、取 B4
#   B4 的 data 里除 overall/dimensions/timeline/regions/words 外，
#   还有 octave_shift / teacher_onset / student_onset / ref_hz（见 DOC_ISSUES 第 14 条）
```

- [ ] **Step 10: Commit**

```bash
git add app/services/analyze_service.py app/api/audio_analyze.py DOC_ISSUES.md
git commit -m "feat: B4 结果补前端展示必需字段，B1/B2 响应改回文档形状

analyze_service._analyze 的 result 补 4 个字段：octave_shift、
teacher_onset、student_onset、ref_hz。它们在上面的管线里都已经算好，
只是没往 result 里放；其中 octave_shift 同时了结 DOC_ISSUES 第 12 条
第 2 项「全局偏移量没有单独字段可放」。

B1 改回 {file_id, url}、B2 改回 {task_id}（工作区此前为了迁就旧前端
改成了别的形状）。B1 不再返回 filePath——那是服务端存储名，回给客户端
违背 common/storage.py 模块文档里的承诺。

新增 DOC_ISSUES 第 14 条（上表四个字段 + B1 的 url）与第 15 条
（B2 未校验音频归属，可读到他人 private 录音的音高曲线，仅登记未修）。

scripts/smoke_analyze.sh 由 8 条失败转为全绿。

顺带同步了 ~/Desktop/test_audio/README.md 的 curl 示例。该文件在仓库外
（仓库根目录并没有 test_audio/ 目录，素材实际放在桌面上），改动不进版本库，
故不在本次提交内。"
```

---

### Task 3: 前端迁移 `pitch_comparison.html`

**Files:**
- Modify: `pitch_comparison.html`

**Interfaces:**
- Consumes: Task 2 的接口形状——B1 回 `data.{file_id, url}`；B2 回 `data.task_id`；B3 回 `data.{status, progress, stage, message}`；B4 回 `data.{overall, dimensions, timeline:{duration, teacher_pitch, student_pitch, deviation_cents}, regions, words, octave_shift, teacher_onset, student_onset, ref_hz}`
- Produces: 页面内新增 `adaptResult(b4)`、`pollUntilSettled(taskId, logsEl, barEl)`、`stopPolling()`、`appendLog(logsEl, msg, color)`、`sessionExpired()` 五个函数；`analysisData` 的形状保持 `drawTimeline()` 原本消费的那套

**为什么这一个任务不拆**：`adaptResult` 的调用方、被删的 `estimateProgressFromLogs`、被改的 `filePath` 读取点全在同一个文件的同一条分析路径上。拆成「先加转换层、再改流程」会留下一个 `filePath` 已删、`doAnalyze` 还在读它的中间态——页面在那一步是坏的，而半迁移的 HTML 不具备可审性。

**读这组步骤前先知道两件事**：

1. **各步之间存在前向引用，是刻意的，不要去「修」。** 下面所有步骤都是对同一个文件的编辑，页面在全部改完之前跑不起来，所以：Step 1 用到的 `sessionExpired()` 在 Step 2 才定义；Step 4 用到的 `POLL_INTERVAL_MS` / `POLL_TIMEOUT_MS` 在 Step 6 才定义。按顺序做完即可。
2. **Step 11 之前不要打开页面**。中间态一定是坏的（`doAnalyze` 还是旧的、常量还没定义），看到一个报错页面不代表改错了。

- [ ] **Step 1: 改上传处读新形状，并加会话过期处理**

打开 `pitch_comparison.html`，找到 `initWave()` 里 `document.getElementById(fileInputId).addEventListener('change', ...)` 那个回调（约 `:520`）。把回调体里 `try` 块的内容替换成：

```js
        try {
            const form = new FormData();
            form.append('audio', file);
            const r = await fetch(`${API}/api/audio/upload`, { method: 'POST', body: form });
            if (r.status === 401) return sessionExpired();
            if (!r.ok) {
                const errText = await r.text();
                throw new Error(`服务器 ${r.status}: ${errText}`);
            }
            const j = await r.json();
            // B1 返回 {file_id, url}。url 由后端 url_for 生成、指向 B5，
            // 前端直接拿来喂 WaveSurfer，不自己拼路径。
            const audioUrl = `${API}${j.data.url}`;
            ws.load(audioUrl);
            // 只留 B2 需要的 audio_files.id 与播放地址。原先还存了 filePath，
            // 那是上一轮同步迁移的遗留——B2 认的是数据库主键，不是磁盘路径，
            // 且 B1 已不再返回它（见 DOC_ISSUES 第 14 条）。
            waves[role] = { ws, id: j.data.file_id, url: audioUrl };
        } catch (err) {
            console.error(`[${role}] 上传/加载失败:`, err);
            setStatus(role, '' + err.message, true);
            alert(`[${role === 't' ? '老师' : '学生'}] 上传失败: ${err.message}`);
        }
```

注意 `catch` 块本身不变，只替换 `try` 里的内容（原来有一行 `if (j.error) throw new Error(j.error);`，删掉——那是 demo 路由的裸 `{"error":...}` 形状，B 组接口的错误一律走统一信封 + 非 2xx，已由上面的 `!r.ok` 覆盖）。

- [ ] **Step 2: 加 `sessionExpired()` 助手**

在 `setStatus()`（`:446`）与 `updateDimensions()`（`:453`）之间插入，即 `setStatus` 的闭括号之后、`function updateDimensions` 那一行之前：

```js
// 会话过期：B1–B5 全部挂了 @login_required，过期时后端回 401 + 统一信封。
// 统一跳登录页，而不是把 401 的 JSON 当普通错误弹 alert ——那种提示对用户
// 完全没有可操作性，他不知道要重新登录。
function sessionExpired() {
    alert('会话已过期，请重新登录');
    location.replace('/login.html');
}
```

- [ ] **Step 3: 删除 `estimateProgressFromLogs()`**

删掉 `:761` 到 `:783`——从 `function estimateProgressFromLogs(logs) {` 到它对应的 `}`，整个函数。连同它下面的空行一起去掉，让 `doAnalyze()` 紧接在 `closeProgress()` 之后。

**保留** `:756` 的 `// ---------- 进度弹窗 ----------` 与 `:757–759` 的 `closeProgress()`，两者都还在用。

删它的理由：B3 直接给 `progress` 真值，不再需要从服务端日志文案里猜。

- [ ] **Step 4: 加日志追加助手与轮询控制**

在上一步留下的位置（`closeProgress()` 之后、`doAnalyze()` 之前）插入：

```js
// ---------- 进度日志与轮询 ----------
// 日志是「追加式」的：只在 stage/message 变化时写一行，不每轮刷 innerHTML。
// 阶段取值见《5-接口清单》3.1：上传完成 / 人声分离 / 音高提取 /
// 八度修正 / 时间对齐 / 评分计算。
function appendLog(logsEl, msg, color) {
    const t = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    const div = document.createElement('div');
    div.className = 'log-line';
    if (color) div.style.color = color;
    // textContent 而非 innerHTML：msg 里含服务端给的 message，
    // 拼接进 HTML 会有注入风险。
    div.textContent = `[${t}] ${msg}`;
    logsEl.appendChild(div);
    logsEl.scrollTop = logsEl.scrollHeight;
}

function stopPolling() {
    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
}

// 轮询 B3 直到 done/failed，resolve 终态那一帧的 status 数据。
// 实测单对分析 77–99 秒，10 分钟留足余量；没有这道护栏，worker 挂掉时
// 任务永远停在 queued，前端会无限轮询下去。
function pollUntilSettled(taskId, logsEl, barEl) {
    return new Promise((resolve, reject) => {
        const startedAt = Date.now();
        let lastLine = '';
        pollTimer = setInterval(async () => {
            if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
                stopPolling();
                reject(new Error('分析超时（超过 10 分钟）——请确认 Celery worker 是否在运行'));
                return;
            }
            try {
                const r = await fetch(`${API}/api/analyze/status/${taskId}`);
                if (r.status === 401) { stopPolling(); return sessionExpired(); }
                if (!r.ok) return;          // 单次失败不终止，交给下一轮
                const st = (await r.json()).data;

                barEl.style.width = (st.progress || 0) + '%';
                const line = st.stage + (st.message ? ' — ' + st.message : '');
                if (line !== lastLine) {
                    lastLine = line;
                    appendLog(logsEl, line);
                }
                if (st.status === 'done' || st.status === 'failed') {
                    stopPolling();
                    resolve(st);
                }
            } catch (e) {
                // 网络抖动：不终止轮询，下一轮重试
            }
        }, POLL_INTERVAL_MS);
    });
}
```

- [ ] **Step 5: 加契约转换层 `adaptResult()`**

紧接着上一步的 `pollUntilSettled` 之后插入：

```js
// ---------- 结果契约转换（文档 3.2 → 绘图层形状） ----------
// B4 回的是 3.2 契约 {overall, dimensions, timeline, regions, words}，
// 而 drawTimeline/tooltip 消费的是 demo 时代的 aligned[]。这里做一层显式转换，
// 而不是把绘图代码改成直接读 3.2 ——转换是纯数学、可单独验证，
// 混进绘图函数里就变成「既要算坐标又要换契约」。
//
// 依据是后端 _pitch_pairs 的 docstring 记的两条自洽关系：
//     student_pitch = ref_hz · 2^(s_cents/1200)
//     deviation_cents = s_cents − t_cents
// 于是 t_cents = 1200·log2(t_hz / ref_hz)，s_cents = t_cents + deviation。
//
// ref_hz 用后端给的：前端自己取教师中位 Hz 只能在抽稀后的 1500 点上估，
// 与后端在全帧上算的有微差，会让教师曲线不精确过 0 音分那条参考线。
//
// 三条曲线等长同栅格（后端 _timeline 用同一个 stride 抽稀），可以按下标配对。
function adaptResult(b4) {
    const tl = b4.timeline;
    const tHz = tl.teacher_pitch;      // [[t, hz], ...]
    const sHz = tl.student_pitch;
    const dev = tl.deviation_cents;    // [[t, cents], ...] 带符号
    const toCents = (hz) => 1200 * Math.log2(hz / b4.ref_hz);

    const aligned = tHz.map((p, i) => {
        const t_cents = toCents(p[1]);
        const d = dev[i][1];
        return {
            t_time: p[0],
            t_cents: t_cents,
            s_cents: t_cents + d,
            t_f0: p[1],
            s_f0: sHz[i][1],
            // 取绝对值是必须的：demo 时代的 diff 是 abs(t_c − s_c)，
            // 而 3.2 的 deviation_cents 是带符号的。不取绝对值，
            // drawTimeline 里所有 `diff < 20 / < 50` 的判断对「偏低」恒为真，
            // 偏低半音会比偏低一个全音看起来更准——着色整个反过来。
            diff: Math.abs(d),
        };
    });

    return {
        aligned: aligned,
        duration: tl.duration,
        score: b4.overall,
        dimensions: b4.dimensions,
        octave_shift: b4.octave_shift,
        teacher_onset: b4.teacher_onset,
        student_onset: b4.student_onset,
    };
}
```

- [ ] **Step 6: 加两个常量**

在文件顶部的 `let pollTimer = null;`（约 `:434`）附近插入：

```js
// B3 的轮询参数
const POLL_INTERVAL_MS = 1000;
const POLL_TIMEOUT_MS = 10 * 60 * 1000;   // 实测单对 77–99s，留足余量
```

- [ ] **Step 7: 重写 `doAnalyze()`**

删掉 `:785` 的 `// ---------- 分析主流程 ----------` 一直到 `:888` 那个 `}`——整条 `doAnalyze()` 连同它的分节注释一起，整段换成下面这份（分节注释在新代码里已经带了，不要让文件里留下两份）：

```js
// ---------- 分析主流程 ----------
// 同步改异步：B2 提交拿 task_id → B3 每秒轮询进度 → done 后 B4 取结果。
// 原来是一个请求挂 80–100 秒，另开一个 setInterval 读服务端日志文案猜进度。
async function doAnalyze() {
    if (!waves.t || !waves.s) {
        alert('请先上传老师和学生的音频\n（确保两个文件都显示"上传成功"）');
        return;
    }
    const btn = document.getElementById('btnAnalyze');
    btn.textContent = '分析中，请等待...';
    btn.disabled = true;

    const modal = document.getElementById('progressModal');
    const logsEl = document.getElementById('progressLogs');
    const barEl = document.getElementById('progressBar');

    modal.classList.add('show');
    logsEl.innerHTML = '';
    barEl.style.width = '0%';
    barEl.style.background = 'linear-gradient(90deg, #0066B3, #4A8AF4)';
    appendLog(logsEl, '正在提交分析任务...');

    try {
        // ① B2：提交后立即返回 task_id，不阻塞
        const r = await fetch(`${API}/api/analyze/submit`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                teacher_audio_id: waves.t.id,
                student_audio_id: waves.s.id,
            }),
        });
        if (r.status === 401) return sessionExpired();
        if (!r.ok) throw new Error(`服务器 ${r.status}: ${await r.text()}`);
        const taskId = (await r.json()).data.task_id;
        console.log('[分析] 任务已提交:', taskId);

        // ② B3：轮询到终态
        const final = await pollUntilSettled(taskId, logsEl, barEl);
        if (final.status === 'failed') {
            // failed 时 message 是后端写给用户看的可读原因（见 run_analysis）
            throw new Error(final.message || '分析失败');
        }

        // ③ B4：取完整结果。只能在 done 之后调——未完成时后端回 409。
        const rr = await fetch(`${API}/api/analyze/result/${taskId}`);
        if (rr.status === 401) return sessionExpired();
        if (!rr.ok) throw new Error(`服务器 ${rr.status}: ${await rr.text()}`);
        const b4 = (await rr.json()).data;
        console.log('[分析] B4 结果:', b4);

        analysisData = adaptResult(b4);
        // 同步播放的起点用后台检测出的开唱点，而不是文件开头——
        // 否则每次都要先播几秒静音
        waves.t.onset = b4.teacher_onset || 0;
        waves.s.onset = b4.student_onset || 0;

        drawTimeline(analysisData);
        document.getElementById('scoreVal').textContent = analysisData.score;
        document.getElementById('scoreBox').classList.add('show');

        // 符号约定：后端 _best_octave 的判据是 `s_cents + shift * 1200`
        // （analyze_service.py:483），所以 shift > 0 表示学生**原本唱得更低**，
        // 要往上升八度才跟老师对得上。原 demo 在这里写的是 `> 0 ? '高' : '低'`，
        // 方向反了 —— 两处一起改，见 Step 8 的说明。
        const shift = b4.octave_shift || 0;
        const octaveInfo = shift !== 0
            ? `（💡 系统智能提示：检测到学生演唱整体${shift > 0 ? '低' : '高'} ${Math.abs(shift)} 个八度，已自动对齐进行对比，这不影响评分准确性，请放心观察下方曲线。）`
            : '';
        document.getElementById('scoreLabel').innerHTML =
            `音准评分（百分制）<br><span style="font-size:12px;color:var(--text-light)">${octaveInfo}</span>`;

        // B4 必返回 dimensions，不再需要兜底的 mock
        updateDimensions(analysisData.dimensions);

        barEl.style.width = '100%';
        appendLog(logsEl, '分析完成！', '#4A8F6B');
        setTimeout(() => closeProgress(), 1500);

    } catch (e) {
        console.error('[分析] 失败:', e);
        barEl.style.width = '100%';
        barEl.style.background = '#B83A2F';
        appendLog(logsEl, '分析失败: ' + e.message, '#B83A2F');
        alert('分析失败: ' + e.message);
    } finally {
        stopPolling();
        btn.textContent = '开始对比分析';
        btn.disabled = false;
    }
}
```

- [ ] **Step 8: 修 tooltip 的八度方向，并确认 mock 兜底已消失**

**8a — 八度提示的方向是反的（预先存在的 bug，本次顺手修）**

这不是迁移引入的，`app-d.py` 时代就反了，但本次正好要重写这段、又要在 Step 14 验证这条分支，所以一并修掉。

> 设计文档 5.4 节写的是「其余绘图逻辑、tooltip 一行不动」。这一处是那条例外的唯一改动，理由是上面说的：不修的话 Step 14 会验出一个已知错误的结果。除此之外 tooltip 一行未动。

**判断依据（两个后端用的是同一个约定）**：

| 出处 | 代码 | 含义 |
|---|---|---|
| `app-d.py:315` | `s_shifted = [c + offset for c in s_cents_original]` | `shift>0` → 学生原本**低** |
| `app/services/analyze_service.py:483` | `shifted = s_cents + shift * 1200.0` | 同上，约定一致 |

学生比老师低一个八度唱时，`s_cents_raw ≈ t_cents − 1200`，要加 `+1200` 才对得上，于是 `best_shift = +1`。而 `app-d.py:452` 把这个值原样放进 `octave_shift` 交给前端，前端却按 `> 0 ? '高' : '低'` 渲染 —— 反了。

同一段话里的数字恰恰是对的、且与文字自相矛盾：`rawFreq = s_f0 / 2^shift` 算出来的原始频率确实更低。例如基准 353.8Hz、`shift=+1` 时，文字说「原始 176.9 Hz，已自动修正 **高** 1 个八度」——176.9 比 353.8 低，却说成「高」。

把 tooltip 里这一行（`:1054`）：

```js
            const shiftText = octaveShift > 0 ? `高 ${Math.abs(octaveShift)} 个八度` : `低 ${Math.abs(octaveShift)} 个八度`;
```

换成：

```js
            // 同 Step 7：shift > 0 是学生原本唱得更低，不是更高。
            const shiftText = octaveShift > 0 ? `低 ${Math.abs(octaveShift)} 个八度` : `高 ${Math.abs(octaveShift)} 个八度`;
```

**8b — 确认 mock 兜底已消失**

这部分已包含在 Step 7 的 `doAnalyze()` 替换里（原来的 `if (data.dimensions) { ... } else { const mock = ... }` 被换成了一行 `updateDimensions(analysisData.dimensions);`）。确认没有残留：

```bash
grep -n "const mock = {" pitch_comparison.html
```

Expected：无输出。

- [ ] **Step 9: 改 `drawTimeline()` 的 `maxTime` 取法**

找到 `drawTimeline()` 里的这两行（约 `:901–902`）：

```js
    const al = data.aligned;
    maxTime = data.teacher.times[data.teacher.times.length - 1];
```

替换成：

```js
    const al = data.aligned;
    // B4 的 timeline.duration 就是这三条曲线共用栅格的末端，与原来取
    // teacher.times 末位是同一个值；adaptResult 不再造 teacher.times 这个壳。
    maxTime = data.duration;
```

- [ ] **Step 10: 确认没有遗留的旧引用**

```bash
grep -n "filePath\|estimateProgressFromLogs\|/api/progress\|/api/analyze?\|teacher\.times\|const mock" pitch_comparison.html
```

Expected：**无输出**。任何一条命中都说明还有没改干净的地方。

- [ ] **Step 11: 语法自检**

```bash
.venv/bin/python - <<'PYEOF'
import re, pathlib
src = pathlib.Path("pitch_comparison.html").read_text(encoding="utf-8")
# 裸 <script> 一共两块：第一块（:422–1093）是主逻辑，第二块（:1106–1164）
# 是顶部登录用户条。带 src 属性的那块（:7 的 wavesurfer）匹配不到，不计入。
blocks = re.findall(r"<script>(.*?)</script>", src, re.S)
print("script 块数:", len(blocks))
open("/tmp/_pc_main.js", "w", encoding="utf-8").write(blocks[0])
PYEOF
node --check /tmp/_pc_main.js && echo "主 script 语法 OK"
```

Expected：`script 块数: 2`，然后 `主 script 语法 OK`。
若本机没有 `node`（`command -v node` 无输出），跳过这条——浏览器 console 会在 Step 13 暴露语法错误。

- [ ] **Step 12: 起后端，打开页面**

```bash
# 后端与 worker 若还没起
.venv/bin/python app-d.py &
```

浏览器访问 `http://127.0.0.1:8877/pitch_comparison.html`（**必须经 HTTP，不能 file:// 双击**：页面自 2026-09-15 起受服务端登录保护，且 `static/wavesurfer.min.js` 用的是根绝对路径）。未登录会 302 到登录页，用 `teacher01` / `xiyun@2026` 登录。

Expected：页面正常加载，右上角出现用户条（用户名 + 「教师」+ 登出按钮）。

- [ ] **Step 13: 手工走完整链路**

依次做：

1. 老师侧选 `$HOME/Desktop/test_audio/01_xipi_1931.wav`
2. 学生侧选**同一个文件**
3. 点「开始对比分析」

Expected（逐条核对，有问题就停下来查）：

- 上传后两侧状态栏都显示「上传成功，时长 182.8s」左右，波形画出来（**这一条验证 B1 新形状 + B5 取音频**）
- 进度弹窗出现，日志逐行追加并**恰好是 6 行**阶段记录，形如 `[15:04:21] 上传完成 — 任务已创建，排队中` … `[15:05:52] 评分计算 — 正在计算评分…`
- 进度条随阶段的 `progress` 真值跳（5 → 20 → 55 → 70 → 85 → 100），不是一格格匀速爬
- 约 80–100 秒后弹窗自动关闭
- 评分框显示 **92.6**（基准线，见 Task 1 脚本头部的说明——**92.6 不是 100，这是对的**）
- 五个维度条里「音准」是 **100**
- 曲线图上老师（景泰蓝）与学生（朱砂红）两条曲线**完全重合**
- 时间轴背景**整片绿色**，没有任何红色竖虚线（⚠ 标记）
- 鼠标在曲线上移动，tooltip 出现且「偏差: 0 cents」「音准优秀」；因为 `octave_shift` 为 0，学生那行只显示 `xxx Hz`，**不带**「原始 … Hz，已自动修正 …」后缀
- 点「同步播放」，两条音频从**开唱点**（约 7 秒处）开始，不是从 0 秒

- [ ] **Step 14: 验证「两条曲线真不一样」时的着色与八度分支**

**14a — 用 05 对 01 验 `diff` 的绝对值（`adaptResult` 里最险的一处）**

换一组真不一样的搭配：老师选 `05_youlongxifeng_1901.wav`、学生选 `01_xipi_1931.wav`（不同剧目，README 实测 overall 40.6 / 音准 25.8 / regions 全红）。等它跑完。

Expected：

- 完整跑完不报错
- 评分框显示 **40.6**
- 时间轴出现**大片红色**（对照 Step 13 的全绿）
- tooltip 里「偏差: N cents」出现**非零**值

**这条为什么必要**：Step 13 的基准线里 `deviation_cents` 严格为 0，`Math.abs` 取不取都等于 0 ——**基准线根本验不出这个 bug**。只有当偏差真的大幅偏离、且正负都有时，漏掉 `Math.abs` 才会暴露：`closest.diff < 20` 对负数恒为真，整张图会错误地显示成绿色。所以这条是 `adaptResult` 里最险那一行的唯一护栏。

**14b — 八度分支要用控制台打，素材里没有自然的触发条件**

上面六条素材全是戏曲、音区接近，`_best_octave` 会选 `0`（05 对 01 的 `音准=25.8` 而不是 0，正说明没有整体错八度——真错一个八度的话 DTW 对不上、音准会趋近 0）。**所以靠换搭配是走不到八度分支的，不要在这上面浪费时间。**

改成在浏览器控制台里确定性地打这个分支。14a 跑完之后，控制台执行：

```js
analysisData.octave_shift = 1;   // 伪造「学生原本低一个八度」
```

然后把鼠标移到曲线上。

Expected：tooltip 里学生那行变成形如

```
🎤 学生: 353.8 Hz（原始 176.9 Hz，已自动修正 低 1 个八度）
```

**「低」这个字是这条的断言点。** 176.9 比 353.8 低，文字说「低」才对得上；若显示「高」，就是 Step 8a 没改到位（或改反了）。`rawFreq = s_f0 / 2^shift` 那一半本来就是对的，不要被它迷惑——只有这个中文字是错的。

再执行 `analysisData.octave_shift = 0;` 恢复，tooltip 应回到纯 `xxx Hz`（不带括号后缀）。

**14c — 评分框那段提示文案只能靠读代码确认**

「💡 系统智能提示」那段是在 `doAnalyze()` 里算一次的，跑完就没法用控制台改。它的映射与 14b 是同一行逻辑（Step 7 里已改成 `shift > 0 ? '低' : '高'`），用读代码确认即可：

```bash
grep -n "检测到学生演唱整体" pitch_comparison.html
```

Expected：只有一处命中，且是 `${shift > 0 ? '低' : '高'}`（`?` 后面紧跟 `'低'`）。

- [ ] **Step 15: Commit**

```bash
git add pitch_comparison.html
git commit -m "feat: pitch_comparison 音准对比分析改为 B2/B3/B4 异步协议

分析从 app-d.py 的同步阻塞接口（GET /api/analyze 挂 80–100 秒）
迁到 B 组异步协议：B2 提交拿 task_id → B3 每秒轮询进度 → B4 取结果。
该页至此不再调用 demo_bp 的任何路由。

新增 adaptResult() 作为契约转换层，把文档 3.2 的 timeline 三条曲线
还原成绘图函数认识的 aligned[]。其中 deviation_cents 是带符号的，
必须取 |d| 当 diff——demo 时代的 diff 是绝对值，不取会让所有
「diff < 20 / < 50」的判断对偏低恒为真，着色整个反过来。

进度日志改为 6 个阶段的进入记录，进度条改用 B3 给的 progress 真值，
删掉原来按日志文案猜进度的 estimateProgressFromLogs()。
轮询加 10 分钟护栏（实测单对 77–99 秒），防 worker 挂掉时无限轮询。

上传改读 B1 的 data.{file_id, url}，不再保存已从响应移除的 filePath。
B1–B5 全挂 login_required，新增 sessionExpired() 统一处理 401。

顺带修一处 demo 时代就有的方向错误：八度提示把学生「低一个八度」
说成「高一个八度」。两个后端的 _best_octave 判据都是
`s_cents + shift * 1200`（app-d.py:315、analyze_service.py:483），
shift > 0 表示学生原本唱得更低；前端两处却都按 `> 0 ? '高' : '低'`
渲染。同一句里的 原始/已修正 Hz 数值本来就对，只有那个中文字是错的。"
```

---

### Task 4: 文档同步

**Files:**
- Modify: `CLAUDE.md`
- Modify: `DOC_ISSUES.md`（只改第 11 条）

**Interfaces:**
- Consumes: Task 2、Task 3 的已完成状态
- Produces: 无（纯文档）

- [ ] **Step 1: 改 `CLAUDE.md` 的「例外 1」段落**

找到「运行方式」一节里以 `- **例外 1 — `pitch_comparison.html`**：` 开头的那一整条，整条替换成：

```markdown
- **例外 1 — `pitch_comparison.html`**：以**根绝对路径** `/static/wavesurfer.min.js` 引入 WaveSurfer（与其它页的相对路径不一致）；且它是唯一真实跑分析链路的页面——上传走 B1、加载音频走 B5、分析走 B2（提交）+ B3（轮询）+ B4（取结果）。该页 `:428` 定义 `const API = ''`（空串 = 同源，走 nginx 的 `/api` 代理），**不要改成 `location.host + ':8877'`**：那是跨源请求，而跨源 fetch 默认不带 Cookie，后端 `login_required` 只会看到空 session 并回 401。运行：起后端 + Celery worker 后用 HTTP 访问（`file://` 打不开，页面受登录保护）。
```

- [ ] **Step 2: 合并那两条演示路由的警示**

找到以 `- **动那 4 条演示路由前先看这条**：` 开头的那一整条，以及紧随其后的 `- **但 `pitch_comparison.html` 的音频加载现在是坏的，且与 B5 无关**：` 那一条。**把这两条一起删掉**，在它们原来的位置上换成一条：

```markdown
- **`app-d.py` 的 4 条演示路由已无调用方（2026-09-20 起）**：`pitch_comparison.html` 已全部迁到 B1–B5，那 4 条（`/api/upload`、`/api/audio/demo/<path:filename>`、`/api/progress`、`/api/analyze`）不再被任何页面调用，是待删除的死代码。它们挂在 `demo_bp` 上、与业务蓝图 `api_bp` 共用 `/api` 前缀，**且至今没有任何鉴权**——所以在删掉之前不要往它们上面加功能。取音频那条是两段的 `/audio/demo/<path:filename>`，与 B5 的单段 `<int:file_id>` 不重叠（`app/api/audio_analyze.py` 末尾有实测对照）。相关议题见 `DOC_ISSUES.md` 第 11 条。
```

- [ ] **Step 3: 改「`/api/upload` 仍返回裸字段」那句**

找到「数据库接入层」一节末尾的 `- `app/response.py` 提供统一响应助手 ...` 那一条，把其中这一段：

```
**目前只有 `app-d.py` 的根路由 `/` 用了它**；`/api/upload`、`/api/progress`、`/api/analyze` 仍返回裸字段，因为 `pitch_comparison.html` 直接消费那些字段（`j.url`、`data.logs`、`data.score`），改了会当场打断音准对比演示——要统一必须先改前端。
```

替换成：

```
`/api/audio/upload`（B1）与 `/api/analyze/submit`（B2）也已用它（2026-09-20 起）；`/api/analyze/result`（B4）回的是 `ok(analyze_service.result(...))`，同样是统一信封。仍返回裸字段的只剩 `app-d.py` `demo_bp` 上那 4 条演示路由——它们已无调用方，随 `demo_bp` 一起待删。
```

- [ ] **Step 4: 更新 `DOC_ISSUES.md` 第 11 条**

在第 11 条的正文末尾（`**本节议题仍未了结**：...` 那一段之后）追加：

```markdown
**2026-09-20 更新**：`pitch_comparison.html` 已迁到 B1/B2/B3/B4/B5，不再调用 `demo_bp` 的任何路由。本节记录的两个悬案随之解决：

- **「音频加载是坏的」** —— 由 B1 返回 B5 的 `url`（`url_for("api.audio_download", ...)` 生成）解决。前端不再拼 `${API}${j.url}` 而是 `${API}${j.data.url}`，且 `url` 本身已含 `/api` 前缀，不再重复。
- **「结果契约无法平滑切换」** —— 由前端新增的 `adaptResult()` 转换层解决。它把 3.2 契约的 `timeline` 三条曲线用 `t_cents = 1200·log2(t_hz/ref_hz)`、`s_cents = t_cents + deviation_cents` 还原成绘图函数认识的 `aligned[]`。契约不同构不再是障碍。

**但 `demo_bp` 那 4 条演示路由保留未删**（这是本次的明确决策，不是遗漏），已无任何调用方，是后续的独立清理项。它们至今没有鉴权——删之前不要往上面加功能。
```

- [ ] **Step 5: 确认 CLAUDE.md 里没有残留的旧描述**

```bash
grep -n "位置上的 pip\|音频加载现在是坏的\|前缀重复\|location.host + \":8877\"\|/api/progress" CLAUDE.md
```

Expected：**无输出**。

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md DOC_ISSUES.md
git commit -m "docs: 同步音准对比页迁移后的项目说明

CLAUDE.md：
- 「例外 1」段落改写——该页端点从 demo_bp 的 4 条改为 B1–B5，
  并写明 API 空串是同源、不能改成 8877（跨源不带 Cookie）
- 两条演示路由警示合并为一条「已无调用方，待删除」
- 去掉「仍返回裸字段……要统一必须先改前端」的过时说明

DOC_ISSUES.md 第 11 条补 2026-09-20 更新：该条记录的两个悬案
（音频加载坏掉、结果契约无法平滑切换）均已解决，分别由 B1 返回
B5 的 url、以及前端的 adaptResult() 转换层；demo_bp 保留未删。"
```

---

## 验收总览

全部完成后，以下命令必须全绿：

```bash
scripts/smoke_analyze.sh          # 退出码 0，约 2 分钟
scripts/smoke_auth.sh             # 退出码 0 —— 回归闸门：本次不该动到 A 组
python scripts/check_db.py        # 退出码 0 —— 回归闸门：本次没改表结构
grep -n "filePath\|estimateProgressFromLogs\|/api/progress\|/api/analyze?" pitch_comparison.html   # 无输出
```

外加 Task 3 Step 13 / Step 14 两轮浏览器手工验证。

## 本次明确不做（避免后来者误以为是遗漏）

| 项 | 原因 |
|---|---|
| 删除 `app-d.py` 的 `demo_bp` 与那段 librosa/DTW 代码 | 本次决策保留，仅登记为无调用方（`DOC_ISSUES.md` 第 11 条） |
| 给 `demo_bp` 的 4 条路由加鉴权 | 已是待删死代码，加鉴权等于给待删代码增加维护面 |
| 修 B2 不校验音频归属（`DOC_ISSUES.md` 第 15 条） | 要先定「教师能否分析他人录音」这类业务规则，文档没给依据 |
| 在前端渲染 `words` / `regions` | 现有着色由 `aligned` 分片算出，视觉等价；逐字展示是独立需求（YAGNI） |
| 改五个维度的 `_logistic` 的 `mid` 让满分可达 | 那组阈值是从 `app-d.py` 照搬、拿真实录音调过的，改了会让本页与演示页对不上 |
| 调大 `MAX_AUDIO_SEC`（180）以跑完整条 01 | 冒烟脚本的基准线期望值（92.6 / 完全重合 / 全绿）正是在这个截断下测出来的 |
