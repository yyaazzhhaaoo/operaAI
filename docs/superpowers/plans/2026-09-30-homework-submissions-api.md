# F4 `GET /api/homeworks/<id>/submissions` 实施计划

日期：2026-09-30
spec：`docs/superpowers/specs/2026-09-30-homework-submissions-api-design.md`
接口：《5-接口清单》F4 / 功能 4.3

四个任务，按序做。每步都给了完整代码与**预期输出**——对不上就是没做对，不要往下走。

---

## 任务 1：`homeworks_repo` 加两个查询

文件：`app/repositories/homeworks_repo.py`

### 步骤 1.1 补 import

第 4 行现在是：

```python
from app.models import Homework, Submission, TeacherDemo
```

改成（`Student`、`User` 是新增的，LEFT JOIN 要按 `students.user_id` 拐一次拿姓名，不能直接 `db.get(User, student_id)`——两者不是同一套 id，见 `DOC_ISSUES.md` 第 21 条）：

```python
from app.models import Homework, Student, Submission, TeacherDemo, User
```

**先确认 `app/models/__init__.py` 里导出了 `Student` 和 `User`**（`user_repo.py` 是从 `app.models.student` / `app.models.user` 直接 import 的，两条路都在用；这里跟本文件的既有风格走 `app.models`）。

### 步骤 1.2 文件末尾追加

```python
def get_homework(db: Session, homework_id: int) -> Homework | None:
    """按 id 取作业，不存在返回 None。供 F4 判 404。"""
    return db.get(Homework, homework_id)


def get_pending_submissions(
    db: Session, homework_id: int
) -> list[tuple[Submission, str | None, str | None, str | None]]:
    """某作业下未终审的提交，[(提交, 姓名, 等级, 头像)]，最早提交在前。

    「未终审」= `status IS NULL OR status != 'reviewed'`，与上面的 get_progress_rows
    的 `pending` **逐字同源**——同一批提交在 F1（出条数）与 F4（出行本身）上必须
    是一致的，改这里必须同时改那里。NULL 同样要显式兜：`NULL != 'reviewed'` 在
    SQL 里求值为 NULL 而非 true。

    与 F1 的 `pending` 有一处**刻意不同：这里不过滤在册名单**。F1 过滤是为了让分子
    不超过分母（students 表里连 teacher01 都有行），F4 没有分母，过滤只会让「提交人
    不在名单里」的真实提交永远不出现在待批列表里——教师批不到它，比数目对不上严重。
    代价是脏数据下这里的条数会大于 F1 的 pending_review_count，那是预期不是 bug。

    两个 join 都必须是 LEFT：`submissions.student_id` 可空，INNER JOIN 会把
    student_id 为 NULL 的提交整条删掉，同样造成「批不到」；`students.user_id` 那层
    用 LEFT 则保证 students 有行而 users 缺失时至少还能出 student_id。

    排序 `submitted_at ASC NULLS LAST, id ASC`。`id` 不是装饰：库里 24/26/27 三条的
    submitted_at 完全相同，只按时间排则顺序由执行计划决定，前端选中的提交会在刷新
    后跳到别人身上。NULL 排最后是因为那说明入库没写时间，不该插队。
    """
    stmt = (
        select(Submission, User.display_name, Student.level, Student.avatar)
        .outerjoin(Student, Student.id == Submission.student_id)
        .outerjoin(User, User.id == Student.user_id)
        .where(Submission.homework_id == homework_id)
        .where((Submission.status.is_(None)) | (Submission.status != "reviewed"))
        .order_by(Submission.submitted_at.asc().nulls_last(), Submission.id.asc())
    )
    return [tuple(row) for row in db.execute(stmt).all()]
```

### 步骤 1.3 单独验一次 repo（不起 Flask）

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && source .venv/bin/activate
python - <<'PY'
from app.db import SessionLocal
from app.repositories import homeworks_repo as r
with SessionLocal() as db:
    rows = r.get_pending_submissions(db, 12)
    print([(s.id, n, lv, av, str(s.submitted_at)) for s, n, lv, av in rows])
    print("hw13:", r.get_pending_submissions(db, 13))
    print("hw999 exists:", r.get_homework(db, 999) is not None)
