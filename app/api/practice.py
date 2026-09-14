from flask import request

from app.api import api_bp
from app.common.decorators import login_required, student_required
from app.response import ok


@api_bp.route("/practice/submit",methods=["POST"])
@login_required
@student_required
def practice_submit():
    segment_id = request.form.get("segment_id")
    audio_id = request.form.get("audio_id")
    return ok({"segment_id":segment_id,"audio_id":audio_id})

@api_bp.route("/practice/logs",methods=["GET"])
@login_required
def practice_logs():
    student_id = request.args.get("student_id")
    return ok({"student_id":student_id})

@api_bp.route("/practice/last/<segment_id>",methods=["GET"])
@login_required
@student_required
def practice_last(segment_id):
    return ok(segment_id)