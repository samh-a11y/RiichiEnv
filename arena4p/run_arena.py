#!/usr/bin/env python3
"""四麻四方对战驱动（qgrp change-002：QGRP 打牌器 vs Mortal）。

在 riichienv/（.venv 激活）下跑：
  python arena4p/run_arena.py --players qgrp,mortal,mortal,mortal --hanchan 4 --seed 100
  python arena4p/run_arena.py --players qgrp,mortal,mortal,mortal --hanchan 100 --seed 0 --rotate

--rotate = 复式（CRN）：同 seed 跑 4 个循环轮转座次（同牌山、座位效应对消），
汇总按模型聚合 avg_rank / avg_pt（四麻公平线 avg_rank 2.50）。
裁判 = RiichiEnv 4p-red-half 天凤规则；每座一个 MJAI 子进程引擎（见 engines/）。
注意：RiichiEnv.scores 终局不归还桌上立直棒（同 3p 已知口径），素点仅供参考，
rank/pt 不受影响。
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import sys

RIICHIENV_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RIICHIENV_ROOT))

from riichienv import RiichiEnv, GameRule  # noqa: E402
from arena4p.engines.subprocess_engine import SubprocessMjaiEngine  # noqa: E402

PTS = {1: 90.0, 2: 45.0, 3: 0.0, 4: -135.0}  # 天凤凤南口径（与 qgrp bot 默认一致）


def play_one_hanchan(players: list[str], seed: int | None = None):
    env = RiichiEnv(game_mode="4p-red-half", rule=GameRule.default_tenhou(),
                    seed=seed)
    engines = {seat: SubprocessMjaiEngine(name, seat)
               for seat, name in enumerate(players)}
    try:
        obs = env.reset(scores=[25000] * 4)
        steps = 0
        while not env.done():
            acts = {}
            for pid, o in obs.items():
                a = engines[pid].act(o)
                if a is None:
                    legals = o.legal_actions()
                    a = legals[0]
                acts[pid] = a
            obs = env.step(acts)
            steps += 1
            if steps > 100000:
                raise RuntimeError("step 上限保护触发（疑似死循环）")
        return env.scores(), env.ranks()
    finally:
        for e in engines.values():
            e.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", required=True,
                    help="逗号分隔四个模型名，如 qgrp,mortal,mortal,mortal")
    ap.add_argument("--hanchan", type=int, default=1,
                    help="局数（--rotate 时 = seed 数，每 seed 4 局轮转）")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--rotate", action="store_true",
                    help="复式：每 seed 4 个循环轮转座次（CRN 同牌山）")
    args = ap.parse_args()

    players = [p.strip() for p in args.players.split(",")]
    if len(players) != 4:
        ap.error(f"需要正好 4 个玩家，得到 {players}")

    rank_hist: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    pt_sum: dict[str, float] = collections.defaultdict(float)
    n_games: dict[str, int] = collections.defaultdict(int)
    score_sum: dict[str, int] = collections.defaultdict(int)

    def record(seating, scores, ranks):
        for seat, name in enumerate(seating):
            r = ranks[seat]
            rank_hist[name][r] += 1
            pt_sum[name] += PTS[r]
            n_games[name] += 1
            score_sum[name] += scores[seat]

    for h in range(args.hanchan):
        seed = None if args.seed is None else args.seed + h
        rotations = 4 if args.rotate else 1
        for rot in range(rotations):
            seating = players[rot:] + players[:rot]
            scores, ranks = play_one_hanchan(seating, seed=seed)
            print(f"[hanchan {h}.{rot}] seed={seed} seating={seating} "
                  f"scores={scores} ranks={ranks}", flush=True)
            record(seating, scores, ranks)

    print("\n=== 汇总（按模型聚合；四麻公平线 avg_rank=2.50 / avg_pt=0）===")
    for name in dict.fromkeys(players):
        n = n_games[name]
        if not n:
            continue
        avg_r = sum(r * c for r, c in rank_hist[name].items()) / n
        hist = {r: rank_hist[name][r] for r in (1, 2, 3, 4)}
        print(f"  {name:10s} n={n:5d}  avg_rank={avg_r:.3f}  "
              f"avg_pt={pt_sum[name] / n:+.2f}  rank(1/2/3/4)={hist}  "
              f"avg_score={score_sum[name] / n:.0f}")


if __name__ == "__main__":
    main()
