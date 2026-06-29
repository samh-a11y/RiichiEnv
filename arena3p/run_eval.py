#!/usr/bin/env python3
"""change-001 大样本对战评测（并行 + 座位轮转复式 + 断点续跑）。

在 riichienv/（.venv）下跑。多进程并行：每个 worker 持有一套常驻引擎（跨局复用），
每局把 RiichiEnv 的 **god-view mjai 日志** 落盘（kita→nukidora + 注入 names），
既供 libriichi3p.stat.Stat 算 Mortal 同款指标（arena3p/stat_report.py），
也可直接喂 Mortal3/tools/joint_review 可视化。

座位轮转复式（--rotate，三个**不同**模型）：每个 seed 跑 3 个**循环轮转**座次，
同 seed=同牌山（CRN），每个模型在每个座位各打 N 局 → 消掉座位/发牌运气，得真实强弱。
日志按**模型名**落盘（names=该座次模型名），stat 跨座位自动按模型聚合。
非 --rotate（旧固定座位）：names 带座位前缀 `i_name`，文件 `g{seed}.json.gz`，向后兼容。

--resume：已存在 god-view 日志的 (seed,轮转) 跳过，summary 追加写（崩溃可续）。

例（座位轮转复式 4000×3=12000 半庄）：
  .venv/bin/python arena3p/run_eval.py --players joint,community,v8 --rotate \\
      --n 4000 --seed0 200000 --workers 24 --log-dir arena3p/eval_runs/rr_4k3
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

_ENGINES = None
_NAMES = None
_LOGDIR = None
_ROT = None


def _init_worker(players, names, logdir, rot):
    global _ENGINES, _NAMES, _LOGDIR, _ROT
    import atexit
    from arena3p.engines.subprocess_engine import SubprocessMjaiEngine
    _NAMES = names
    _LOGDIR = pathlib.Path(logdir)
    _ROT = rot
    _ENGINES = {seat: SubprocessMjaiEngine(name, seat) for seat, name in enumerate(players)}
    atexit.register(lambda: [e.close() for e in _ENGINES.values()])


def _logpath(seed):
    fn = f"g{seed}.json.gz" if _ROT is None else f"g{seed}_r{_ROT}.json.gz"
    return _LOGDIR / fn


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
    fp = _logpath(seed)
    tmp = fp.with_suffix(".gz.tmp")  # 原子落盘：写 .tmp 再 rename，--resume 据完整文件判断
    with gzip.open(tmp, "wt") as f:
        for e in out:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")
    tmp.rename(fp)
    return seed, scores, ranks, steps


def _seatings(players, rotate):
    """rotate：3 个循环轮转 [(rot, seating), ...]；否则单一固定座次（rot=None）。"""
    if not rotate:
        return [(None, list(players))]
    assert len(set(players)) == 3, f"--rotate 需 3 个不同模型，给的是 {players}"
    return [(r, players[r:] + players[:r]) for r in range(3)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", required=True)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--seed0", type=int, default=100000)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--log-dir", required=True)
    ap.add_argument("--rotate", action="store_true", help="座位轮转复式（3 不同模型，每 seed×3 轮转）")
    ap.add_argument("--resume", action="store_true", help="跳过已有日志的 (seed,轮转)，summary 追加")
    args = ap.parse_args()

    players = [p.strip() for p in args.players.split(",")]
    assert len(players) == 3, players
    logdir = pathlib.Path(args.log_dir)
    logdir.mkdir(parents=True, exist_ok=True)
    summary_fp = logdir / "summary.jsonl"

    seatings = _seatings(players, args.rotate)
    seeds = [args.seed0 + i for i in range(args.n)]
    total_tasks = args.n * len(seatings)
    # rotate 用模型名落盘（跨座位按模型聚合）；固定座位用座位前缀名
    t0 = time.time()
    done = 0
    total_steps = 0
    mode = "a" if args.resume else "w"
    print(f"模型={players} 轮转={'是('+str(len(seatings))+'座次)' if args.rotate else '否'} "
          f"seeds={args.n} 总任务={total_tasks} workers={args.workers} resume={args.resume}", flush=True)

    with summary_fp.open(mode) as sf:
        for rot, seating in seatings:
            names = list(seating) if args.rotate else [f"{i}_{n}" for i, n in enumerate(seating)]
            rot_logdir = logdir
            # --resume：本轮转待跑 seeds（按落盘文件判断）
            if args.resume:
                pending = [s for s in seeds
                           if not (rot_logdir / (f"g{s}_r{rot}.json.gz" if rot is not None
                                                 else f"g{s}.json.gz")).exists()]
            else:
                pending = list(seeds)
            tag = f"轮转{rot} 座次{seating}" if args.rotate else f"座次{seating}"
            print(f"=== {tag}：待跑 {len(pending)}/{args.n} ===", flush=True)
            if not pending:
                done += args.n
                continue
            with mp.Pool(args.workers, initializer=_init_worker,
                         initargs=(seating, names, str(logdir), rot)) as pool:
                for seed, scores, ranks, steps in pool.imap_unordered(_play, pending, chunksize=4):
                    done += 1
                    total_steps += steps
                    sf.write(json.dumps({"seed": seed, "rot": rot, "seating": seating,
                                         "scores": scores, "ranks": ranks}) + "\n")
                    sf.flush()
                    if done % 200 == 0 or done == total_tasks:
                        el = time.time() - t0
                        rate = done / el if el else 0
                        eta = (total_tasks - done) / rate if rate else 0
                        print(f"[{done}/{total_tasks}] {el:.0f}s  {rate*60:.1f} 半庄/min  "
                              f"{total_steps/el:.0f} 决策/s  ETA {eta/60:.1f}min", flush=True)

    el = time.time() - t0
    print(f"\n完成 {done} 半庄（{total_tasks} 目标），用时 {el/60:.1f}min。日志在 {logdir}", flush=True)
    print(f"算指标：stat_report.py --log-dir {logdir} --players {args.players}"
          + (" --rotate" if args.rotate else ""), flush=True)


if __name__ == "__main__":
    main()
