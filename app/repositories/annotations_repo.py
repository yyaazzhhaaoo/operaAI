from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Annotation


def get_annotations_list(db: Session) -> list[Annotation] | None:
    return list(db.scalars(select(Annotation)).all())