PY
```

**预期输出**（顺序必须是这个，两组相同时间的各自按 id 升序）：

```
[(24, '刘思琪', '初学', '🎵', '2026-08-01 00:00:00'),
 (26, '孙志远', '初学', '🥁', '2026-08-01 00:00:00'),
 (27, '赵雨桐', '进阶', '🎼', '2026-08-01 00:00:00'),
 (23, '李小燕', '初学', '🎭', '2026-08-02 00:00:00'),
 (25, '周明轩', '初学', '🎹', '2026-08-02 00:00:00')]
hw13: []
hw999 exists: False
```

---

## 任务 2：`app/schemas/homework.py` 加出参

文件：`app/schemas/homework.py`

### 步骤 2.1 文件头 import 补 `datetime`

```python
from datetime import date, datetime
```

### 步骤 2.2 文件末尾追加三个模型

```python
class SubmissionTag(BaseModel):
    """待批改卡片上的一个 AI 归因标签。

    `label` 是 `ai_detail.defects[].label` 的**原文**（如「气息支撑不足」），后端
    不改写、不缩写——页面的详情区（F5）会用同一批文字，两处对不上教师会以为是两回事。

    `severity` 是 `defects[].status` 的**语义值透传**（high/medium/low），**不是**
    页面的 CSS 类名（`.tag.danger/.warn/.info`，见 homework.html:270-272）。出表现层
    词汇等于把「这个页面用这套配色」写进接口契约，换版设计就要改后端。前端接到后自己
    映射；取到未知档时按中性色渲染，后端不做白名单过滤——滤掉一个未预期的分级会让
    标签凭空消失。
    """

    label: str
    severity: str


class PendingSubmissionItem(BaseModel):
    """待批改提交列表的一行（功能 4.3「AI 初评待终审」）。

    「待批改」= `submissions.status IS NULL OR status != 'reviewed'`，与 F1 的
    `pending_review_count` 逐字同源（口径见 spec 3.1）。

    **学生字段平铺，不做嵌套对象**：与同模块的 `demo_title/demo_role/demo_banshi`
    保持一种风格；嵌套会引出「F5 要不要复用同一个 StudentBrief」的跨接口耦合，而
    本项目的 schema 现在是彼此独立的。

    `student_name` / `student_level` / `student_avatar` 都可空：后两者是列本身可空
    （**张三的 avatar 是空串不是 NULL**），前者还多一种情形——`students.user_id` 指向
    不存在的 user 时 join 不到（DOC_ISSUES 第 21/24 条描述的那类脏数据）。前端要兜。

    `tags` 的条数**没有上限**（spec 3.6）：页面自己声明的口径是「只展示置信度 > 0.7」，
    那就按这条来，不再叠一层截断——真数据里刘思琪有 3 条过线，截到 2 会砍掉 0.71 的
    「拖腔不足」而留下 0.72 的「收尾偏急」，同量级留下哪个纯看运气。撑破布局是前端
    CSS 的问题，不该由后端悄悄丢数据。
    """

    model_config = ConfigDict(from_attributes=True)
    submission_id: int
    student_id: int | None
    student_name: str | None
    student_avatar: str | None
    student_level: str | None
    ai_score: float | None
    submitted_at: datetime | None
    tags: list[SubmissionTag]


class PendingSubmissionListResponse(BaseModel):
    """待批改提交列表（功能 4.3）。

    作业存在但没有待批提交时 `submissions` 是 `[]`，**不是 404**——「这份作业没有
    东西要批」是正常结果。作业**不存在**才 404（由 service 抛）。

    `homework_title` 是给详情区标题用的：页面现在用 `HOMEWORKS[0].title` 硬编码
    （homework.html:813），接入后应显示当前作业名。前端本可以从 F1 的列表里查，
    但那要多一次请求和一份前端状态；这里一个字符串就够。
    `homework_id` 是路径参数回显，异步返回时确认是不是当前选中的那份，避免竞态。

    不分页（spec 3.8）：一份作业的待批提交是教师一次批完的工作量。
    """

    model_config = ConfigDict(from_attributes=True)
    homework_id: int
    homework_title: str
    submissions: list[PendingSubmissionItem]
