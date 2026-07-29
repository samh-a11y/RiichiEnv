#!/usr/bin/env python3
"""上线前**强制门**：用真实 RAW 帧离线回放整条客户端处理链，抓运行时异常。

为什么必须有这一步（2026-07-28 事故）：把 `ClientConfig.coop_min_events` 改名成
`coop_min_run` 时漏改了 `_try_coop_timing` 里的一处引用。`py_compile` 语法检查抓不到
属性名错误，于是直接上了 ranked——每收到一帧就 `AttributeError` → 断线 → 重连 → 再抛，
反复 120+ 次，bot 全程无法出牌，平台代打摸切，真实排位分受损。

本门在**不碰平台**的前提下跑通与线上完全相同的代码路径：`handle_frame` →
`_feed` → `_note_event` → `_try_coop_timing`（含侧信道 IO 与 detect）→ `bot.react`
（真实模型推理）→ `_on_request_action` → `_sanitize`。任何异常都会被计数并打印。

⚠ 纪律：改过 online3p/ 或 hybrid/ 的代码后，**先过这个门（连同 coop 判据门），才能上
ranked** —— 正门是 `bash online3p/go_live.sh`，它跑完两门才签发通行证。

用法：
  cd ~/riichienv && PYTHONPATH=$HOME/Mortal3/mortal:$HOME/qgrp:$PWD \
    ~/miniconda3/envs/mortal/bin/python online3p/replay_smoke.py \
      --frames <某个 *.frames.jsonl> --backend hybrid --alpha 0.18 --device cuda
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from online3p.client import ClientConfig, OnlineMjaiClient  # noqa: E402
from online3p.coop_detect import TimingCoop  # noqa: E402

HOME = pathlib.Path.home()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", required=True, help="RAW frames.jsonl（RIICHI_RAW=1 采集）")
    ap.add_argument("--limit", type=int, default=300, help="最多回放多少 recv 帧")
    ap.add_argument("--backend", default="hybrid",
                    choices=["qgrp", "mortal3", "hybrid"])
    ap.add_argument("--alpha", type=float, default=0.18)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--coop-mode", default="timing",
                    choices=["timing", "fingerprint"])
    ap.add_argument("--qgrp-ckpt", default=str(HOME / "qgrp3p_run/qgrp3p_v5_full.pth"))
    ap.add_argument("--trans-ckpt", default=str(HOME / "zeroppo-grp/grp_trans3p_v1.pth"))
    ap.add_argument("--transcore-repo", default=str(HOME / "zeroppo-grp"))
    ap.add_argument("--coop-dir", default="/tmp/riichi_coop_replay")
    ap.add_argument("--name", default="ReplaySmoke",
                    help="本次回放的 bot 名。双边回放（验证 coop 命中路径）：先用 "
                         "--name A 跑一侧留下 announce，再用 --name B 跑另一侧")
    ap.add_argument("--teammates", default="",
                    help="逗号分隔；默认 = --name 自己 + Peer")
    args = ap.parse_args()

    cfg = ClientConfig(
        url="wss://replay.invalid/ws/ranked",   # 不连接，只借配置
        jwt="", my_name=args.name,
        qgrp_ckpt=args.qgrp_ckpt, trans_ckpt=args.trans_ckpt,
        transcore_repo=args.transcore_repo, device=args.device,
        backend=args.backend, alpha=args.alpha,
        coop_enabled=True, coop_dir=args.coop_dir, coop_mode=args.coop_mode,
        teammates=(tuple(t.strip() for t in args.teammates.split(","))
                   if args.teammates else (args.name, "Peer")))
    coop = TimingCoop(args.coop_dir, cfg.my_name, cfg.teammates,
                      sg_gate=cfg.coop_sg_gate, min_run=cfg.coop_min_run,
                      offset_gate=cfg.coop_offset_gate,
                      spread_gate=cfg.coop_spread_gate, keep=cfg.coop_keep)
    client = OnlineMjaiClient(cfg, coop=coop)

    n_recv = n_act = n_err = 0
    errs: list[str] = []
    types: dict[str, int] = {}
    with open(args.frames, "r", encoding="utf-8") as f:
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
            if not isinstance(fr, dict):
                continue
            n_recv += 1
            client._recv_t = float(rec.get("t") or 0.0)
            types[fr.get("type", "?")] = types.get(fr.get("type", "?"), 0) + 1
            try:
                out, _ctrl = client.handle_frame(fr)
                if out:
                    n_act += 1
                    json.loads(out)          # 动作必须是合法 JSON
            except Exception as e:           # noqa: BLE001
                n_err += 1
                if len(errs) < 5:
                    import traceback
                    errs.append(f"帧#{n_recv} type={fr.get('type')}: {e!r}\n"
                                + traceback.format_exc())
            if n_recv >= args.limit:
                break

    print(f"回放 {n_recv} 帧（{args.frames}）")
    print(f"  帧类型: {dict(sorted(types.items(), key=lambda kv: -kv[1]))}")
    print(f"  发出动作 {n_act} 条，异常 {n_err} 次")
    print(f"  coop 侧信道: announce 次数>0 ⇒ {pathlib.Path(args.coop_dir).exists()}，"
          f"命中 third={client._coop_third}")
    for e in errs:
        print("\n--- 异常样本 ---\n" + e)
    if n_err:
        print(f"\n❌ 回放门未过：{n_err} 次异常——**不得上线**")
        return 1
    if n_act == 0:
        print("\n⚠ 回放门：一条动作都没发出（帧数太少或全是控制帧？）")
        return 1
    print("\n✅ 回放门通过：整条链路零异常，动作可解析")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
