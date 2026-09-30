from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class HomeworkListItem(BaseModel):
    """作业列表的一行（功能 4.1）。

    文档（《1-PRD》4.1、《3-功能清单》4.1、《5-接口清单》F1）的全部描述是
    「作业列表展示 — 进度/截止/提交人数」，**没有定义状态有哪些档、怎么判、
    分母放哪、怎么排序**。以下口径是本次实现定死的，与看板 G7
    （`app/schemas/dashboard.py::HomeworkProgressItem`）**逐字同源**——同一份数据
    在两条接口上必须是同一个档位，否则教师会在看板和作业页看到两个状态：

    - grading 批改中：有提交且存在未终审的提交（`submissions.status != 'reviewed'`）。
      优先级最高——截止没截止都要批；
    - closed 已截止：`homeworks.status == 'closed'` **或**截止日已过；
      截止当天算最后一天，仍可提交，不判已过；
    - ongoing 进行中：其余。

    **与 G7 的差别只有分母的位置**：G7 把分母放在响应级的一个 `student_count`，
    这里放在**每行**（`total`）。两个理由——(1) 页面每行就要渲染 `5/9` 与
    `submitted/total*100` 的进度条，行内拿到自己的分母最直接；(2) `homeworks`
    表目前没有班级/名单字段，所有作业共用同一个分母，但真实教学里作业是按班级
    布置的（`DOC_ISSUES.md` 第 25 条第 2 点），一旦补上班级维度每份作业的分母就会
    真的不同——那时响应级的一个数立刻作废，行内的不用改。所以这里**不再另给**
    响应级 `student_count`：那是同一个数字的第二个来源，漂移了就是线上事故。
    """

    model_config = ConfigDict(from_attributes=True)
    homework_id: int
    title: str
    deadline: date | None                 # 档案没填为 None，页面不显示截止
    demo_title: str | None                # 曲目名；作业没挂曲目（demo_id 为 NULL）为 None
    demo_role: str | None                 # 行当（青衣…）
    demo_banshi: str | None               # 板式（西皮流水…）
    submitted_count: int                  # 已提交**人数**（按学生去重）
    total: int                            # 分母：应提交人数（在册学生数）
    progress: float                       # submitted_count / total，0-1；total 为 0 时给 0
    pending_review_count: int             # 待批（未终审）条数，为 0 说明不用批
    status: str                           # grading / ongoing / closed


class HomeworkListResponse(BaseModel):
    """作业列表（功能 4.1）。

    不过滤、不截断、不分页：返回**全部**作业，由页面自己决定展示几条。
    库里没有作业时 `homeworks` 是 `[]`，**不是 404**。
    """

    model_config = ConfigDict(from_attributes=True)
    homeworks: list[HomeworkListItem]


class SubmissionTag(BaseModel):
    """待批改卡片上的一个 AI 归因标签。

    `label` 是 `ai_detail.defects[].label` 的**原文**（如「气息支撑不足」），后端
    不改写、不缩写——批改详情区（F5）用的是同一批文字，两处对不上教师会以为是两回事。

    `severity` 是 `defects[].status` 的**语义值透传**（high/medium/low），**不是**
    页面的 CSS 类名（`.tag.danger/.warn/.info`，见 homework.html:270-272）。出表现层
    词汇等于把「这个页面用这套配色」写进接口契约，换一版设计就要改后端。前端接到后
    自己映射；取到未知档时按中性色渲染即可，后端不做白名单过滤——滤掉一个未预期的
    分级会让标签凭空消失。
    """

    label: str
    severity: str


class PendingSubmissionItem(BaseModel):
    """待批改提交列表的一行（功能 4.3「AI 初评待终审」）。

    「待批改」= `submissions.status IS NULL OR status != 'reviewed'`，与 F1 的
    `pending_review_count` 逐字同源（口径见 spec 3.1）。因此 F1 里 hw12 的
    `pending_review_count` 与本列表的条数在干净数据下必然相等，验证时按这条对。

    **学生字段平铺，不做嵌套对象**：与同模块的 `demo_title/demo_role/demo_banshi`
    保持一种风格；嵌套更好看，但会引出「F5 要不要复用同一个 StudentBrief 模型」的
    跨接口耦合，而本项目的 schema 现在是彼此独立的，不为一个四字段对象破例。

    `student_name` / `student_level` / `student_avatar` 都可空：后两者是列本身可空
    （**张三的 avatar 是空串不是 NULL**，前端用 `||` 兜不到要看空串），前者还多一种
    情形——`students.user_id` 指向不存在的 user 时 join 不到（DOC_ISSUES 第 21/24 条
    描述的那类脏数据）。

    `tags` 的条数**没有上限**（spec 3.6）：页面自己声明的口径是「只展示置信度 > 0.7
    的标签」，那就按这条来，不再叠一层截断——真数据里刘思琪有 3 条过线，截到 2 会
    砍掉 0.71 的「拖腔不足」而留下 0.72 的「收尾偏急」，同量级留下哪个纯看运气。
    撑破布局是前端 CSS 该解决的问题，不该由后端悄悄丢数据。
    """

    model_config = ConfigDict(from_attributes=True)
    submission_id: int
    student_id: int | None              # students.id（不是 users.id）
    student_name: str | None            # users.display_name，经 students.user_id 拐一次
    student_avatar: str | None          # 可能是空串
    student_level: str | None           # 初学 / 进阶 / 高级
    ai_score: float | None              # AI 初评分数
    submitted_at: datetime | None       # 列可空；出参是 ISO-8601
    tags: list[SubmissionTag]           # 置信度 > 0.7 的归因标签，按置信度降序


class PendingSubmissionListResponse(BaseModel):
    """待批改提交列表（功能 4.3）。

    作业存在但没有待批提交时 `submissions` 是 `[]`，**不是 404**——「这份作业没有
    东西要批」是正常状态。作业**不存在**才 404，由 service 抛 BusinessError。

    与 F1「库里没有作业返回 `[]` 而非 404」不矛盾：F1 查的是集合（空集合是合法
    结果），这里查的是一个具名资源。

    `homework_title` 是给批改详情区标题用的：页面现在用 `HOMEWORKS[0].title` 硬编码
    （homework.html:813），接入后应显示当前作业名。前端本可以从 F1 的列表里查，但
    那要多一次请求和一份前端状态；这里一个字符串就够。
    `homework_id` 是路径参数回显，异步返回时用来确认是不是当前选中的那份，避免竞态。

    不分页（spec 3.8）：一份作业的待批提交是教师一次批完的工作量（真库 5 条），
    分页要的 page/size/total 三个参数与前端翻页状态远超收益。
    """

    model_config = ConfigDict(from_attributes=True)
    homework_id: int
    homework_title: str
    submissions: list[PendingSubmissionItem]
