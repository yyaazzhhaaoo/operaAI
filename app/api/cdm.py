from app.api import api_bp
from app.common.decorators import login_required, teacher_required
from app.common.errors import BusinessError
from app.db import get_db
from app.response import ok
from app.services import cdm_report_service


@api_bp.route("/cdm/submissions", methods=["GET"])
@login_required
@teacher_required
def cdm_submissions():
    """CDM 归因诊断页的学生提交列表（接口清单无此条，口径见 DOC_ISSUES 第 54 条）。"""
    return ok(cdm_report_service.list_submissions(get_db()).model_dump(mode="json"))


@api_bp.route("/cdm/submissions/<id>/features", methods=["GET"])
@login_required
@teacher_required
def cdm_submission_features(id):
    """单条提交的 CDM 输入特征矩阵（接口清单无此条，口径见 DOC_ISSUES 第 57 条）。"""
    try:
        submission_id = int(id)
    except (TypeError, ValueError):
        raise BusinessError(404, "提交不存在")
    return ok(
        cdm_report_service.submission_features(get_db(), submission_id).model_dump(mode="json")
    )


@api_bp.route("/cdm/submissions/<id>/pitch-pattern", methods=["GET"])
@login_required
@teacher_required
def cdm_submission_pitch_pattern(id):
    """单条提交的音高偏差模式（接口清单无此条，口径见 DOC_ISSUES 第 58 条）。"""
    try:
        submission_id = int(id)
    except (TypeError, ValueError):
        raise BusinessError(404, "提交不存在")
    return ok(
        cdm_report_service.submission_pitch_pattern(get_db(), submission_id).model_dump(mode="json")
    )


@api_bp.route("/cdm/submissions/<id>/defects", methods=["GET"])
@login_required
@teacher_required
def cdm_submission_defects(id):
    """单条提交的缺陷标签明细（接口清单无此条，口径见 DOC_ISSUES 第 56 条）。"""
    try:
        submission_id = int(id)
    except (TypeError, ValueError):
        raise BusinessError(404, "提交不存在")
    return ok(
        cdm_report_service.submission_defects(get_db(), submission_id).model_dump(mode="json")
    )


@api_bp.route("/cdm/submissions/<id>", methods=["GET"])
@login_required
@teacher_required
def cdm_submission(id):
    """单条提交的四指标摘要（接口清单无此条，口径见 DOC_ISSUES 第 55 条）。"""
    try:
        submission_id = int(id)
    except (TypeError, ValueError):
        # 非数字 <id> 与查无此提交对调用方是同一件事（同 /graph/node/<id>）
        raise BusinessError(404, "提交不存在")
    return ok(
        cdm_report_service.submission_summary(get_db(), submission_id).model_dump(mode="json")
    )
