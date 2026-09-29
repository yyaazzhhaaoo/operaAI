from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Annotation


def get_annotations_list(db: Session) -> list[Annotation] | None:
    return list(db.scalars(select(Annotation)).all())


def list_by_segment(db: Session, segment_id: int) -> list[Annotation]:
    """按唱段取标注（C4），word_index 升序、同字按 id 升序。

    不与 get_annotations_list 合并：那个是全表取行给看板算总数
    （dashboard_service 在用），本函数按 segment_id 过滤给标注页。
    查询目的不同，合并只会多一个「要不要过滤」的参数分支。

    order_by 里带上 id 是为了**稳定**：同一个字可以挂多个 tag（UNIQUE 约束是
    segment_id + word_index + tag 三列），只按 word_index 排的话这两条谁先谁后
    由 PG 自由决定，同一次查询跑两次可能顺序不同。
    """
    return list(db.scalars(
        select(Annotation)
        .where(Annotation.segment_id == segment_id)
        .order_by(Annotation.word_index, Annotation.id)
    ).all())