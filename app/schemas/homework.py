from datetime import date

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
