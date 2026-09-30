from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Annotation, TeacherDemo
from app.models.demo import Segment


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


def get_by_id(db: Session, annotation_id: int) -> Annotation | None:
    """按主键取一条标注（C6 的存在性判定）。取不到返回 None。

    返回 None 表示「没有」——调用方据此抛 404，不拿它当别的信号。

    用 db.get() 而不是 select().where()：直接走主键查询 / identity map，
    是本文件已有写法里最短的一个。
    """
    return db.get(Annotation, annotation_id)


def remove(db: Session, ann: Annotation) -> None:
    """删除一条标注。只标脏，提交交给 service 层（同 add 只 flush 的约定）。

    收 ORM 对象而不是 id：调用方（service）已经为了判 404 把行查出来了，
    再收一个 id 去发 DELETE 语句等于把同一次查找做两遍。

    **不用 `DELETE ... WHERE id = ?` 拿 rowcount**：rowcount 只有 0/1，
    拿到 0 时还要再 SELECT 一次才能区分「不存在」与「并发被删」，省下的
    那次查询又还回去了；而且本层一律以 ORM 对象为出入口，写原生 delete()
    会让这一层出现两种风格。C6 的量级是「一次一行」，不值得为它优化。
    """
    db.delete(ann)


def list_rules(db: Session, tag: str | None) -> list[tuple[Annotation, Segment | None, TeacherDemo | None]]:
    """全库标注 + 各自所属的唱段与曲目，供 C7 `GET /api/annotations/rules`。

    **一条 SQL 查完，不做 N+1**（同 get_demo_list 的取舍）。曲目数是个位数、
    标注数是十位数，joinedload 不必上。

    **outerjoin 而非 join**：annotations.segment_id 与 segments.demo_id 在 DDL
    上都可空，内连接会把这两类行整条丢掉——集中展示少几行且毫无提示，与
    spec 3.4「char 取不到时保留行」的口径直接打架。

    tag 条件**下推到 SQL**（`tag is None` 时不加）：能少捞一批行就少捞一批。
    `word` 筛选不在这里——它依赖归一后的字，SQL 层拿不到，在 service 层做。

    排序 demo_id → segment_id → word_index → id 全升序：先按曲目分组，再按
    唱段、再按字序，末位 id 保证稳定（同一个字可挂多个 tag，UNIQUE 是三列）。
    demo_id 为 NULL 的行在 PG 的 `ORDER BY ... ASC` 下默认排最后（NULLS LAST），
    这是 PG 的既定行为，不必显式 nulls_last()。

    返回三元组而不是往模型上挂临时属性：同 get_demo_list 返回
    (TeacherDemo, 分段数) 的理由——「哪些来自库、哪些是算出来的」要看得出来。
    """
    stmt = (
        select(Annotation, Segment, TeacherDemo)
        .outerjoin(Segment, Annotation.segment_id == Segment.id)
        .outerjoin(TeacherDemo, Segment.demo_id == TeacherDemo.id)
        .order_by(
            Segment.demo_id,
            Annotation.segment_id,
            Annotation.word_index,
            Annotation.id,
        )
    )
    if tag is not None:
        stmt = stmt.where(Annotation.tag == tag)
    return list(db.execute(stmt).all())