import math

from flask import request

from app.api import api_bp
from app.common.decorators import login_required, teacher_required
from app.common.errors import BusinessError
from app.db import get_db
from app.response import ok
from app.services import graph_service


@api_bp.route("/graph", methods=["GET"])
@login_required
@teacher_required
def graph():
    """I1 全量节点+边（功能 7.1/7.4）。按层筛在前端做。"""
    return ok(graph_service.overview(get_db()).model_dump())


@api_bp.route("/graph/node/<id>", methods=["GET"])
@login_required
@teacher_required
def graph_node(id):
    """I2 单节点依赖链（功能 7.2）。<id> 是 graph_nodes.id。"""
    try:
        node_id = int(id)
    except (TypeError, ValueError):
        # 非数字 <id> 与查无此节点对调用方是同一件事
        raise BusinessError(404, "节点不存在")
    return ok(graph_service.node_detail(get_db(), node_id).model_dump())


@api_bp.route("/graph/lock-diagnosis/<id>", methods=["GET"])
@login_required
@teacher_required
def graph_lock_diagnosis(id):
    """I3 锁定诊断（功能 7.3）。<id> 是 graph_nodes.id。"""
    try:
        node_id = int(id)
    except (TypeError, ValueError):
        # 非数字 <id> 与查无此节点对调用方是同一件事
        raise BusinessError(404, "节点不存在")
    return ok(graph_service.lock_diagnosis(get_db(), node_id).model_dump())


@api_bp.route("/graph/layout", methods=["POST"])
@login_required
@teacher_required
def graph_layout():
    """I4 保存拖拽布局（功能 7.5）；重置传 {"reset": true}（功能 7.6）。

    保存体：{"nodes": [{"id": 1, "x": 120.5, "y": -40.0}, ...]}。
    只保存前端传上来的节点，未传的保持原坐标。
    """
    payload = request.get_json(silent=True) or {}
    if payload.get("reset") is True:
        return ok(graph_service.reset_layout(get_db()).model_dump())

    raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise BusinessError(400, "nodes 必须是非空数组；重置请传 reset=true")

    positions: dict[int, tuple[float, float]] = {}
    for item in raw_nodes:
        if not isinstance(item, dict):
            raise BusinessError(400, "nodes 的每一项必须是对象")
        node_id = item.get("id")
        if isinstance(node_id, bool) or not isinstance(node_id, int):
            raise BusinessError(400, "节点 id 必须是整数")
        coords = []
        for name in ("x", "y"):
            value = item.get(name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise BusinessError(400, f"节点 {node_id} 的 {name} 必须是有限数字")
            coords.append(float(value))
        positions[node_id] = (coords[0], coords[1])

    return ok(graph_service.save_layout(get_db(), positions).model_dump())
