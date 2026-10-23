"""知识图谱（graph_nodes / graph_edges）的数据访问。

图谱数据目前只有只读消费方（看板预警），没有任何写入路径——技法关系是
《8-数据准备清单》4.5 节那份模板一次性交付的，不是运行时维护的。
"""
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, aliased

from app.models import GraphEdge, GraphNode


def get_all_nodes(db: Session) -> list[GraphNode]:
    """全量节点（I1）。当前只有 24 行，一次取完比按层分查划算。"""
    return list(db.scalars(select(GraphNode).order_by(GraphNode.id)).all())


def get_all_edges(db: Session) -> list[GraphEdge]:
    """全量边（I1）。27 行，与节点一起在 service 里建内存邻接表。"""
    return list(db.scalars(select(GraphEdge).order_by(GraphEdge.id)).all())


def get_node(db: Session, node_id: int) -> GraphNode | None:
    """单个节点（I2）。查无此节点由 service 转成 404。"""
    return db.get(GraphNode, node_id)


def save_positions(db: Session, positions: dict[int, tuple[float, float]]) -> int:
    """I4 批量写节点坐标，返回实际命中的行数。未知 id 由 service 先拦掉。"""
    rows = db.scalars(select(GraphNode).where(GraphNode.id.in_(positions))).all()
    for node in rows:
        node.pos_x, node.pos_y = positions[node.id]
    return len(rows)


def clear_positions(db: Session) -> int:
    """I4 重置：清空全部节点坐标，让下次加载回到力导向初始布局。"""
    result = db.execute(update(GraphNode).values(pos_x=None, pos_y=None))
    return result.rowcount or 0


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
