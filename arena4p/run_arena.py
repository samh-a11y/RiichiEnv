#!/usr/bin/env python3
"""四麻四方对战驱动（qgrp change-002：QGRP 打牌器 vs Mortal）。

在 riichienv/（.venv 激活）下跑：
  python arena4p/run_arena.py --players qgrp,mortal,mortal,mortal --hanchan 4 --seed 100
  python arena4p/run_arena.py --players qgrp,mortal,mortal,mortal --hanchan 100 --seed 0 --rotate --jobs 6

--rotate = 复式（CRN）：同 seed 跑 4 个循环轮转座次（同牌山、座位效应对消），
汇总按模型聚合 avg_rank / avg_pt（四麻公平线 avg_rank 2.50）。
裁判 = RiichiEnv 4p-red-half 天凤规则；每模型槽一个 MJAI 子进程引擎（见 engines/），
**跨半庄持久复用**（c09 提速件：模型只加载一次，start_game 携 id 换座重建轻量
bot——冷启动原本占每半庄墙钟的大头）；--jobs N = N 个 worker 进程各持一套引擎
并行跑不同 (seed,rot)（对局彼此独立，GPU 空闲率高，近线性加速）。
注意：RiichiEnv.scores 终局不归还桌上立直棒（同 3p 已知口径），素点仅供参考，
rank/pt 不受影响。
"""
from __future__ import annotations

import argparse
import atexit
import collections
import pathlib
import sys

RIICHIENV_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RIICHIENV_ROOT))

from riichienv import RiichiEnv, GameRule  # noqa: E402
from arena4p.engines.subprocess_engine import SubprocessMjaiEngine  # noqa: E402

PTS = {1: 90.0, 2: 45.0, 3: 0.0, 4: -135.0}  # 天凤凤南口径（与 qgrp bot 默认一致）

# worker 进程级持久件（--jobs 时经 initializer 建；单进程路径直接用）
_ENGINES: list[SubprocessMjaiEngine] | None = None
_PLAYERS: list[str] | None = None


def _worker_init(players: list[str]):
    global _ENGINES, _PLAYERS
    _PLAYERS = players
    # 并发拉起 4 个引擎（各自 torch/ckpt 冷启动数秒，串行等 ready 白白叠加）
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(4) as tp:
        _ENGINES = list(tp.map(
            lambda sn: SubprocessMjaiEngine(sn[1], sn[0]),
            enumerate(players)))
    atexit.register(lambda: [e.close() for e in _ENGINES])


def play_one_hanchan(engines: list[SubprocessMjaiEngine], rot: int,
                     seed: int | None = None):
    """seat s 由持久引擎槽 (rot+s)%4 打（= seating[s]==players[(rot+s)%4]）。"""
    env = RiichiEnv(game_mode="4p-red-half", rule=GameRule.default_tenhou(),
                    seed=seed)
    obs = env.reset(scores=[25000] * 4)
    steps = 0
    while not env.done():
        acts = {}
        for pid, o in obs.items():
            eng = engines[(rot + pid) % 4]
            eng.set_seat(pid)
            a = eng.act(o)
            if a is None:
                legals = o.legal_actions()
                a = legals[0]
            acts[pid] = a
        obs = env.step(acts)
        steps += 1
        if steps > 100000:
            raise RuntimeError("step 上限保护触发（疑似死循环）")
    return env.scores(), env.ranks()


def _run_task(task: tuple[int, int, int | None]):
    h, rot, seed = task
    seating = _PLAYERS[rot:] + _PLAYERS[:rot]
    scores, ranks = play_one_hanchan(_ENGINES, rot, seed)
    print(f"[hanchan {h}.{rot}] seed={seed} seating={seating} "
          f"scores={scores} ranks={ranks}", flush=True)
    return seating, scores, ranks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", required=True,
                    help="逗号分隔四个模型名，如 qgrp,mortal,mortal,mortal")
    ap.add_argument("--hanchan", type=int, default=1,
                    help="局数（--rotate 时 = seed 数，每 seed 4 局轮转）")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--rotate", action="store_true",
                    help="复式：每 seed 4 个循环轮转座次（CRN 同牌山）")
    ap.add_argument("--jobs", type=int, default=1,
                    help="并行 worker 数（各持一套持久引擎，跑不同对局）")
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

    tasks = []
    for h in range(args.hanchan):
        seed = None if args.seed is None else args.seed + h
        for rot in range(4 if args.rotate else 1):
            tasks.append((h, rot, seed))

    if args.jobs <= 1:
        _worker_init(players)
        results = [_run_task(t) for t in tasks]
    else:
        import concurrent.futures as cf
        with cf.ProcessPoolExecutor(
                max_workers=args.jobs,
                initializer=_worker_init, initargs=(players,)) as ex:
            results = list(ex.map(_run_task, tasks))

    for seating, scores, ranks in results:
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
