#!/usr/bin/env python3
"""qgrp3p 打牌器接入 riichienv 在线对战（标准 MJAI over WebSocket）——change-003。

协议（= mjai.app / akagi「标准 MJAI bot」约定，搬到 WebSocket）：
  · 连接：默认 ``Authorization: Bearer <JWT>`` 头（--auth-mode 可切 query/message/none）。
  · 平台自动配桌后，每条 WS 消息 = 一批 mjai 事件（JSON 数组；亦容忍单事件 dict
    或 ``{"events":[...]}`` 信封）；客户端每批回**恰好一条** reaction JSON
    （无动作 = ``{"type":"none"}``）。
  · ``start_game.id`` = 本座（权威）；``start_game.names`` = 三家名（判协作 + 定第三家）。
  · ``end_game`` 一局收尾；默认保持连接等平台下一局（--exit-on-end-game 可改）。

进程内接 qgrp bot3p（模型只载一次、跨 game 复用 evcalc），方言由本客户端自持
（平台线用 ``kita``、Mortal 系 bot 用 ``nukidora``，双向改写）。

协作（用户设计）：两 bot（Nosam/Mason）**未同桌** → 纯最大化自己 EV；**同桌** →
每个 bot 目标 = 0.5·自己 pt_EV + 0.5·(−第三家 pt_EV)（实现 = 每小局把 leaf_pt
换成 0.5·self − 0.5·third，见 bot3p/ev.py::set_coop）。两 bot 各自从 names 独立
判定同桌、定位第三家，无需侧信道。

跑法（gpu16b）：
    cd /root/riichienv
    PYTHONPATH=/root/Mortal3/mortal:/root/qgrp:/root/riichienv \\
    /root/aigc_apps/venv/bin/python3 -m online3p.client \\
        --url wss://<平台地址> --bot-name Nosam \\
        --qgrp-ckpt /root/qgrp3p_run/qgrp3p_v3_ftb50k.pth --device cuda
（Nosam / Mason 各起一个进程，同一 riichi.md 取各自 JWT。）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
import traceback
from dataclasses import dataclass

from .tokens import load_tokens, token_name

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


# ── 方言（客户端自持；平台↔bot 拔北命名双向改写）──────────────────────
def _dialect_in(ev: dict) -> dict:
    """平台事件 → bot：``kita`` → ``nukidora``（Mortal 系 libriichi3p 期望）。"""
    if ev.get("type") == "kita":
        ev = dict(ev)
        ev["type"] = "nukidora"
    return ev


def _dialect_out(act: dict, nukidora_out: str) -> dict:
    """bot 动作 → 平台：``nukidora`` → ``kita``（nukidora_out='nukidora' 时不改）。"""
    if nukidora_out == "kita" and act.get("type") == "nukidora":
        act = dict(act)
        act["type"] = "kita"
    return act


@dataclass
class ClientConfig:
    url: str
    jwt: str
    my_name: str
    teammates: frozenset
    # 模型/依赖
    qgrp_ckpt: str
    trans_ckpt: str
    transcore_repo: str
    device: str
    # 协作权重
    coop_w_self: float = 0.5
    coop_w_third: float = 0.5
    # 协议旋钮（平台细节边测边调）
    auth_mode: str = "header"          # header | query | message | none
    query_key: str = "token"
    hello_msg: str | None = None       # 连上后先发的原始 JSON（可选握手）
    nukidora_out: str = "kita"         # 出站拔北写回 kita | nukidora
    reconnect: bool = True
    reconnect_sec: float = 3.0
    exit_on_end_game: bool = False
    ping_interval: float = 20.0


class OnlineMjaiClient:
    def __init__(self, cfg: ClientConfig):
        self.cfg = cfg
        self.bot = None
        self.my_seat: int | None = None
        self._build_engine()

    # ── 日志（走 stderr，不污染协议）────────────────────────────
    def log(self, msg: str) -> None:
        sys.stderr.write(f"[{self.cfg.my_name}] {msg}\n")
        sys.stderr.flush()

    # ── 引擎（模型只载一次，evcalc 跨 game 复用）─────────────────
    def _build_engine(self) -> None:
        try:
            from bot3p.bot import QgrpBot3P
            from bot3p.config import BotConfig3P
            from bot3p.ev import EvCalc3P
        except ImportError as e:  # noqa: BLE001
            raise SystemExit(
                "import bot3p 失败——PYTHONPATH 需含 qgrp 仓根 + Mortal3/mortal。\n"
                f"  详细：{e}")
        self._QgrpBot3P = QgrpBot3P
        self.bot_cfg = BotConfig3P(
            qgrp_ckpt=self.cfg.qgrp_ckpt, trans_ckpt=self.cfg.trans_ckpt,
            transcore_repo=self.cfg.transcore_repo, device=self.cfg.device,
            name=self.cfg.my_name)
        self.evcalc = EvCalc3P(self.bot_cfg)  # 模型 + trans_core 载入（贵，仅一次）
        self.log(f"引擎就绪 ckpt={self.cfg.qgrp_ckpt} device={self.cfg.device} "
                 f"teammates={sorted(self.cfg.teammates)}")

    # ── 开局：定座位 + 协作判定 + 重建 bot ──────────────────────
    def _on_start_game(self, ev: dict) -> None:
        names = list(ev.get("names") or [])
        seat = ev.get("id")
        if seat is None:
            # 平台未给 id（不合标准）：按名字定位，再不行缺省 0
            seat = names.index(self.cfg.my_name) if self.cfg.my_name in names else 0
            self.log(f"WARN start_game 无 id，按名字/缺省定座 seat={seat} names={names}")
        self.my_seat = int(seat)
        self.bot = self._QgrpBot3P(self.my_seat, self.bot_cfg, evcalc=self.evcalc)
        third = self._detect_third(names)
        if third is not None:
            self.evcalc.set_coop(third, self.cfg.coop_w_self, self.cfg.coop_w_third)
            self.log(f"[coop ON] seat={self.my_seat} names={names} third_seat={third} "
                     f"w=(self {self.cfg.coop_w_self}, third {self.cfg.coop_w_third})")
        else:
            self.evcalc.clear_coop()
            self.log(f"[coop OFF] seat={self.my_seat} names={names}（队友不在桌）")

    def _detect_third(self, names: list) -> int | None:
        """同桌判定：names 里有队友（另一个我方 bot 名）则返回第三家座位，否则 None。"""
        if len(names) != 3 or self.my_seat is None:
            return None
        teammate_seat = None
        for i, nm in enumerate(names):
            if i != self.my_seat and nm in self.cfg.teammates and nm != self.cfg.my_name:
                teammate_seat = i
                break
        if teammate_seat is None:
            return None
        return ({0, 1, 2} - {self.my_seat, teammate_seat}).pop()

    # ── 一批事件 → 一条 reaction ────────────────────────────────
    def handle_batch(self, batch: list) -> tuple[dict, bool]:
        last = None
        end = False
        for raw in batch:
            if not isinstance(raw, dict):
                continue
            ev = _dialect_in(raw)
            et = ev.get("type")
            if et == "start_game":
                self._on_start_game(ev)
            elif et == "end_game":
                end = True
            if self.bot is None:
                continue
            try:
                r = self.bot.react(json.dumps(ev, separators=(",", ":")))
            except Exception:  # noqa: BLE001
                self.log("react 异常：\n" + traceback.format_exc())
                r = None
            if r:
                last = r
        if last is None:
            out = {"type": "none"}
        else:
            out = json.loads(last)
            out.pop("meta", None)
        return _dialect_out(out, self.cfg.nukidora_out), end

    # ── 单次连接生命周期 ────────────────────────────────────────
    async def _run_once(self) -> str:
        from websockets.asyncio.client import connect
        url = self.cfg.url
        headers = {}
        if self.cfg.auth_mode == "header":
            headers["Authorization"] = f"Bearer {self.cfg.jwt}"
        elif self.cfg.auth_mode == "query":
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{self.cfg.query_key}={self.cfg.jwt}"
        async with connect(url, additional_headers=headers,
                            ping_interval=self.cfg.ping_interval,
                            max_size=None) as ws:
            self.log(f"已连接 {self.cfg.url}（auth={self.cfg.auth_mode}）")
            if self.cfg.auth_mode == "message":
                await ws.send(json.dumps({"type": "auth", "token": self.cfg.jwt}))
            if self.cfg.hello_msg:
                await ws.send(self.cfg.hello_msg)
            async for msg in ws:
                try:
                    data = json.loads(msg)
                except (json.JSONDecodeError, TypeError):
                    self.log(f"非 JSON 消息，忽略：{str(msg)[:200]!r}")
                    continue
                if isinstance(data, list):
                    batch = data
                elif isinstance(data, dict) and isinstance(data.get("events"), list):
                    batch = data["events"]           # {"events":[...]} 信封
                elif isinstance(data, dict):
                    batch = [data]                    # 单事件
                else:
                    self.log(f"无法识别的消息结构，忽略：{str(data)[:200]}")
                    continue
                out, end = self.handle_batch(batch)
                await ws.send(json.dumps(out, separators=(",", ":")))
                if end:
                    self.log(f"收到 end_game（seat={self.my_seat}）")
                    if self.cfg.exit_on_end_game:
                        return "exit"
            return "closed"

    async def run(self) -> None:
        while True:
            try:
                result = await self._run_once()
            except Exception as e:  # noqa: BLE001
                self.log(f"连接异常：{e!r}")
                result = "error"
            if result == "exit" or not self.cfg.reconnect:
                break
            self.log(f"{self.cfg.reconnect_sec}s 后重连…")
            await asyncio.sleep(self.cfg.reconnect_sec)


def build_config(argv=None) -> ClientConfig:
    ap = argparse.ArgumentParser(
        description="qgrp3p 在线对战客户端（MJAI over WebSocket）")
    ap.add_argument("--url", default=os.environ.get("RIICHI_WS_URL"),
                    help="平台 WebSocket 地址（或 env RIICHI_WS_URL）")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--bot-name", help="从 --tokens-file 按名取 JWT（Nosam/Mason）")
    g.add_argument("--jwt", help="直接给 JWT")
    ap.add_argument("--tokens-file", default=str(_REPO_ROOT / "riichi.md"))
    ap.add_argument("--teammates", default="Nosam,Mason",
                    help="我方 bot 名集合（同桌判定用）")
    ap.add_argument("--qgrp-ckpt", default=os.environ.get(
        "QGRP3P_CKPT", "/root/qgrp3p_run/qgrp3p_v3_ftb50k.pth"))
    ap.add_argument("--trans-ckpt", default=os.environ.get(
        "QGRP3P_TRANS", "/root/zeroppo-grp/grp_trans3p_v1.pth"))
    ap.add_argument("--transcore-repo", default=os.environ.get(
        "QGRP3P_TRANSCORE_REPO", "/root/zeroppo-grp"))
    ap.add_argument("--device", default=os.environ.get("QGRP3P_DEVICE", "cuda"))
    ap.add_argument("--coop-w-self", type=float, default=0.5)
    ap.add_argument("--coop-w-third", type=float, default=0.5)
    ap.add_argument("--auth-mode", choices=["header", "query", "message", "none"],
                    default="header")
    ap.add_argument("--query-key", default="token")
    ap.add_argument("--hello-msg", default=None,
                    help="连上后先发的原始 JSON（可选平台握手）")
    ap.add_argument("--nukidora-out", choices=["kita", "nukidora"], default="kita")
    ap.add_argument("--no-reconnect", action="store_true")
    ap.add_argument("--reconnect-sec", type=float, default=3.0)
    ap.add_argument("--exit-on-end-game", action="store_true")
    args = ap.parse_args(argv)

    if not args.url:
        ap.error("必须给 --url 或设 RIICHI_WS_URL")
    if args.jwt:
        jwt = args.jwt
    elif args.bot_name:
        toks = load_tokens(args.tokens_file)
        if args.bot_name not in toks:
            ap.error(f"{args.bot_name!r} 不在 {args.tokens_file}；已有 {list(toks)}")
        jwt = toks[args.bot_name]
    else:
        ap.error("需要 --bot-name 或 --jwt")
    my_name = token_name(jwt) or (args.bot_name or "qgrp3p")

    return ClientConfig(
        url=args.url, jwt=jwt, my_name=my_name,
        teammates=frozenset(t.strip() for t in args.teammates.split(",")),
        qgrp_ckpt=args.qgrp_ckpt, trans_ckpt=args.trans_ckpt,
        transcore_repo=args.transcore_repo, device=args.device,
        coop_w_self=args.coop_w_self, coop_w_third=args.coop_w_third,
        auth_mode=args.auth_mode, query_key=args.query_key,
        hello_msg=args.hello_msg, nukidora_out=args.nukidora_out,
        reconnect=not args.no_reconnect, reconnect_sec=args.reconnect_sec,
        exit_on_end_game=args.exit_on_end_game)


def main(argv=None) -> None:
    cfg = build_config(argv)
    try:  # 单样本推理限 1 线程（run_stdio 同款纪律）
        import torch
        torch.set_num_threads(1)
    except Exception:  # noqa: BLE001
        pass
    client = OnlineMjaiClient(cfg)
    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        client.log("Ctrl-C 退出")


if __name__ == "__main__":
    main()
