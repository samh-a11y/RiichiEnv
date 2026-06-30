#!/usr/bin/env python3
"""review 阶段 1（生成）：跑 N 局 arena（真正的子进程 builder 链路），录每座的
(视角事件流, mjai 动作) tape + god-view 牌谱，供阶段 2 用各模型【独立原版推理代码】重放比对。

跑在 riichienv/.venv（有 riichienv）；引擎子进程用 conda mortal（registry）。
固定座位（引擎吃视角事件出动作、与物理座位无关；座位平衡是 run_eval --rotate 的事，
此处只验证「每个决策点的动作 = 模型本应给出的动作」）。

例：
  .venv/bin/python arena3p/review/gen_tapes.py \\
      --players joint-mse,joint-mse,v8guard --n 20 --seed0 800000 \\
      --out-dir arena3p/eval_runs/c002_review
"""
from __future__ import annotations

import argparse
import gzip
import json
import pathlib
import sys

RIICHIENV_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RIICHIENV_ROOT))

from riichienv import RiichiEnv, GameRule          # noqa: E402
from arena3p.engines.subprocess_engine import SubprocessMjaiEngine  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", required=True, help="逗号分隔，如 joint-mse,joint-mse,v8guard")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed0", type=int, default=800000)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    players = [p.strip() for p in args.players.split(",")]
    assert len(players) == 3, players
    outdir = pathlib.Path(args.out_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 每座一个常驻引擎（跨局复用，与正式 run_eval 的一个 worker 同行为），record=True 录 tape
    engines = {seat: SubprocessMjaiEngine(name, seat, record=True)
               for seat, name in enumerate(players)}
    print(f"模型={players} n={args.n} seed0={args.seed0} out={outdir}", flush=True)

    ok = True
    for i in range(args.n):
        seed = args.seed0 + i
        env = RiichiEnv(game_mode="3p-red-half", rule=GameRule.default_tenhou(), seed=seed)
        obs = env.reset(scores=[35000, 35000, 35000])
        steps = 0
        while not env.done():
            acts = {}
            for pid, o in obs.items():
                a = engines[pid].act(o)
                if a is None:
                    a = o.legal_actions()[0]
                acts[pid] = a
            obs = env.step(acts)
            steps += 1
            if steps > 100000:
                raise RuntimeError(f"seed {seed} step 上限保护")
        scores, ranks = env.scores(), env.ranks()
        # 守恒/ranks 健全性
        consv = (sum(scores) == 105000)
        rank_ok = (sorted(ranks) == [1, 2, 3])
        if not (consv and rank_ok):
            ok = False
        # god-view 牌谱（kita→nukidora + 注入 names）
        log = env.mjai_log() if callable(env.mjai_log) else env.mjai_log
        out = []
        for e in log:
            t = e.get("type")
            if t == "kita":
                e = {**e, "type": "nukidora"}
            elif t == "start_game":
                e = {**e, "names": players}
            out.append(e)
        with gzip.open(outdir / f"g{seed}.json.gz", "wt") as f:
            for e in out:
                f.write(json.dumps(e, separators=(",", ":")) + "\n")
        print(f"  seed {seed}: scores={scores} ranks={ranks} steps={steps} "
              f"守恒={'✓' if consv else '✗'} ranks={'✓' if rank_ok else '✗'}", flush=True)

    # 落每座 tape（线性、跨局，与该座引擎的 Bot 状态轨迹一致）
    print("\n=== 落 tape（每座一段，跨局线性）===", flush=True)
    for seat, eng in engines.items():
        tp = outdir / f"tape_seat{seat}_{players[seat]}.jsonl"
        with tp.open("w") as f:
            f.write(json.dumps({"_meta": {"seat": seat, "model": players[seat],
                                          "n_acts": len(eng.tape)}}) + "\n")
            for rec in eng.tape:
                f.write(json.dumps(rec, separators=(",", ":")) + "\n")
        # 统计动作分布
        from collections import Counter
        types = Counter(r["resp"].get("type") for r in eng.tape)
        sel_fail = sum(1 for r in eng.tape if r.get("select_ok") is False)
        print(f"  seat{seat} {players[seat]}: {len(eng.tape)} acts, select_fail={sel_fail}, "
              f"动作分布={dict(types)} -> {tp.name}", flush=True)
        eng.close()

    print(f"\n{'✓ 牌谱全部守恒/ranks 合法' if ok else '✗ 有局不守恒/ranks 异常（见上）'}", flush=True)
    print("阶段 2 重放比对（分模型分进程，各用原版推理代码）：", flush=True)
    for seat, name in enumerate(players):
        print(f"  ~/miniconda3/envs/mortal/bin/python arena3p/review/replay_truth.py "
              f"--model {name} --tape {outdir}/tape_seat{seat}_{name}.jsonl", flush=True)


if __name__ == "__main__":
    main()
