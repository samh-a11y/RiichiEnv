#!/usr/bin/env python3
"""riichi.dev 协议探针：连真实 /ws/validate（或 /ws/ranked）把每一帧原样记录，
拿协议 ground truth（帧序列 / request_action 全字段 / start_game 有无 names / 3p vs 4p /
kita 表示 / end_game / validation_result）。只依赖 websockets，不碰模型。

安全动作策略（避免 chombo 早退，让对局多走几步好观察）：request_action 时优先 none，
否则挑一个 dahai 原样回（补 actor），再不行回 possible_actions[0]——全部来自服务器给的
合法集，echo 回 request_id。

跑法（gpu16b，aigc venv 有 websockets）：
    cd /root/riichienv
    /root/aigc_apps/venv/bin/python3 -m online3p.probe_riichidev \\
        --bot-name Nosam --endpoint validate --max-seconds 180
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .tokens import load_tokens, token_name

_REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent


def log(msg: str) -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def choose_action(req: dict, my_seat) -> dict:
    pa = req.get("possible_actions") or []
    types = [a.get("type") for a in pa]
    chosen = None
    for a in pa:
        if a.get("type") == "none":
            chosen = a
            break
    if chosen is None:
        for a in pa:
            if a.get("type") == "dahai":
                chosen = a
                break
    if chosen is None and pa:
        chosen = pa[0]
    if chosen is None:
        chosen = {"type": "none"}
    out = dict(chosen)
    out["request_id"] = req.get("request_id")
    if out.get("type") not in ("none",) and "actor" not in out and my_seat is not None:
        out["actor"] = my_seat
    return out, types


async def run(url: str, jwt: str, max_frames: int, max_seconds: float) -> None:
    from websockets.asyncio.client import connect
    headers = {"Authorization": f"Bearer {jwt}"}
    log(f"# connecting {url}")
    my_seat = None
    n = 0
    async with connect(url, additional_headers=headers, max_size=None) as ws:
        log("# connected")
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=max_seconds)
            except asyncio.TimeoutError:
                log(f"# recv timeout after {max_seconds}s"); break
            if isinstance(msg, bytes):
                log(f"[{n}] <BINARY {len(msg)} bytes> (ignored)"); n += 1; continue
            n += 1
            try:
                ev = json.loads(msg)
            except Exception:  # noqa: BLE001
                log(f"[{n}] <NON-JSON> {msg[:300]!r}"); continue
            et = ev.get("type")
            # 原样记录（observation 太长时截断标注）
            shown = dict(ev)
            obs_b64 = shown.get("observation")
            if isinstance(obs_b64, str) and len(obs_b64) > 80:
                shown["observation"] = f"<b64 len={len(obs_b64)}> {obs_b64[:60]}…"
            log(f"[{n}] RECV {et}: {json.dumps(shown, ensure_ascii=False)[:1200]}")
            if et == "start_game":
                my_seat = ev.get("id")
                log(f"#   -> my_seat={my_seat}  start_game keys={sorted(ev.keys())}")
            elif et == "start_kyoku":
                log(f"#   -> start_kyoku keys={sorted(ev.keys())} "
                    f"tehais_n={len(ev.get('tehais', []))} "
                    f"bakaze={ev.get('bakaze')} kyoku={ev.get('kyoku')} oya={ev.get('oya')}")
            elif et in ("end_game", "validation_result"):
                log(f"#   -> 终止帧 {et}: {json.dumps(ev, ensure_ascii=False)}")
                break
            elif et == "request_action":
                if not getattr(run, "_obs_dumped", False) and isinstance(obs_b64, str):
                    run._obs_dumped = True
                    import base64
                    try:
                        oj = json.loads(base64.b64decode(obs_b64))
                        log(f"#   === OBSERVATION 解码 top-keys={sorted(oj.keys())} ===")
                        log(f"#   === OBSERVATION 全文 ===\n{json.dumps(oj, ensure_ascii=False)[:4000]}")
                    except Exception as e:  # noqa: BLE001
                        log(f"#   observation 解码失败：{e!r}")
                out, types = choose_action(ev, my_seat)
                log(f"#   -> possible_actions types={types} time={ev.get('time')}")
                await ws.send(json.dumps(out, separators=(",", ":")))
                log(f"#   -> SENT {json.dumps(out, ensure_ascii=False)}")
            if n >= max_frames:
                log(f"# reached max_frames={max_frames}"); break
    log(f"# done, {n} frames")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot-name")
    ap.add_argument("--jwt")
    ap.add_argument("--tokens-file", default=str(_REPO_ROOT / "riichi.md"))
    ap.add_argument("--url-base", default="wss://game.riichi.dev")
    ap.add_argument("--endpoint", default="validate", choices=["validate", "ranked"])
    ap.add_argument("--max-frames", type=int, default=400)
    ap.add_argument("--max-seconds", type=float, default=120.0)
    args = ap.parse_args()
    if args.jwt:
        jwt = args.jwt
    else:
        toks = load_tokens(args.tokens_file)
        jwt = toks[args.bot_name]
    log(f"# bot={token_name(jwt)} endpoint={args.endpoint}")
    url = f"{args.url_base}/ws/{args.endpoint}"
    asyncio.run(run(url, jwt, args.max_frames, args.max_seconds))


if __name__ == "__main__":
    main()
