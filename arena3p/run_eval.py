#!/usr/bin/env python3
"""change-001 大样本对战评测（并行）。

在 riichienv/（.venv）下跑。多进程并行：每个 worker 持有一套常驻引擎（跨局复用），
每局把 RiichiEnv 的 **god-view mjai 日志** 落盘（kita→nukidora + 注入 names），
既供 libriichi3p.stat.Stat 算 Mortal 同款指标（arena3p/stat_report.py），
也可直接喂 Mortal3/tools/joint_review 可视化。

固定座位（用户已认可，方差略大但 oya 一庄内轮转、座间无系统性偏差；两个 community 座可互为一致性校验）。

例：
  .venv/bin/python arena3p/run_eval.py --players joint,community,community \\
      --n 10000 --seed0 100000 --workers 10 --log-dir arena3p/eval_runs/joint_vs_comm2
"""
from __future__ import annotations

import argparse
import gzip
import json
import multiprocessing as mp
import pathlib
import sys
import time

RIICHIENV_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RIICHIENV_ROOT))

# 这些只在 worker（fork 后）用到，import 放 worker 内更安全；但 RiichiEnv 纯对象，顶层 import 亦可。
_ENGINES = None
_PLAYERS = None
_NAMES = None
_LOGDIR = None


def _init_worker(players, logdir):
    global _ENGINES, _PLAYERS, _NAMES, _LOGDIR
    import atexit
    from arena3p.engines.subprocess_engine import SubprocessMjaiEngine
    _PLAYERS = players
    _NAMES = [f"{i}_{n}" for i, n in enumerate(players)]
    _LOGDIR = pathlib.Path(logdir)
    _ENGINES = {seat: SubprocessMjaiEngine(name, seat) for seat, name in enumerate(players)}
    atexit.register(lambda: [e.close() for e in _ENGINES.values()])


def _play(seed):
    from riichienv import RiichiEnv, GameRule
    env = RiichiEnv(game_mode="3p-red-half", rule=GameRule.default_tenhou(), seed=seed)
    obs = env.reset(scores=[35000, 35000, 35000])
    steps = 0
    while not env.done():
        acts = {}
        for pid, o in obs.items():
            a = _ENGINES[pid].act(o)
            if a is None:
                a = o.legal_actions()[0]
            acts[pid] = a
        obs = env.step(acts)
        steps += 1
        if steps > 100000:
            raise RuntimeError(f"seed {seed} step 上限保护")
    scores, ranks = env.scores(), env.ranks()

    log = env.mjai_log() if callable(env.mjai_log) else env.mjai_log
    out = []
    for e in log:
        t = e.get("type")
        if t == "kita":
            e = {**e, "type": "nukidora"}
        elif t == "start_game":
            e = {**e, "names": _NAMES}
        out.append(e)
    fp = _LOGDIR / f"g{seed}.json.gz"
    with gzip.open(fp, "wt") as f:
        for e in out:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")
    return seed, scores, ranks, steps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", required=True)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--seed0", type=int, default=100000)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--log-dir", required=True)
    args = ap.parse_args()

    players = [p.strip() for p in args.players.split(",")]
    assert len(players) == 3, players
    logdir = pathlib.Path(args.log_dir)
    logdir.mkdir(parents=True, exist_ok=True)
    summary_fp = logdir / "summary.jsonl"

    seeds = [args.seed0 + i for i in range(args.n)]
    t0 = time.time()
    done = 0
    total_steps = 0
    with summary_fp.open("w") as sf, mp.Pool(
        args.workers, initializer=_init_worker, initargs=(players, str(logdir))
    ) as pool:
        for seed, scores, ranks, steps in pool.imap_unordered(_play, seeds, chunksize=4):
            done += 1
            total_steps += steps
            sf.write(json.dumps({"seed": seed, "scores": scores, "ranks": ranks}) + "\n")
            sf.flush()
            if done % 200 == 0 or done == args.n:
                el = time.time() - t0
                rate = done / el
                eta = (args.n - done) / rate if rate else 0
                print(f"[{done}/{args.n}] {el:.0f}s  {rate*60:.1f} 半庄/min  "
                      f"{total_steps/el:.0f} 决策/s  ETA {eta/60:.1f}min", flush=True)

    el = time.time() - t0
    print(f"\n完成 {args.n} 半庄，用时 {el/60:.1f}min，{args.n/el*60:.1f} 半庄/min，"
          f"{total_steps/el:.0f} 决策/s。日志在 {logdir}（summary.jsonl + g<seed>.json.gz）")
    print(f"算指标：~/miniconda3/envs/mortal/bin/python arena3p/stat_report.py "
          f"--log-dir {logdir} --players {args.players}")


if __name__ == "__main__":
    main()
