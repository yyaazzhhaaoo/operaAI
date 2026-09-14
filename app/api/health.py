from app.api import api_bp
from app.response import ok


@api_bp.route("/health",methods=["GET"])
def health():
    return ok()