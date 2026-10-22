# -*- coding: utf-8 -*-
"""摸底题库种子：从真实分段里选 6 题写入 cat_questions。

用法（项目根目录）：
    .venv/bin/python scripts/seed_cat_questions.py

幂等：按 seq 先删后插。题目定位不写死 id，按标题找带段音频的分段；
有多条时取 demo_id 最大的那条（最近一次上传）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select                      # noqa: E402

from app.db import session_scope                           # noqa: E402
from app.models import CatQuestion, Segment                # noqa: E402

# (seq, 分段标题, focus_dims)
QUESTIONS = [
    (1, "辕门外三声炮如同雷震", ["音准", "气息", "拖腔"]),
    (2, "天波府里走出来我保国臣", ["音准", "节奏", "咬字"]),
    (3, "头戴金冠压双鬓", ["节奏", "咬字"]),
    (4, "帅字旗飘入云", ["气息", "拖腔"]),
    (5, "斗大的穆字震乾坤", ["音准", "咬字"]),
    (6, "谁料想我五十三岁又管三军", ["节奏", "气息", "拖腔"]),
]


def _find_segment(db, title: str) -> Segment | None:
    return db.scalar(
        select(Segment)
        .where(Segment.title == title)
        .where(Segment.audio_id.is_not(None))
        .where(Segment.demo_id.is_not(None))
        .order_by(Segment.demo_id.desc(), Segment.id.desc())
        .limit(1)
    )


def main() -> int:
    with session_scope() as db:
        rows = []
        missing = []
        for seq, title, dims in QUESTIONS:
            seg = _find_segment(db, title)
            if seg is None:
                missing.append(title)
                continue
            rows.append((seq, seg, dims))

        if missing:
            print("找不到带段音频的分段：" + "、".join(missing))
            return 1

        db.execute(delete(CatQuestion).where(
            CatQuestion.seq.in_([q[0] for q in QUESTIONS])
        ))
        for seq, seg, dims in rows:
            db.add(CatQuestion(
                seq=seq,
                segment_id=seg.id,
                focus_dims=dims,
                is_active=True,
            ))
            print(f"seq={seq} segment_id={seg.id} {seg.title}")

    print(f"已写入 {len(rows)} 题")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
