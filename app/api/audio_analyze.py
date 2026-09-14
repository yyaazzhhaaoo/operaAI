from flask import request

from app.api import api_bp
from app.common.decorators import login_required
from app.response import ok


def _payload() -> dict:
    """取 JSON 请求体。

    客户端没带 Content-Type: application/json 时 get_json() 会抛 415；
    silent=True 把它压成 None，这里再兜成 {}，让 pydantic 报「字段必填」
    而不是让 Flask 抛一个前端看不懂的 415。
    """
    return request.get_json(silent=True) or {}

@api_bp.route("/audio/upload",methods=["POST"])
@login_required
def audio_upload():
    return ok()

@api_bp.route("/analyze/submit",methods=["POST"])
@login_required
def analyze_submit():
    return ok();

@api_bp.route("/analyze/status/<task_id>",methods=["GET"])
@login_required
def analyze_status(task_id):
    return ok(task_id)

@api_bp.route("/analyze/result/<task_id>",methods=["GET"])
@login_required
def analyze_result(task_id):
    return ok(task_id)

@api_bp.route("/audio/<file_id>",methods=["GET"])
@login_required
def audio(file_id):
    return ok(file_id)

