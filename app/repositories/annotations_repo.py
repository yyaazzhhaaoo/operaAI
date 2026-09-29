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


def get_one(db: Session, segment_id: int, word_index: int, tag: str) -> Annotation | None:
    """按唯一键取一条标注（C5 的重复判定）。

    三列全用上，**不含 teacher_id**：这张表的设计前提是「一个唱段一套全局
    唯一的规则集」（C4 spec 3.4），换个教师再标同字同 tag 一样是重复。

    返回 None 表示「没有」——调用方据此放行写入，不拿它当 404 信号。
    """
    return db.scalar(
        select(Annotation).where(
            Annotation.segment_id == segment_id,
            Annotation.word_index == word_index,
            Annotation.tag == tag,
        )
    )


def add(db: Session, *, segment_id: int, word_index: int, tag: str,
        tolerance: int | None, teacher_id: int | None) -> Annotation:
    """新增一条标注。只 flush 拿自增 id，提交交给 service 层。

    关键字参数：五个字段里有两个是 int、一个可空 int，位置调用时
    `add(db, 119, 0, "拖腔", 30, 2)` 里 `0` 和 `30` 极易写反。

    flush 之后 id 与 created_at 都已被 RETURNING 填好，调用方可以直接组装
    响应，不必 commit 之后再回查一次。
    """
    ann = Annotation(
        segment_id=segment_id,
        word_index=word_index,
        tag=tag,
        tolerance=tolerance,
        teacher_id=teacher_id,
    )
    db.add(ann)
    db.flush()          # 只为拿到自增 id 与 created_at，提交由 service 层负责
    return ann