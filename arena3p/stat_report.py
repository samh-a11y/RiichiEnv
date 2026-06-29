#!/usr/bin/env python3
"""change-001 指标报告：复现 Mortal test-play 写入 TB 的那套指标。

**不自创公式**：直接用 libriichi3p 原生 `stat.Stat`（与 Mortal test-play 同一份 Rust 统计器）。
读 run_eval.py 落的 god-view mjai 日志目录，对每个座位名 `Stat.from_dir(dir, name)`，
读其 getter（avg_rank / agari_rate / houjuu_rate / riichi_rate / ... 全套）。

按模型聚合：单座模型直接取 getter；多座同模型（如 community 占两座）= 两座 getter 的均值
（率/顺位类因每座 game/round 相同而**精确**；按事件平均的点数/巡目类为近似，已标注）。

须在 conda mortal（py3.12，有 libriichi3p.so）下跑：
  ~/miniconda3/envs/mortal/bin/python arena3p/stat_report.py --log-dir <dir> --players joint,community,community
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, "/home/administrator/Mortal3/mortal")  # libriichi3p.so
import libriichi3p  # noqa: E402

Stat = libriichi3p.stat.Stat
PTS_3P = [90, 0, -90]  # Mortal3 train.py:336（3 麻 3 元，display 用）

# (label, 取值函数)；率为「精确可均值」，按事件平均为「近似可均值」
RATE_LIKE = [  # 每局/每round/每game 归一 → 均值精确
    ("avg_rank", lambda s: s.avg_rank),
    ("avg_pt", lambda s: s.avg_pt(PTS_3P)),
    ("1st%", lambda s: s.rank_1_rate),
    ("2nd%", lambda s: s.rank_2_rate),
    ("3rd%", lambda s: s.rank_3_rate),
    ("和率", lambda s: s.agari_rate),
    ("放铳率", lambda s: s.houjuu_rate),
    ("立直率", lambda s: s.riichi_rate),
    ("副露率", lambda s: s.fuuro_rate),
    ("每round点", lambda s: s.avg_point_per_round),
    ("tobi率", lambda s: s.tobi / s.game if s.game else 0.0),
]
EVENT_AVG = [  # 按事件次数归一 → 多座均值为近似
    ("平均和点", lambda s: s.avg_point_per_agari),
    ("立直和点", lambda s: s.avg_point_per_riichi_agari),
    ("副露和点", lambda s: s.avg_point_per_fuuro_agari),
    ("默听和点", lambda s: s.avg_point_per_dama_agari),
    ("平均放铳点", lambda s: s.avg_point_per_houjuu),
    ("和了巡", lambda s: s.avg_agari_jun),
    ("放铳巡", lambda s: s.avg_houjuu_jun),
    ("立直巡", lambda s: s.avg_riichi_jun),
    ("立直后和率", lambda s: s.agari_rate_after_riichi),
    ("立直后铳率", lambda s: s.houjuu_rate_after_riichi),
    ("追立直率", lambda s: s.chasing_riichi_rate),
    ("被追率", lambda s: s.riichi_chased_rate),
    ("立直收益", lambda s: s.avg_riichi_point),
    ("副露后和率", lambda s: s.agari_rate_after_fuuro),
    ("副露后铳率", lambda s: s.houjuu_rate_after_fuuro),
    ("平均副露数", lambda s: s.avg_fuuro_num),
    ("副露点", lambda s: s.avg_fuuro_point),
]


def safe(fn, s):
    try:
        v = fn(s)
        return float(v)
    except Exception:
        return float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log-dir", required=True)
    ap.add_argument("--players", required=True)
    args = ap.parse_args()

    players = [p.strip() for p in args.players.split(",")]
    names = [f"{i}_{n}" for i, n in enumerate(players)]
    d = str(pathlib.Path(args.log_dir))

    # 每座一个 Stat
    seat_stat = {}
    for i, nm in enumerate(names):
        seat_stat[i] = Stat.from_dir(d, nm)
    g0 = seat_stat[0]
    print(f"日志目录: {d}")
    print(f"对局数 game={g0.game}  总局 round(座0)={g0.round}  座位: " +
          ", ".join(f"{i}={players[i]}" for i in range(3)))

    # 模型 → 座位列表
    model_seats = {}
    for i, p in enumerate(players):
        model_seats.setdefault(p, []).append(i)

    def val(seats, fn):
        vs = [safe(fn, seat_stat[i]) for i in seats]
        return sum(vs) / len(vs)

    # ---- headline 表（每座 + 每模型）----
    rows = []
    for i in range(3):
        rows.append((f"座{i}:{players[i]}", [i]))
    for p, seats in model_seats.items():
        if len(seats) > 1:
            rows.append((f"{p}(均{len(seats)}座)", seats))

    cols = RATE_LIKE
    print("\n===== Mortal test-play 同款指标（率/顺位；多座=均值，精确）=====")
    head = f"{'':16}" + "".join(f"{lbl:>9}" for lbl, _ in cols)
    print(head)
    for label, seats in rows:
        cells = []
        for lbl, fn in cols:
            v = val(seats, fn)
            if lbl in ("avg_rank", "avg_pt", "每round点"):
                cells.append(f"{v:9.3f}" if "rank" in lbl else f"{v:9.1f}")
            else:
                cells.append(f"{v*100:8.2f}%")
        print(f"{label:16}" + "".join(cells))

    print("\n===== 进阶指标（按事件平均；多座为近似）=====")
    head2 = f"{'':16}" + "".join(f"{lbl:>9}" for lbl, _ in EVENT_AVG)
    print(head2)
    for label, seats in rows:
        cells = []
        for lbl, fn in EVENT_AVG:
            v = val(seats, fn)
            if "率" in lbl:
                cells.append(f"{v*100:8.2f}%")
            elif "巡" in lbl or "数" in lbl:
                cells.append(f"{v:9.2f}")
            else:
                cells.append(f"{v:9.0f}")
        print(f"{label:16}" + "".join(cells))


if __name__ == "__main__":
    main()