```

---

## 任务 3：`homework_service` 加 service

文件：`app/services/homework_service.py`

### 步骤 3.1 import 补

```python
from app.common.errors import BusinessError
from app.schemas.homework import (
    HomeworkListItem,
    HomeworkListResponse,
    PendingSubmissionItem,
    PendingSubmissionListResponse,
    SubmissionTag,
)
```

（现有代码里 `HomeworkListItem` / `HomeworkListResponse` 是分开两行 import 的，合并成上面这一处即可。）

### 步骤 3.2 文件末尾追加

```python
# 标签的置信度下限（spec 3.5）。0.7 这个数是页面自己声明的（「只展示置信度 > 0.7
# 的标签」），**严格大于**，0.7 本身不算。文档从未规定要按置信度筛，也没规定阈值。
_CONFIDENCE_MIN = 0.7


def _num(v) -> float | None:
    """JSONB 列没有类型约束，只放行真正的数值，其余一律 None。同 library_service._num。

    bool 要单独排除——Python 里 isinstance(True, int) 是 True。
    """
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v


def _tags_of(ai_detail: dict | None) -> list[SubmissionTag]:
    """从 ai_detail.defects 取置信度过线的标签，按置信度降序（spec 3.4–3.6）。

    整条路径防御式取值：ai_detail 可空、结构由 AI 侧写入不受本服务约束，**一条坏
    数据不该让整个待批列表 500**——教师看不到任何待批提交，比少看一个标签严重得多。
    所以 ai_detail 为 None / defects 不是 list / 元素不是 dict，一律跳过（最坏出 []）。

    **要重排**：库里的 defects 不是按置信度排的（李小燕那条是 0.82 / 0.45 / 0.78），
    不排的话过滤完卡片上第一个标签会是 0.78 而不是 0.82。

    label 缺失或空串的整条丢弃：构造不出标签文字，前端会渲染成一个空胶囊。
    """
    if not isinstance(ai_detail, dict):
        return []
    defects = ai_detail.get("defects")
    if not isinstance(defects, list):
        return []

    tags: list[tuple[float, SubmissionTag]] = []
    for d in defects:
        if not isinstance(d, dict):
            continue
        label = d.get("label")
        if not isinstance(label, str) or not label:
            continue
        conf = _num(d.get("confidence"))
        if conf is None or conf <= _CONFIDENCE_MIN:
            continue
        # severity 原样透传，不做白名单；取不到就给空串，前端按未知档渲染
        sev = d.get("status")
        tags.append((conf, SubmissionTag(
            label=label,
            severity=sev if isinstance(sev, str) and sev else "unknown",
        )))

    tags.sort(key=lambda t: -t[0])
    return [t for _, t in tags]


def list_pending_submissions(db: Session, homework_id: int) -> PendingSubmissionListResponse:
    """某作业的待批改提交列表（功能 4.3）。作业不存在抛 404。"""
    hw = homeworks_repo.get_homework(db, homework_id)
    if hw is None:
        raise BusinessError(404, "作业不存在")

    items = [
        PendingSubmissionItem(
            submission_id=sub.id,
            student_id=sub.student_id,
            student_name=name,
            student_avatar=avatar,
            student_level=level,
            ai_score=sub.ai_score,
            submitted_at=sub.submitted_at,
            tags=_tags_of(sub.ai_detail),
        )
        for sub, name, level, avatar in homeworks_repo.get_pending_submissions(db, homework_id)
    ]

    return PendingSubmissionListResponse(
        homework_id=hw.id,
        homework_title=hw.title,
        submissions=items,
    )
