#!/usr/bin/env python3
"""qgrp3p 打牌器接入 riichi.dev / RiichiLab 在线三麻对战——change-003。

真实协议（探针 /ws/validate 实测，见 sessions/c07）：
  · 连接 `wss://game.riichi.dev/ws/{validate,ranked}`，`Authorization: Bearer <JWT>` 头。
  · 平台自动配桌、驱动游戏；每帧 = **单个 JSON 对象**。服务器发的 mjai 事件
    （start_game/start_kyoku/tsumo/dahai/kita/pon/kan/reach/hora/end_kyoku…）逐帧到达，
    bot **只对 `request_action` 帧回复**——一条 mjai 动作 + **回显 `request_id`**
    （不响应=`{"type":"none","request_id":…}`）。`request_action` 带 `possible_actions`
    （合法集，防 chombo 兜底用）+ base64 `observation`（本客户端不需要，状态从事件流跟踪）。
  · `start_game.id` = 本座（0-2），**无 names / 无玩家身份 / 无 game_id**。
  · `action_ack` 确认；`end_game`/`validation_result` 终止 → 断开（平台不自动续局，
    ranked 下重连即重新排队）。`kita` = 拔北（客户端 kita↔nukidora）。

架构：进程内接 qgrp bot3p（模型只载一次），把每个 mjai 事件喂 `bot.react()` 跟踪状态、
缓存其触发的动作，`request_action` 到达时发出+补 request_id；`possible_actions` 做合法性
兜底防 chombo。全在 gpu16b aigc venv（torch/libriichi3p/websockets）。

协作（用户设计，`bot3p/ev.py::set_coop` 已就绪，同桌 0.5·self−0.5·third）：**riichi.dev
协议不暴露玩家身份/对局 ID，无法从协议数据判定两 bot 是否同桌**。检测做成可插拔
`coop_detector`，默认 None＝纯自己 EV（= 未同桌行为）。侧信道检测方案见 README / 待用户定。

跑法（gpu16b）：
    cd /root/riichienv
    PYTHONPATH=/root/Mortal3/mortal:/root/qgrp:/root/riichienv \\
    /root/aigc_apps/venv/bin/python3 -m online3p.client \\
        --url wss://game.riichi.dev/ws/validate --bot-name Nosam \\
        --qgrp-ckpt /root/qgrp3p_run/qgrp3p_v3_ftb50k.pth --device cuda
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

# request_action / 确认 / 终止 / 错误 = 控制帧，不喂 bot；其余按 mjai 事件喂
_CONTROL = {"request_action", "action_ack", "validation_result", "end_game", "error"}
_TERMINAL = {"end_game", "validation_result"}


def _dialect_in(ev: dict) -> dict:
    """平台事件 → bot：`kita` → `nukidora`（Mortal 系 libriichi3p 期望）。"""
    if ev.get("type") == "kita":
        ev = dict(ev)
        ev["type"] = "nukidora"
    return ev


def _dialect_out(act: dict, nukidora_out: str) -> dict:
    """bot 动作 → 平台：`nukidora` → `kita`（nukidora_out='nukidora' 时不改）。"""
    if nukidora_out == "kita" and act.get("type") == "nukidora":
        act = dict(act)
        act["type"] = "kita"
    return act


@dataclass
class ClientConfig:
    url: str
    jwt: str
    my_name: str
    qgrp_ckpt: str
    trans_ckpt: str
    transcore_repo: str
    device: str
    coop_w_self: float = 0.5
    coop_w_third: float = 0.5
    nukidora_out: str = "kita"
    reconnect: bool = True
    reconnect_sec: float = 3.0
    ping_interval: float = 20.0


class OnlineMjaiClient:
    def __init__(self, cfg: ClientConfig, coop_detector=None):
        self.cfg = cfg
        self.bot = None
        self.my_seat: int | None = None
        self.pending: str | None = None       # bot 最近一次触发的 mjai 动作 JSON
        # validate 端点：end_game 后还会发 validation_result（要等它，不能先断）；
        # ranked：end_game 即收工 → 断开重连（重新排队）。
        self.is_validate = "validate" in cfg.url
        # coop_detector(client) -> third_pid|None（默认 None＝纯自己 EV）。
        # riichi.dev 无玩家身份 → 需侧信道实现，见 README。
        self.coop_detector = coop_detector
        self._build_engine()

    def log(self, msg: str) -> None:
        sys.stderr.write(f"[{self.cfg.my_name}] {msg}\n")
        sys.stderr.flush()

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
        self.evcalc = EvCalc3P(self.bot_cfg)   # 模型 + trans_core 只载一次
        self.log(f"引擎就绪 ckpt={self.cfg.qgrp_ckpt} device={self.cfg.device}")

    # ── 开局：定座位 + 重建 bot + 协作判定 ─────────────────────
    def _on_start_game(self, ev: dict) -> None:
        seat = ev.get("id")
        self.my_seat = int(seat) if seat is not None else 0
        self.pending = None
        self.bot = self._QgrpBot3P(self.my_seat, self.bot_cfg, evcalc=self.evcalc)
        third = None
        if self.coop_detector is not None:
            try:
                third = self.coop_detector(self)
            except Exception:  # noqa: BLE001
                self.log("coop_detector 异常：\n" + traceback.format_exc())
        if third is not None:
            self.evcalc.set_coop(int(third), self.cfg.coop_w_self, self.cfg.coop_w_third)
            self.log(f"[coop ON] seat={self.my_seat} third_seat={third} "
                     f"w=(self {self.cfg.coop_w_self}, third {self.cfg.coop_w_third})")
        else:
            self.evcalc.clear_coop()
            self.log(f"[coop OFF] seat={self.my_seat}（纯自己 EV）")

    # ── 喂一个 mjai 事件给 bot（跟踪状态 + 缓存动作）────────────
    def _feed(self, ev: dict) -> None:
        ev = _dialect_in(ev)
        if ev.get("type") == "start_game":
            self._on_start_game(ev)
        if self.bot is None:
            return
        try:
            r = self.bot.react(json.dumps(ev, separators=(",", ":")))
        except Exception:  # noqa: BLE001
            self.log("react 异常：\n" + traceback.format_exc())
            r = None
        if r:
            self.pending = r

    # ── request_action → 一条动作 JSON（补 request_id + 合法兜底）─
    def _on_request_action(self, ev: dict) -> str:
        if self.pending:
            act = json.loads(self.pending)
            act.pop("meta", None)
        else:
            act = {"type": "none"}
        self.pending = None
        act = _dialect_out(act, self.cfg.nukidora_out)
        act = self._sanitize(act, ev.get("possible_actions") or [])
        act["request_id"] = ev.get("request_id")
        if act.get("type") != "none" and "actor" not in act and self.my_seat is not None:
            act["actor"] = self.my_seat
        return json.dumps(act, separators=(",", ":"))

    @staticmethod
    def _match(act: dict, p: dict) -> bool:
        if p.get("type") != act.get("type"):
            return False
        t = act.get("type")
        if t == "dahai":
            return p.get("pai") == act.get("pai")
        if t in ("pon", "chi", "daiminkan", "kakan", "ankan", "kan", "kita"):
            return (p.get("pai") == act.get("pai")
                    and sorted(p.get("consumed", [])) == sorted(act.get("consumed", [])))
        return True   # reach / hora / none / ryukyoku 等按类型唯一

    def _sanitize(self, act: dict, pas: list) -> dict:
        """确保动作在服务器合法集内，否则回退（none>dahai>pas[0]）防 chombo。"""
        if not pas:
            return act
        if any(self._match(act, p) for p in pas):
            return act
        self.log(f"WARN 动作不在合法集，回退：act={act} "
                 f"legal_types={[p.get('type') for p in pas]}")
        for p in pas:
            if p.get("type") == "none":
                return dict(p)
        for p in pas:
            if p.get("type") == "dahai":
                return dict(p)
        return dict(pas[0])

    # ── 单帧分派 ────────────────────────────────────────────
    def handle_frame(self, ev: dict) -> tuple[str | None, str | None]:
        et = ev.get("type")
        if et == "request_action":
            return self._on_request_action(ev), None
        if et == "validation_result":
            self.log(f"validation_result: {json.dumps(ev, ensure_ascii=False)[:300]}")
            return None, "validation_result"
        if et == "end_game":
            self.log(f"end_game: {json.dumps(ev, ensure_ascii=False)[:300]}")
            self.pending = None
            # validate 下不作终止（等 validation_result）；ranked 下终止→重连
            return None, (None if self.is_validate else "end_game")
        if et == "error":
            self.log(f"server error: {json.dumps(ev, ensure_ascii=False)[:300]}")
            return None, None
        if et == "action_ack":
            if ev.get("status") not in (None, "accepted"):
                self.log(f"action_ack 非 accepted：{ev}")
            return None, None
        self._feed(ev)   # 其余＝mjai 事件
        return None, None

    # ── 单次连接生命周期 ────────────────────────────────────
    async def _run_once(self) -> str:
        from websockets.asyncio.client import connect
        headers = {"Authorization": f"Bearer {self.cfg.jwt}"}
        async with connect(self.cfg.url, additional_headers=headers,
                            ping_interval=self.cfg.ping_interval,
                            max_size=None) as ws:
            self.log(f"已连接 {self.cfg.url}")
            async for msg in ws:
                if isinstance(msg, bytes):
                    continue
                try:
                    data = json.loads(msg)
                except (json.JSONDecodeError, TypeError):
                    self.log(f"非 JSON 帧，忽略：{str(msg)[:200]!r}")
                    continue
                frames = data if isinstance(data, list) else [data]
                for f in frames:
                    if not isinstance(f, dict):
                        continue
                    out, control = self.handle_frame(f)
                    if out is not None:
                        await ws.send(out)
                    if control in _TERMINAL:
                        return control
            return "closed"

    async def run(self) -> None:
        while True:
            try:
                result = await self._run_once()
            except Exception as e:  # noqa: BLE001
                self.log(f"连接异常：{e!r}")
                result = "error"
            if result == "validation_result" or not self.cfg.reconnect:
                self.log(f"结束（{result}），不再重连")
                break
            self.log(f"{result} → {self.cfg.reconnect_sec}s 后重连（重新排队）…")
            await asyncio.sleep(self.cfg.reconnect_sec)


def build_config(argv=None) -> ClientConfig:
    ap = argparse.ArgumentParser(description="qgrp3p riichi.dev 在线对战客户端")
    ap.add_argument("--url", default=os.environ.get(
        "RIICHI_WS_URL", "wss://game.riichi.dev/ws/validate"),
        help="平台 WebSocket 地址（默认 validate；上线用 .../ws/ranked）")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--bot-name", help="从 --tokens-file 按名取 JWT（Nosam/Mason）")
    g.add_argument("--jwt", help="直接给 JWT")
    ap.add_argument("--tokens-file", default=str(_REPO_ROOT / "riichi.md"))
    ap.add_argument("--qgrp-ckpt", default=os.environ.get(
        "QGRP3P_CKPT", "/root/qgrp3p_run/qgrp3p_v3_ftb50k.pth"))
    ap.add_argument("--trans-ckpt", default=os.environ.get(
        "QGRP3P_TRANS", "/root/zeroppo-grp/grp_trans3p_v1.pth"))
    ap.add_argument("--transcore-repo", default=os.environ.get(
        "QGRP3P_TRANSCORE_REPO", "/root/zeroppo-grp"))
    ap.add_argument("--device", default=os.environ.get("QGRP3P_DEVICE", "cuda"))
    ap.add_argument("--coop-w-self", type=float, default=0.5)
    ap.add_argument("--coop-w-third", type=float, default=0.5)
    ap.add_argument("--nukidora-out", choices=["kita", "nukidora"], default="kita")
    ap.add_argument("--no-reconnect", action="store_true")
    ap.add_argument("--reconnect-sec", type=float, default=3.0)
    args = ap.parse_args(argv)

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
        qgrp_ckpt=args.qgrp_ckpt, trans_ckpt=args.trans_ckpt,
        transcore_repo=args.transcore_repo, device=args.device,
        coop_w_self=args.coop_w_self, coop_w_third=args.coop_w_third,
        nukidora_out=args.nukidora_out,
        reconnect=not args.no_reconnect, reconnect_sec=args.reconnect_sec)


def main(argv=None) -> None:
    cfg = build_config(argv)
    try:
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
