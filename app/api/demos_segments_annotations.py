import requests
from flask import request

from app.api import api_bp
from app.response import ok


@api_bp.route("/demos",methods=["GET"])
def demos():
    return ok();

@api_bp.route("/demos/<id>/segments",methods=["GET"])
def demos_segments(id):
    return ok(id)

@api_bp.route("/segments/<id>",methods=["GET"])
def segments(id):
    return ok(id);

@api_bp.route("/segments/<id>/annotations",methods=["GET"])
def segments_annotations(id):
    return ok(id);

@api_bp.route("/annotations",methods=["POST"])
def annotations():
    return ok()

@api_bp.route("/annotations/<id>",methods=["DELETE"])
def del_annotations(id):
    return ok(id)

@api_bp.route("/annotations/rules",methods=["GET"])
def annotations_rules():
    tag = request.args.get("tag")
    word = request.args.get("word")
    return ok({"tag":tag,"word":word})