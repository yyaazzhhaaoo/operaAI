#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回填 practice_records.cdm_json（历史练习记录）。

用法（在项目根目录执行，**先执行 scripts/add_practice_cdm_json.sql**）：
    .venv/bin/python scripts/backfill_practice_cdm.py --dry-run   # 只看结果
    .venv/bin/python scripts/backfill_practice_cdm.py             # 真正写库

只处理 cdm_json IS NULL 且 dimensions_json / words_json 至少有一项非 NULL 的行：
两者都为 NULL 的记录没有数据源，保持 NULL（与「查了是空」的 defects=[] 区分）。
规则引擎与线上分析管线共用 app/services/cdm_service.py，这里不另写一套判定。
脚本幂等：已回填的行不会被再次选中。
"""

import argparse
import sys
from pathlib import Path

# scripts/ 不是包，直接跑时 sys.path[0] 是 scripts/，import 不到 app/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import or_, select                          # noqa: E402

from app.db import session_scope                             # noqa: E402
from app.models import PracticeRecord                        # noqa: E402
from app.services import cdm_service                         # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="回填 practice_records.cdm_json")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写库")
    args = parser.parse_args()

    with session_scope() as db:
        rows = db.scalars(
            select(PracticeRecord)
            .where(PracticeRecord.cdm_json.is_(None))
            .where(or_(
                PracticeRecord.dimensions_json.is_not(None),
                PracticeRecord.words_json.is_not(None),
            ))
            .order_by(PracticeRecord.id)
        ).all()

        filled = skipped = 0
        for record in rows:
            cdm = cdm_service.build(record.dimensions_json, record.words_json)
            if cdm is None:
                # 有列但内容不是可用结构（脏数据），不猜、不写
                skipped += 1
                continue
            labels = "、".join(d["label"] for d in cdm["defects"]) or "无缺陷"
            print(
                f"id={record.id} student_id={record.student_id} "
                f"-> {labels}（overallConfidence={cdm['overallConfidence']}）"
            )
            if not args.dry_run:
                record.cdm_json = cdm
            filled += 1

        print(f"\n候选 {len(rows)} 条：{'将回填' if args.dry_run else '已回填'} {filled} 条，"
              f"跳过 {skipped} 条（无可用结构）")
        if args.dry_run:
            print("dry-run：未写库。去掉 --dry-run 再执行一次。")


if __name__ == "__main__":
    main()
