#!/usr/bin/env python3
"""用**真实 RAW 帧**回放验证 coop 的 timing 同桌判据（同桌 / 不同桌都要判对）。

输入 = 两个 bot 的 `RIICHI_RAW_LOG`（`online3p/_live/<BOT>.frames.jsonl`，用
`RIICHI_RAW=1 bash online3p/live_start.sh …` 采集），每行：
    {"n":…, "t":<本帧接收时刻>, "dir":"recv|send", "seat":…, "frame":{…}}

做法：各自按 `start_game`→`end_game` 切成对局，对每一对 (A 的第 i 局, B 的第 j 局)
同时算两个东西——

  · **金标准**：两边公开事件序列的整体匹配率。同一个服务器进程驱动同一桌，会把同一串
    公开事件在同一时刻广播给三家 ⇒ 真同桌时几乎每一条都能在时间窗内对上内容
    （实测 >0.9），不同桌则寥寥。这个判定用了整局几十上百条事件，比线上判据严得多，
    可以当真值标签。
  · **待验判据**：`TimingCoop` 线上用的那几条 —— Δstart_game < sg_gate、公开事件
    **连续公共段** ≥ min_run 条、|median(Δt)| < offset_gate、90 分位抖动 <
    spread_gate。它只看每局**前若干条**事件，因为线上要尽早开协作。

最后给混淆矩阵：待验判据相对金标准有没有假阳（把不同桌判成同桌，会让 bot 白白压制
一个无关真人）或假阴（同桌却没开协作，只是少赚）。

用法：
  cd ~/riichienv && python online3p/verify_coop_timing.py \
      --a online3p/_live/Nosam.frames.jsonl --b online3p/_live/Mason.frames.jsonl
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from online3p.coop_detect import TimingCoop, public_digest  # noqa: E402

# 非 mjai 事件（协议控制帧）：不进公开事件序列
_CTRL = {"request_action", "action_ack", "error", "validation_result"}


def load_games(path: str) -> list[dict]:
    """RAW → 对局列表 [{seat, t_sg, feats:[[t,digest],…], n_events}]。"""
    games: list[dict] = []
    cur: dict | None = None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("dir") != "recv":
                continue
            fr = rec.get("frame") or {}
            et = fr.get("type")
            t = float(rec.get("t") or 0.0)
            if et == "start_game":
                cur = {"seat": fr.get("id"), "t_sg": t, "feats": []}
                games.append(cur)
                continue
            if cur is None or et in _CTRL:
                continue
            if et == "end_game":
                cur = None
                continue
            cur["feats"].append([t, public_digest(fr)])
    for g in games:
        g["n_events"] = len(g["feats"])
    return games


def gold_same_table(tc: TimingCoop, ga: dict, gb: dict,
                    rate_gate: float, min_abs: int) -> tuple[bool, float, int]:
    """金标准：整局公开事件序列的**最长连续公共段占比**。→ (是否同桌, 占比, 段长)

    同一桌 = 同一个服务器进程把同一串公开事件广播给三家 ⇒ 整局几乎逐条相同
    （实测 55/60）。用整局几十上百条判定，比线上判据（只看前 12 条）严得多，可当真值。
    """
    L, _, _ = tc.longest_run(ga["feats"], gb["feats"])
    denom = max(1, min(ga["n_events"], gb["n_events"]))
    rate = L / denom
    same = rate >= rate_gate and L >= min_abs and ga["seat"] != gb["seat"]
    return same, rate, L


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="bot A 的 frames.jsonl")
    ap.add_argument("--b", required=True, help="bot B 的 frames.jsonl")
    ap.add_argument("--sg-gate", type=float, default=5.0)
    ap.add_argument("--min-run", type=int, default=5)
    ap.add_argument("--offset-gate", type=float, default=5.0)
    ap.add_argument("--spread-gate", type=float, default=2.0)
    ap.add_argument("--prefix", type=int, default=12,
                    help="待验判据只看每局前 N 条公开事件（线上要尽早开），默认 12")
    ap.add_argument("--gold-rate", type=float, default=0.9,
                    help="金标准：整局匹配率阈值，默认 0.9")
    ap.add_argument("--gold-min", type=int, default=10,
                    help="金标准：整局最少匹配条数，默认 10")
    args = ap.parse_args()

    tc = TimingCoop("/tmp/riichi_coop_verify", "verify", ("verify",),
                    sg_gate=args.sg_gate, min_run=args.min_run,
                    offset_gate=args.offset_gate, spread_gate=args.spread_gate)

    A, B = load_games(args.a), load_games(args.b)
    print(f"A={pathlib.Path(args.a).name}: {len(A)} 局 "
          f"(座位 {[g['seat'] for g in A]}, 事件数 {[g['n_events'] for g in A]})")
    print(f"B={pathlib.Path(args.b).name}: {len(B)} 局 "
          f"(座位 {[g['seat'] for g in B]}, 事件数 {[g['n_events'] for g in B]})\n")
    if not A or not B:
        print("❌ 至少一侧没有完整对局（需 RIICHI_RAW=1 采集）")
        return 2

    tp = fp = tn = fn = 0
    rows = []
    for i, ga in enumerate(A):
        for j, gb in enumerate(B):
            gold, rate, glen = gold_same_table(
                tc, ga, gb, args.gold_rate, args.gold_min)
            # 待验判据：只用每局前 prefix 条，且必须座位不同
            dsg = abs(ga["t_sg"] - gb["t_sg"])
            ok, det = tc.check(ga["feats"][:args.prefix],
                               gb["feats"][:args.prefix])
            pred = ok and dsg < args.sg_gate and ga["seat"] != gb["seat"]
            tp += (pred and gold); fp += (pred and not gold)
            tn += (not pred and not gold); fn += (not pred and gold)
            rows.append((i, j, ga["seat"], gb["seat"], dsg, rate, glen,
                         det.get("run", 0), det.get("offset"), det.get("jitter"),
                         gold, pred))

    print(f"{'A局':>3} {'B局':>3} {'座位':>6} {'Δsg(s)':>8} "
          f"{'金:段占比':>9} {'金:段长':>7} "
          f"{'判据:段长':>9} {'offset':>8} {'抖动':>7} {'金标准':>7} {'判据':>5}")
    for (i, j, sa, sb, dsg, rate, glen, run, off, jit, gold, pred) in rows:
        flag = "" if gold == pred else "  ← 不一致!"
        print(f"{i:>3} {j:>3} {sa}vs{sb:<3} {dsg:>8.2f} {rate:>9.3f} {glen:>7} "
              f"{run:>9} {(f'{off:+.2f}' if off is not None else '—'):>8} "
              f"{(f'{jit:.2f}' if jit is not None else '—'):>7} "
              f"{'同桌' if gold else '不同桌':>7} {'开' if pred else '不开':>5}{flag}")

    print(f"\n混淆矩阵（相对金标准）：真同桌且开={tp}  真不同桌却开={fp}（假阳）  "
          f"真不同桌且不开={tn}  真同桌却不开={fn}（假阴）")
    ok = (fp == 0 and fn == 0)
    if fp:
        print("❌ 有假阳：会让 bot 对无关真人做协作压制——必须收紧判据")
    if fn:
        print("⚠ 有假阴：同桌却没开协作（只是少赚，不伤对局）")
    if ok and tp:
        print("✅ 判据在这批真实 log 上与金标准完全一致（含至少一个真同桌样本）")
    elif ok:
        print("✅ 无假阳/假阴，但这批 log 里**没有真同桌样本**——同桌一侧尚未被验证")
    return 0 if fp == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
