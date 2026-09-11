from sqlalchemy import Float,ForeignKey,Integer,String,text
from sqlalchemy.orm import Mapped,mapped_column,relationship
from app.db import Base


class GraphNode(Base):
    """知识图谱节点。技法名存 label，唱句用 ref_id 指向 segments.id。"""

    __tablename__ = "graph_nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    node_type: Mapped[str] = mapped_column(String(10))         # skill / segment / opera
    # 唱句节点指向 segments.id，但表上并未建外键约束（仅注释说明），故此处不加 ForeignKey
    ref_id: Mapped[int | None] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(50))
    pos_x: Mapped[float | None] = mapped_column(Float)         # 拖拽布局持久化
    pos_y: Mapped[float | None] = mapped_column(Float)
    mastery_threshold: Mapped[float | None] = mapped_column(Float, server_default=text("0.60"))


class GraphEdge(Base):
    """知识图谱边。edge_type：prereq(前置) / contains(包含)。"""

    __tablename__ = "graph_edges"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("graph_nodes.id"))
    target_id: Mapped[int | None] = mapped_column(ForeignKey("graph_nodes.id"))
    edge_type: Mapped[str] = mapped_column(String(10))

    # 两个外键都指向 graph_nodes，必须显式指定 foreign_keys
    source_node: Mapped["GraphNode | None"] = relationship(foreign_keys=[source_id])
    target_node: Mapped["GraphNode | None"] = relationship(foreign_keys=[target_id])
