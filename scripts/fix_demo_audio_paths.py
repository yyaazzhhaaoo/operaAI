#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把示范曲目关联的 audio_files.file_path 规范成 demos/<文件名>。

背景（DOC_ISSUES 第 40 条）：示范音频该放 uploads/demos/，学生录音平铺在
uploads/。库里那批示范音频的 file_path 是按「相对项目根」手工插的
（uploads/demos/x.wav），storage.resolve() 解不出来，B5 播放、Demucs 解析、
分析三条链路全断。storage 的守卫修好后，还要把值改成「相对 uploads/」的形态。

用法（在项目根目录执行）：
    .venv/bin/python scripts/fix_demo_audio_paths.py --dry-run
    .venv/bin/python scripts/fix_demo_audio_paths.py

规则是「teacher_demos.audio_id 关联的每一行都应在 demos/ 下」，所以原本是
裸名的（demo 15 那条）也会被归到 demos/——即便它的文件并不存在。
幂等：已经是目标形态的行跳过，可重复执行。
"""

import argparse
import sys
from pathlib import Path

# scripts/ 不是包，直接跑时 sys.path[0] 是 scripts/，import 不到 app/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select                                    # noqa: E402

from app.common import storage                                   # noqa: E402
from app.common.errors import BusinessError                      # noqa: E402
from app.db import session_scope                                 # noqa: E402
from app.models.audio import AudioFile                           # noqa: E402
from app.models.demo import TeacherDemo                          # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写库")
    args = ap.parse_args()

    changed = 0
    with session_scope() as s:
        rows = s.execute(
            select(AudioFile, TeacherDemo.id)
            .join(TeacherDemo, TeacherDemo.audio_id == AudioFile.id)
            .order_by(AudioFile.id)
        ).all()

        if not rows:
            print("没有 teacher_demos 关联的音频，什么都不用做。")
            return 0

        for audio, demo_id in rows:
            target = f"demos/{Path(audio.file_path).name}"
            if audio.file_path == target:
                print(f"跳过   audio {audio.id:3} 已是 {target}")
                continue

            # 改完解不解得出来、文件在不在，当场说清楚——
            # 不然下一个人会问「改完了怎么还是不出声」
            try:
                path = storage.resolve(target)
                detail = f"文件在（{path}）" if path.is_file() else f"文件不在（{path}）"
            except BusinessError as e:
                detail = f"解析失败：{e.message}"

            print(f"改     audio {audio.id:3}  demo {demo_id:3}  "
                  f"{audio.file_path}  ->  {target}   {detail}")
            if not args.dry_run:
                audio.file_path = target
            changed += 1

    verb = "将改" if args.dry_run else "已改"
    print(f"\n{verb} {changed} 行。")
    if args.dry_run:
        print("（--dry-run，没有写库）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
