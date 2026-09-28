"""知识图谱（graph_nodes / graph_edges）的数据访问。

图谱数据目前只有只读消费方（看板预警），没有任何写入路径——技法关系是
《8-数据准备清单》4.5 节那份模板一次性交付的，不是运行时维护的。
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.models import GraphEdge, GraphNode


def get_segment_nodes(db: Session) -> list[GraphNode]:
    """全部唱段节点。推荐（功能 5.7）拿它当候选集。"""
    return list(db.scalars(
        select(GraphNode).where(GraphNode.node_type == "segment").order_by(GraphNode.id)
    ).all())


def get_segment_skill_map(db: Session) -> dict[int, list[str]]:
    """唱段节点 id -> 它 contains 的全部技法名。

    只认 segment --contains--> skill 这一个方向：opera --> segment 与 prereq
    都不是「练这个唱段要用到哪些技法」，混进来会得出离谱的需求技法集合。
    """
    src = aliased(GraphNode, name="seg")
    tgt = aliased(GraphNode, name="sk")
    stmt = (
        select(src.id, tgt.label)
        .select_from(GraphEdge)
        .join(src, GraphEdge.source_id == src.id)
        .join(tgt, GraphEdge.target_id == tgt.id)
        .where(
            GraphEdge.edge_type == "contains",
            src.node_type == "segment",
            tgt.node_type == "skill",
        )
        .order_by(src.id, tgt.label)
    )
    out: dict[int, list[str]] = {}
    for node_id, label in db.execute(stmt).all():
        out.setdefault(node_id, []).append(label)
    return out


def get_prereq_edges(db: Session) -> list[tuple[str, float, str]]:
    """全部前置关系，每项是 (前置技法名, 该技法的达标线, 下游技法名)。

    只取 edge_type='prereq'：contains 表达的是「剧目包含唱段、唱段包含技法」的
    结构归属，与学习先后无关，混进来会得出「某唱段是某技法的前置」这种结果。

    技法名存在 graph_nodes.label——skill 节点的 ref_id 是空的（ref_id 只给
    唱段节点指向 segments.id）。达标线用 coalesce 兜底：列虽然 default 0.60，
    但没建 NOT NULL，显式写 NULL 是可能的。
    """
    src = aliased(GraphNode, name="src")
    tgt = aliased(GraphNode, name="tgt")
    stmt = (
        select(src.label, func.coalesce(src.mastery_threshold, 0.60), tgt.label)
        .select_from(GraphEdge)
        .join(src, GraphEdge.source_id == src.id)
        .join(tgt, GraphEdge.target_id == tgt.id)
        .where(GraphEdge.edge_type == "prereq")
    )
    return [tuple(row) for row in db.execute(stmt).all()]
