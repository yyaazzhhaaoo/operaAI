# -*- coding: utf-8 -*-
"""知识图谱取数与布局：I1 全量节点+边、I2 单节点依赖链、I3 锁定诊断、I4 布局保存。

掌握度口径（DOC_ISSUES 第 23 条）：`graph_nodes` 的 15 个 skill 节点里只有 7 个
与 `bkt_history` 的技法名严格同名，其余 8 个（归韵、音准感知、声带控制、
音准稳定性、润腔、咬字基础、装饰音基础、听辨能力）在 BKT 体系里没有对应记录。
**不做别名映射**——「归韵」与「归韵咬字」是否同一技法仍待文档方确认，猜错了
会把两条独立的教学进度混成一个数。取不到就回 null：null 表示没有数据源，
不是 0 分（与 homework_service 等模块的约定一致）。

「班级」在本项目没有建模（schema 里没有班级/师生归属表），所以均值取自
全部在册学生的最新 p_l，与 dashboard_service、student_service 的口径一致。
没练过某技法的学生不参与该技法的均值计算，分母是练过的人数而不是全班人数。
"""
from sqlalchemy.orm import Session

from app.common.errors import BusinessError
from app.models import GraphEdge, GraphNode
from app.repositories import bkt_history_repo, graph_repo, user_repo
from app.schemas.graph import (
    GraphDependencyOut,
    GraphEdgeOut,
    GraphLayoutOut,
    GraphLockDiagnosis,
    GraphNodeDetail,
    GraphNodeOut,
    GraphNodeRef,
    GraphOverview,
    LockBlockerOut,
    LockedStudentOut,
)

# 与 graph_repo.get_prereq_edges 的 coalesce 兜底保持一致：列虽然有 default 0.60，
# 但没建 NOT NULL，显式写 NULL 是可能的。
DEFAULT_THRESHOLD = 0.60


def _skill_mastery(db: Session) -> dict[str, float]:
    """技法名 -> 全班最新 p_l 的算术平均（保留 3 位小数）。"""
    by_skill: dict[str, list[float]] = {}
    for row in bkt_history_repo.get_latest_by_skill(db):
        if row.skill is None or row.p_l is None:
            continue
        by_skill.setdefault(row.skill, []).append(row.p_l)
    return {skill: round(sum(vals) / len(vals), 3) for skill, vals in by_skill.items()}


def _node_out(node: GraphNode, mastery: dict[str, float]) -> GraphNodeOut:
    return GraphNodeOut(
        id=node.id,
        node_type=node.node_type,
        label=node.label,
        ref_id=node.ref_id,
        # 只有技法节点有掌握度；唱段/剧目没有数据源
        mastery=mastery.get(node.label) if node.node_type == "skill" else None,
        mastery_threshold=(
            node.mastery_threshold if node.mastery_threshold is not None else DEFAULT_THRESHOLD
        ),
        pos_x=node.pos_x,
        pos_y=node.pos_y,
    )


def overview(db: Session) -> GraphOverview:
    """I1：全量节点+边（功能 7.1/7.4，按层筛在前端做）。"""
    mastery = _skill_mastery(db)
    nodes = [_node_out(n, mastery) for n in graph_repo.get_all_nodes(db)]
    edges = [
        GraphEdgeOut(id=e.id, source=e.source_id, target=e.target_id, edge_type=e.edge_type)
        for e in graph_repo.get_all_edges(db)
        if e.source_id is not None and e.target_id is not None
    ]
    return GraphOverview(nodes=nodes, edges=edges)


