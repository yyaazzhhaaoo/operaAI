#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验 ORM 模型与真实库的结构是否一致。

用法（在项目根目录执行）：
    .venv/bin/python scripts/check_db.py

检查四项，任一不符即打印差异并以退出码 1 结束，可直接接进 CI：
  1. 表集合     —— 真库有而模型没有（漏建模型）／模型有而真库没有（脚本没跟上）
  2. 列名       —— 逐表比对
  3. 列类型与可空性 —— 类型先归一化再比，避免 DATETIME/TIMESTAMP 这类同义写法误报
  4. 外键与自定义索引 —— 索引侧排掉主键与 UNIQUE 约束自动生成的

背景：表结构的唯一真源是 schema.sql，模型只做映射。本脚本是这两者之间的
一致性闸门——改了 schema.sql 却忘了同步模型时，靠它抓出来。
"""

import sys
from pathlib import Path

# scripts/ 不是包，直接跑时 sys.path[0] 是 scripts/，import 不到 app/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text                      # noqa: E402
from sqlalchemy.orm import configure_mappers              # noqa: E402

import app.models                                          # noqa: E402,F401  必须导入，否则 metadata 是空的
from app.db import Base, engine, session_scope             # noqa: E402


def norm(t):
    """把两边的类型写法归一到可比较的形式。

    真库返回 PG 的类型名（TIMESTAMP / DOUBLE PRECISION…），
    模型返回 SQLAlchemy 的类型名（DATETIME / FLOAT…），同名不同写法的要先抹平。
    """
    t = str(t).lower()
    if t in ("timestamp", "datetime"):
        return "timestamp"
    if t in ("double precision", "float", "real"):
        return "float"
    if t in ("integer", "int4"):
        return "int"
    if t == "character varying":
        return "varchar"
    if t == "boolean":
        return "bool"
    return t


def main():
    configure_mappers()
    insp = inspect(engine)

    real = set(insp.get_table_names())
    model = set(Base.metadata.tables)
    bad = []
    if real != model:
        bad.append(f"表集合不一致：真库独有={real - model or '无'} 模型独有={model - real or '无'}")

    ncol = nfk = nidx = 0
    for t in sorted(model):
        rcols = {c["name"]: c for c in insp.get_columns(t)}
        mcols = Base.metadata.tables[t].columns

        if set(rcols) != set(mcols.keys()):
            bad.append(
                f"{t} 列名差异：真库独有={set(rcols) - set(mcols.keys()) or '无'} "
                f"模型独有={set(mcols.keys()) - set(rcols) or '无'}"
            )
        else:
            for name in mcols.keys():
                ncol += 1
                if norm(mcols[name].type) != norm(rcols[name]["type"]):
                    bad.append(f"{t}.{name} 类型：真库={rcols[name]['type']} 模型={mcols[name].type}")
                if bool(mcols[name].nullable) != bool(rcols[name]["nullable"]):
                    bad.append(f"{t}.{name} 可空：真库={rcols[name]['nullable']} 模型={mcols[name].nullable}")

        # 外键：两边各取「本表列 -> 目标表.目标列」的三元组
        rfk = {
            frozenset((f["constrained_columns"][0], f["referred_table"], f["referred_columns"][0]))
            for f in insp.get_foreign_keys(t)
        }
        mfk = {
            frozenset((fk.parent.name, fk.column.table.name, fk.column.name))
            for fk in Base.metadata.tables[t].foreign_keys
        }
        nfk += len(mfk)
        if rfk != mfk:
            bad.append(f"{t} 外键差异：真库独有={rfk - mfk or '无'} 模型独有={mfk - rfk or '无'}")

        # 索引：真库侧排掉主键与 UNIQUE 约束自动生成的，只留显式 CREATE INDEX 的
        uniq = {u["name"] for u in insp.get_unique_constraints(t)}
        ridx = {
            i["name"] for i in insp.get_indexes(t)
            if not i["name"].endswith("_pkey") and i["name"] not in uniq
        }
        midx = {i.name for i in Base.metadata.tables[t].indexes}
        nidx += len(midx)
        if ridx != midx:
            bad.append(f"{t} 索引差异：真库独有={ridx - midx or '无'} 模型独有={midx - ridx or '无'}")

    print(f"比对范围：{len(model)} 张表 / {ncol} 列 / {nfk} 个外键 / {nidx} 个自定义索引")
    if bad:
        print("结果：有差异 ✗")
        for b in bad:
            print(f"  - {b}")
        return 1

    print("结果：全部一致 ✓")
    # 顺带确认会话与连接池是干净的
    with session_scope() as s:
        who = s.execute(text("SELECT current_user||'@'||current_database()")).scalar()
    print(f"连接正常：{who}，连接池残留 {engine.pool.checkedout()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
