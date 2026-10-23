# -*- coding: utf-8 -*-
"""知识图谱接口出参（I1 / I2 / I3 / I4）。

节点与边沿用数据库的词表（node_type: skill/segment/opera，edge_type:
prereq/contains），页面侧的展示词表（technique/phrase/piece、
DEPENDS_ON/REQUIRES/BELONGS_TO）由前端映射——接口不迁就某一张页面的配色。
"""
from pydantic import BaseModel


class GraphNodeOut(BaseModel):
    id: int
    node_type: str                    # skill / segment / opera
    label: str
    ref_id: int | None
    # 只有 skill 节点有值：全班最新 p_l 的均值。没有同名 BKT 技法时为 null
    # （null 表示「没有数据源」，不是 0 分，见 DOC_ISSUES 第 23 条）。
    mastery: float | None
    mastery_threshold: float          # coalesce(mastery_threshold, 0.60)
    pos_x: float | None               # 布局持久化留给 I4，本次页面忽略
    pos_y: float | None


class GraphEdgeOut(BaseModel):
    id: int
    source: int
    target: int
    edge_type: str                    # prereq / contains


class GraphOverview(BaseModel):
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]


class GraphNodeRef(BaseModel):
    """依赖链里出现的一个节点（前置/后置/关联唱句等）。"""

    id: int
    label: str
    mastery: float | None


class GraphDependencyOut(GraphNodeRef):
    """直接前置技法。threshold 是该前置节点自己的达标线，met 判它达没达标。

    mastery 为 null 时 met 也是 null——没有数据不能判成「未达标」。
    """

    threshold: float
    met: bool | None


class GraphNodeDetail(BaseModel):
    node: GraphNodeOut
    prerequisites: list[GraphDependencyOut]   # 直接前置（prereq 入边）
    successors: list[GraphNodeRef]            # 直接后置（prereq 出边）
    # 递归前置链：DFS 后序，最深的前置排在前面，已去重、带环检测。
    chain: list[GraphNodeRef]
    # contains 边的三类邻居，按对方节点类型分列。技法带自己的达标线与是否达标
    # （唱句详情里的「所需技法」要用），唱段/剧目没有这两项。
    related_skills: list[GraphDependencyOut]
    related_segments: list[GraphNodeRef]
    related_operas: list[GraphNodeRef]


class LockBlockerOut(BaseModel):
    """某名学生卡住他的一条门禁技法。

    mastery 是**该学生本人**在这条技法上的最新 p_l，不是班级均值；
    threshold 是这条技法节点自己的达标线。
    """

    id: int
    label: str
    mastery: float
    threshold: float


class LockedStudentOut(BaseModel):
    student_id: int          # students.id，不是 users.id
    student_name: str | None
    blocked_by: list[LockBlockerOut]


class GraphLockDiagnosis(BaseModel):
    """I3 锁定诊断（功能 7.3）。

    locked 只表示「是否存在被未达标前置卡住的学生」；没有前置依赖、前置技法
    全部无数据、或练过前置的学生都已达标时都是 false，具体原因由 reason 说明
    （null 的语义是「没有数据源」，不能把无数据当成未达标）。
    """

    node: GraphNodeOut
    locked: bool
    reason: str
    # 受影响技法：技法节点 = 自身 + 递归下游；唱段节点 = 卡住学生的所需技法；
    # 剧目节点不参与诊断，返回空列表。
    affected_skills: list[GraphNodeRef]
    # 至少卡住一名学生的门禁技法（技法节点看递归前置链，唱段看所需技法）。
    # class_mastery 与 met 都是**班级层面**的，可能出现 met=true 但个别学生未达标。
    blocking_prerequisites: list[GraphDependencyOut]
    students: list[LockedStudentOut]


class GraphLayoutOut(BaseModel):
    """I4 布局保存/重置的结果。updated 是写入或清空的节点数。"""

    updated: int
    reset: bool