def _unique(ids: list[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for nid in ids:
        if nid not in seen:
            seen.add(nid)
            out.append(nid)
    return out


def node_detail(db: Session, node_id: int) -> GraphNodeDetail:
    """I2：单节点依赖链（功能 7.2：前置/后置/关联唱句/班级掌握度）。"""
    node = graph_repo.get_node(db, node_id)
    if node is None:
        raise BusinessError(404, "节点不存在")

    mastery = _skill_mastery(db)
    nodes: dict[int, GraphNode] = {n.id: n for n in graph_repo.get_all_nodes(db)}
    edges: list[GraphEdge] = [
        e
        for e in graph_repo.get_all_edges(db)
        if e.source_id is not None and e.target_id is not None
    ]

    prereq_in: dict[int, list[int]] = {}    # 节点 -> 它的直接前置
    prereq_out: dict[int, list[int]] = {}   # 节点 -> 它的直接后置
    contains_in: dict[int, list[int]] = {}
    contains_out: dict[int, list[int]] = {}
    for e in edges:
        if e.edge_type == "prereq":
            prereq_in.setdefault(e.target_id, []).append(e.source_id)
            prereq_out.setdefault(e.source_id, []).append(e.target_id)
        elif e.edge_type == "contains":
            contains_in.setdefault(e.target_id, []).append(e.source_id)
            contains_out.setdefault(e.source_id, []).append(e.target_id)

    def ref(nid: int) -> GraphNodeRef:
        n = nodes[nid]
        return GraphNodeRef(
            id=n.id,
            label=n.label,
            mastery=mastery.get(n.label) if n.node_type == "skill" else None,
        )

    def dependency(nid: int) -> GraphDependencyOut:
        n = nodes[nid]
        m = mastery.get(n.label) if n.node_type == "skill" else None
        thr = n.mastery_threshold if n.mastery_threshold is not None else DEFAULT_THRESHOLD
        # 没有掌握度数据时 met 是 null，不能判成「未达标」
        return GraphDependencyOut(
            id=n.id,
            label=n.label,
            mastery=m,
            threshold=thr,
            met=None if m is None else m >= thr,
        )

    def ancestors(start: int) -> list[int]:
        """递归前置链：DFS 后序（最深的前置在前），已去重并带环检测。"""
        seen: set[int] = {start}
        out: list[int] = []

        def visit(nid: int) -> None:
            for pid in prereq_in.get(nid, []):
                if pid in seen or pid not in nodes:
                    continue
                seen.add(pid)
                visit(pid)
                out.append(pid)

        visit(start)
        return out

    # contains 的两个方向合起来看，再按对方节点的类型分列：
    # 技法节点拿到「包含它的唱段」，唱段节点拿到「所需技法」与「所属剧目」，
    # 剧目节点拿到「包含的唱段」——同一套逻辑覆盖三层。
    neighbours = _unique(contains_in.get(node.id, []) + contains_out.get(node.id, []))
    neighbours = [nid for nid in neighbours if nid in nodes and nid != node.id]

    def related_by_type(node_type: str):
        if node_type == "skill":
            # 技法邻居同时给出达标线与是否达标，供唱句详情的「所需技法」使用
            return [dependency(nid) for nid in neighbours if nodes[nid].node_type == "skill"]
        return [ref(nid) for nid in neighbours if nodes[nid].node_type == node_type]

    return GraphNodeDetail(
        node=_node_out(node, mastery),
        prerequisites=[
            dependency(nid) for nid in _unique(prereq_in.get(node.id, [])) if nid in nodes
        ],
        successors=[ref(nid) for nid in _unique(prereq_out.get(node.id, [])) if nid in nodes],
        chain=[ref(nid) for nid in ancestors(node.id)],
        related_skills=related_by_type("skill"),
        related_segments=related_by_type("segment"),
        related_operas=related_by_type("opera"),
    )


def _student_mastery(db: Session) -> dict[int, dict[str, float]]:
    """学生 id -> {技法名: 本人最新 p_l}。

    键是 students.id：`bkt_history.student_id` 的外键指向 students.id，不是
    users.id（见 DOC_ISSUES 第 21 条）。取数口径与 _skill_mastery 相同，
    只是不跨学生聚合。
    """
    by_student: dict[int, dict[str, float]] = {}
    for row in bkt_history_repo.get_latest_by_skill(db):
        if row.student_id is None or row.skill is None or row.p_l is None:
            continue
        by_student.setdefault(row.student_id, {})[row.skill] = row.p_l
    return by_student


def _threshold(node: GraphNode) -> float:
    return node.mastery_threshold if node.mastery_threshold is not None else DEFAULT_THRESHOLD


def lock_diagnosis(db: Session, node_id: int) -> GraphLockDiagnosis:
    """I3 锁定诊断（功能 7.3）。

    判定口径（2026-10-23 与需求方确认）：
    - 技法节点：门禁是**递归前置链**（不只是直接前置），任何一个前置没掌握
      都说明学生还够不到该节点；受影响技法 = 节点自身 + 沿 prereq 边递归
      下游的技法（带环检测）。本人已掌握目标技法的学生不算受影响。
    - 唱段节点：门禁是 contains 边直接指向的所需技法；受影响技法 = 卡住学生
      的所需技法（唱段自身不是技法）。
    - 剧目节点：结构归属节点，没有掌握度与门禁，返回 locked=false。
    - 受影响学生：逐个学生看他本人在每条门禁技法上的最新 p_l，低于该技法
      自己的达标线才列入，并标明卡在哪几条技法。没练过某条技法的学生无从
      判断，不按 0 分算；全部门禁都无数据时不列任何人。
    """
    node = graph_repo.get_node(db, node_id)
    if node is None:
        raise BusinessError(404, "节点不存在")

    mastery = _skill_mastery(db)
    if node.node_type == "opera":
        return GraphLockDiagnosis(
            node=_node_out(node, mastery),
            locked=False,
            reason="剧目节点不参与锁定诊断",
            affected_skills=[],
            blocking_prerequisites=[],
            students=[],
        )

    nodes: dict[int, GraphNode] = {n.id: n for n in graph_repo.get_all_nodes(db)}
    edges = [
        e
        for e in graph_repo.get_all_edges(db)
        if e.source_id is not None and e.target_id is not None
    ]
    prereq_in: dict[int, list[int]] = {}
    prereq_out: dict[int, list[int]] = {}
    contains_out: dict[int, list[int]] = {}
    for e in edges:
        if e.edge_type == "prereq":
            prereq_in.setdefault(e.target_id, []).append(e.source_id)
            prereq_out.setdefault(e.source_id, []).append(e.target_id)
        elif e.edge_type == "contains":
            contains_out.setdefault(e.source_id, []).append(e.target_id)

    def ancestors(start: int) -> list[int]:
        """递归前置链：DFS 后序（最深的前置在前），带环检测。"""
        seen: set[int] = {start}
        out: list[int] = []

        def visit(nid: int) -> None:
            for pid in prereq_in.get(nid, []):
                if pid in seen or pid not in nodes:
                    continue
                seen.add(pid)
                visit(pid)
                out.append(pid)

        visit(start)
        return out

    def descendants(start: int) -> list[int]:
        """递归下游技法（prereq 出边方向），带环检测。"""
        seen: set[int] = {start}
        out: list[int] = []
        stack = [start]
        while stack:
            cur = stack.pop()
            for nxt in prereq_out.get(cur, []):
                if nxt in seen or nxt not in nodes:
                    continue
                seen.add(nxt)
                out.append(nxt)
                stack.append(nxt)
        return out

    gate_ids: list[int] = []
    if node.node_type == "skill":
        gate_ids = ancestors(node.id)
    elif node.node_type == "segment":
        gate_ids = contains_out.get(node.id, [])
    # 门禁只可能是技法节点，脏边不参与诊断
    gate_ids = [
        nid
        for nid in _unique(gate_ids)
        if nid in nodes and nodes[nid].node_type == "skill"
    ]

    by_student = _student_mastery(db)
    counts: dict[int, int] = {gid: 0 for gid in gate_ids}
    blocked_students: list[tuple[int, list[tuple[int, float, float]]]] = []
    for sid in sorted(by_student):
        skills = by_student[sid]
        if node.node_type == "skill":
            own = skills.get(node.label)
            # 本人已掌握目标技法 → 即使前置偏低也不构成「锁定」
            if own is not None and own >= _threshold(node):
                continue
        blockers: list[tuple[int, float, float]] = []
        for gid in gate_ids:
            gate = nodes[gid]
            p_l = skills.get(gate.label)
            if p_l is None:
                continue  # 没练过这条技法，不能判成未达标
            thr = _threshold(gate)
            if p_l < thr:
                blockers.append((gid, p_l, thr))
        if not blockers:
            continue
        for gid, _, _ in blockers:
            counts[gid] += 1
        blocked_students.append((sid, blockers))

    names = user_repo.get_student_names(db, [sid for sid, _ in blocked_students])
    students = [
        LockedStudentOut(
            student_id=sid,
            student_name=names.get(sid),
            blocked_by=[
                LockBlockerOut(id=gid, label=nodes[gid].label, mastery=p_l, threshold=thr)
                for gid, p_l, thr in blockers
            ],
        )
        for sid, blockers in blocked_students
    ]

    def dependency(nid: int) -> GraphDependencyOut:
        gate = nodes[nid]
        m = mastery.get(gate.label)
        thr = _threshold(gate)
        # 这里可能 met=true：班级均值达标但个别学生未达标，仍会卡住人
        return GraphDependencyOut(
            id=gate.id,
            label=gate.label,
            mastery=m,
            threshold=thr,
            met=None if m is None else m >= thr,
        )

    blocking_ids = [gid for gid in gate_ids if counts[gid] > 0]
    blocking = [dependency(gid) for gid in blocking_ids]

    if node.node_type == "skill":
        affected = [
            GraphNodeRef(id=node.id, label=node.label, mastery=mastery.get(node.label)),
            *[
                GraphNodeRef(id=nid, label=nodes[nid].label, mastery=mastery.get(nodes[nid].label))
                for nid in descendants(node.id)
                if nodes[nid].node_type == "skill"
            ],
        ]
    elif node.node_type == "segment":
        # 唱段自身不是技法；受影响技法 = 卡住学生的所需技法
        affected = [
            GraphNodeRef(id=nid, label=nodes[nid].label, mastery=mastery.get(nodes[nid].label))
            for nid in blocking_ids
        ]
    else:
        affected = []

    locked = bool(students)
    if not gate_ids:
        reason = (
            "该技法没有前置依赖，不会被锁定"
            if node.node_type == "skill"
            else "该唱段没有关联的所需技法，无法判定锁定"
        )
    elif locked:
        top_label = nodes[max(gate_ids, key=lambda gid: counts[gid])].label
        if node.node_type == "skill":
            reason = f"{len(students)} 名学生卡在未达标的前置技法「{top_label}」，暂无法解锁「{node.label}」"
        else:
            reason = f"{len(students)} 名学生的所需技法「{top_label}」未达标，暂无法练习「{node.label}」"
    else:
        has_data = any(
            skills.get(nodes[gid].label) is not None
            for skills in by_student.values()
            for gid in gate_ids
        )
        reason = (
            "相关技法在 bkt_history 中没有同名记录，暂无数据可判定锁定"
            if not has_data
            else "练过相关技法的学生均已达标，当前无人被锁定"
        )

    return GraphLockDiagnosis(
        node=_node_out(node, mastery),
        locked=locked,
        reason=reason,
        affected_skills=affected,
        blocking_prerequisites=blocking,
        students=students,
    )


def save_layout(db: Session, positions: dict[int, tuple[float, float]]) -> GraphLayoutOut:
    """I4：保存拖拽后的节点坐标（功能 7.5）。

    坐标是 ECharts graph 画布坐标，按原样入库；前端在坐标齐全时用它做
    `layout: 'none'` 渲染。未知 id 直接 400，避免静默丢数据。
    """
    known = {n.id for n in graph_repo.get_all_nodes(db)}
    unknown = sorted(set(positions) - known)
    if unknown:
        raise BusinessError(400, "节点不存在：" + "、".join(str(i) for i in unknown))
    saved = graph_repo.save_positions(db, positions)
    db.commit()
    return GraphLayoutOut(updated=saved, reset=False)


def reset_layout(db: Session) -> GraphLayoutOut:
    """I4：清空全部节点坐标（功能 7.6 的持久化部分）。

    接口清单只写「重置=前端恢复初始坐标」，但若不清服务端，刷新后又会回到
    已保存布局，重置就成了假动作。本轮口径见 DOC_ISSUES 第 53 条。
    """
    cleared = graph_repo.clear_positions(db)
    db.commit()
    return GraphLayoutOut(updated=cleared, reset=True)
