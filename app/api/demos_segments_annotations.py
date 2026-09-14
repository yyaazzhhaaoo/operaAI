from flask import request

from app.api import api_bp
from app.common.decorators import login_required, teacher_required
from app.response import ok


@api_bp.route("/demos",methods=["GET"])
@login_required
def demos():
    return ok();

@api_bp.route("/demos/<id>/segments",methods=["GET"])
@login_required
def demos_segments(id):
    return ok(id)

@api_bp.route("/segments/<id>",methods=["GET"])
@login_required
def segments(id):
    return ok(id);

@api_bp.route("/segments/<id>/annotations",methods=["GET"])
@login_required
@teacher_required
def segments_annotations(id):
    return ok(id);

@api_bp.route("/annotations",methods=["POST"])
@login_required
@teacher_required
def annotations():
    return ok()

@api_bp.route("/annotations/<id>",methods=["DELETE"])
@login_required
@teacher_required
def del_annotations(id):
    return ok(id)

@api_bp.route("/annotations/rules",methods=["GET"])
@login_required
@teacher_required
def annotations_rules():
    tag = request.args.get("tag")
    word = request.args.get("word")
    return ok({"tag":tag,"word":word})