```

> 注意 `get_pending_submissions` 返回的元组顺序是 `(提交, 姓名, 等级, 头像)`，别按
> 变量名的字母序想当然写成 `(sub, name, avatar, level)`——解包顺序错了不会报错，
> 只会让等级和头像对调（两个都是 str，pydantic 照收）。

---

## 任务 4：换掉 `app/api/homeworks.py` 的桩

文件：`app/api/homeworks.py`

### 步骤 4.1 改路由

把：

```python
@api_bp.route("/homeworks/<id>/submissions",methods=["GET"])
@login_required
@teacher_required
def homeworks_submissions(id):
    return ok(id)
```

换成：

```python
@api_bp.route("/homeworks/<int:homework_id>/submissions",methods=["GET"])
@login_required
@teacher_required
def homeworks_submissions(homework_id):
    # mode="json"：出参里有 datetime（submitted_at）。默认 model_dump() 会给 Flask
    # 一个 datetime 对象，而它按 RFC-822 序列化成 "Sat, 01 Aug 2026 00:00:00 GMT"；
    # mode="json" 出的是 ISO-8601（"2026-08-01T00:00:00"）。同 get_homeworks。
    return ok(homework_service.list_pending_submissions(
        get_db(), homework_id).model_dump(mode="json"))
```

三处变化：`<id>` → `<int:homework_id>`（非数字路径在路由层 404，不进业务代码，是本项目既定约定）、参数改名、返回体换掉。

**`<int:...>` 转换器只能用在 `/submissions` 这一段的路由上**，同一个文件里另外几个桩（`homeworks_submit`、`homeworks_detail`、`submissions_review`、`submissions_calibration`）本次不动——它们还没实现，改了会让后面认不出哪些是「已落地的约定」。

### 步骤 4.2 语法与路由自检

```bash
cd /Users/meiyazhao/Documents/lianshu/operaAI && source .venv/bin/activate
python -c "
from app import create_app
app = create_app()
print([str(r) + ' ' + ','.join(sorted(r.methods - {'HEAD','OPTIONS'}))
       for r in app.url_map.iter_rules() if 'submission' in str(r)])
"
```

**预期**：能看到 `/api/homeworks/<int:homework_id>/submissions GET`（Flask 打印规则时是 `<int:homework_id>`）。

---

## 任务 5：端到端验证

见 spec §5。要点重列：

```bash
# 起服务（另开一个终端）
cd /Users/meiyazhao/Documents/lianshu/operaAI && source .venv/bin/activate
python app-d.py            # 8877

# 登录拿 cookie（curl 走 Flask 直连 8877；经 nginx 也行，见 CLAUDE.md）
curl -s -c /tmp/f4.jar -X POST http://127.0.0.1:8877/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"teacher01","password":"xiyun@2026"}'
```

逐项对：1) hw12 五条、顺序 24,26,27,23,25、tags 条数 2/3/2/2/1；2) hw13/hw14 → `[]`；
3) hw999 → 404「作业不存在」；4) `/api/homeworks/abc/submissions` → 404「**接口不存在**」——
   两个都是统一信封、都是 `code:404`，**只能靠 message 区分**：前者是 service 抛的
   BusinessError，后者是路由层没匹配上、由 `errors.py` 里那条把 Werkzeug HTML 404
   包成信封的处理器兜的（`app/common/errors.py:94` 的注释说明了为什么必须有它）；
5) F1 的 hw12 `pending_review_count == 5 == len(submissions)`；6) stu001 → 403、无 cookie → 401；
7) 兜底（`status=NULL`、坏 `ai_detail`）；8) `check_db.py` 无新增漂移、临时改动按 id 复原。

**第 7 项的清理纪律**：临时改的那几行**只能按抓到的 id 改回去**，不要 `UPDATE ... WHERE <别的列>`，
更不要 `DELETE`。改完再跑一次基线 sql 确认回到 5 条 `ai_scored`。
