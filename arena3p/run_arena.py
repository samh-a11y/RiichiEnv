#!/usr/bin/env python3
"""change-001 三麻三方对战驱动。

在 riichienv/（.venv 激活）下跑：
  python arena3p/run_arena.py --players community,community,community --hanchan 1 --seed 42
  python arena3p/run_arena.py --players joint,joint,joint --hanchan 1 --seed 42
  python arena3p/run_arena.py --players joint,community,community --hanchan 1 --seed 42   # 里程碑

每个座位 = 一个 MJAI 子进程引擎（见 arena3p/engines/）。裁判 = RiichiEnv 3p-red-half 天凤规则。
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import sys

RIICHIENV_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RIICHIENV_ROOT))

from riichienv import RiichiEnv, GameRule  # noqa: E402
from arena3p.engines.subprocess_engine import SubprocessMjaiEngine  # noqa: E402


def play_one_hanchan(players: list[str], seed: int | None = None):
    """跑一整局半庄，返回 (scores, ranks)。每座一个独立子进程引擎，用完即关。"""
    env = RiichiEnv(game_mode="3p-red-half", rule=GameRule.default_tenhou(), seed=seed)
    engines = {seat: SubprocessMjaiEngine(name, seat) for seat, name in enumerate(players)}
    try:
        obs = env.reset(scores=[35000, 35000, 35000])
        steps = 0
        while not env.done():
            acts = {}
            for pid, o in obs.items():
                a = engines[pid].act(o)
                if a is None:  # 终极兜底（_resolve_none 已尽力）
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
                    help="逗号分隔三个模型名，如 joint,community,community")
    ap.add_argument("--hanchan", type=int, default=1)
    ap.add_argument("--seed", type=int, default=None, help="第 h 局用 seed+h")
    args = ap.parse_args()

    players = [p.strip() for p in args.players.split(",")]
    if len(players) != 3:
        ap.error(f"需要正好 3 个玩家，得到 {players}")

    rank_hist: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    place_sum: dict[str, float] = collections.defaultdict(float)
    place_n: dict[str, int] = collections.defaultdict(int)
    score_sum: dict[str, int] = collections.defaultdict(int)

    for h in range(args.hanchan):
        seed = None if args.seed is None else args.seed + h
        scores, ranks = play_one_hanchan(players, seed=seed)
        print(f"[hanchan {h}] seed={seed} scores={scores} ranks={ranks}", flush=True)
        for seat, name in enumerate(players):
            r = ranks[seat]
            rank_hist[name][r] += 1
            place_sum[name] += r
            place_n[name] += 1
            score_sum[name] += scores[seat]

    print("\n=== 汇总（按模型聚合；avg placement 越低越强，三麻公平线 2.00）===")
    for name in dict.fromkeys(players):  # 去重保序
        n = place_n[name]
        avg = place_sum[name] / n if n else float("nan")
        hist = {r: rank_hist[name][r] for r in (1, 2, 3)}
        avg_score = score_sum[name] / n if n else float("nan")
        print(f"  {name:12s} n={n:4d}  avg_place={avg:.3f}  "
              f"rank(1/2/3)={hist}  avg_score={avg_score:.0f}")


if __name__ == "__main__":
    main()
