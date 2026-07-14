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
import base64
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


# 红宝牌 aka 归一化：riichi.dev 的 `possible_actions` **把红5折叠成普通5**（红5筒显示为
# 5p、红5索显示为 5s，实测同一局合法集里红/非红 5p 都写 "5p"），但服务器真正的校验器
# (riichienv-core mjai_select.rs::select_action) 按 `tid_to_mjai(tile)` 是 **aka 敏感**的、
# 照收 5pr/5sr（validate 实测发 5pr/5sr → action_ack=accepted）。⇒ `_match` 比对 pai/
# consumed 时按普通5归一化即可命中合法集，命中后 `_sanitize` **原样发 bot 的 5pr**——
# 服务器自行区分红/非红。不做归一化则 bot 想切/摸切红5时被误判非法、回退成别的牌
# （表现＝"模型不认识红5"）。只影响 5m/5p/5s，其余牌名恒等。三麻实际只有 5pr/5sr。
_AKA2PLAIN = {"5mr": "5m", "5pr": "5p", "5sr": "5s"}


def _deaka(pai):
    return _AKA2PLAIN.get(pai, pai) if isinstance(pai, str) else pai


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
    # 剥削旋钮（aux 水平/激进度条件，train-003 §2；三家同值＝告诉模型对手 profile，模型
    # 针对性调整打法）。None＝用 BotConfig3P 默认（自产谱口径 level=8.0/aggr=12.0）。
    level: float | None = None
    aggr: float | None = None
    nukidora_out: str = "kita"
    reconnect: bool = True
    reconnect_sec: float = 0.0        # 正常 end_game 后重连（重新排队）延迟——默认 0=立即
    reconnect_backoff_sec: float = 3.0  # 异常/断线后重连退避（≠正常 end_game），防 0s 猛捶服务器
    ping_interval: float = 20.0
    # 侧信道协作（**默认开**＝核心测试；--no-coop 关。只传"是否同桌"的公开局面指纹，
    # 不传任何私有手牌信息，每 bot 仍只用自己观测独立优化 0.5·self−0.5·third）
    coop_enabled: bool = True
    coop_dir: str = "/tmp/riichi_coop"
    teammates: tuple = ("Nosam", "Mason")
    coop_wait_sec: float = 3.0     # 同桌握手轮询上限（覆盖两进程到达时间差）
    # 优雅停机：stop_file 出现 或 收到 SIGTERM/SIGINT → **打完当前对局**后退出（不中断进行中对局）
    stop_file: str = "/tmp/riichi_coop/STOP"


class OnlineMjaiClient:
    def __init__(self, cfg: ClientConfig, coop=None):
        self.cfg = cfg
        self.bot = None
        self.my_seat: int | None = None
        self.pending: str | None = None       # bot 最近一次触发的 mjai 动作 JSON
        # validate 端点：end_game 后还会发 validation_result（要等它，不能先断）；
        # ranked：end_game 即收工 → 断开重连（重新排队）。
        self.is_validate = "validate" in cfg.url
        # 侧信道同桌检测器（coop_detect.FileFingerprintCoop）或 None＝纯自己 EV。
        # riichi.dev 无玩家身份 ⇒ 只能靠侧信道（两 bot 本机进程），见 coop_detect.py。
        self.coop = coop
        # 同桌＝整局属性：用整局不变的对局指纹（首小局 E1）匹配，每小局重查直到命中并锁存
        # （不早锁 solo；即便首局两进程错开，次局瞬时重读也能命中）。
        self._coop_third: int | None = None
        self._game_fp: str | None = None
        self._coop_attempts = 0
        # 优雅停机：收到信号/停机文件后，打完当前对局才退（不中断进行中对局）
        self._stop = False
        self._in_game = False
        # 只读诊断：RIICHI_RAW_LOG=<path> 时把每一帧原始 recv/send 落盘（含 request_action
        # 里 base64 observation 的解码），用于核对平台真实线格式（如红5=5pr 还是 5p）。
        # **不改任何决策/匹配逻辑**；默认关（env 未设即完全 no-op）。
        self._raw_path = os.environ.get("RIICHI_RAW_LOG") or None
        self._raw_n = 0
        self._build_engine()

    def _raw(self, direction: str, frame) -> None:
        """把一帧原样落盘（诊断用）；request_action 的 base64 observation 解码后并记。
        绝不抛出（异常吞掉），绝不影响对局主循环。"""
        if not self._raw_path:
            return
        try:
            rec = {"n": self._raw_n, "dir": direction, "seat": self.my_seat,
                   "frame": frame}
            if isinstance(frame, dict) and frame.get("type") == "request_action":
                obs_b64 = frame.get("observation")
                if isinstance(obs_b64, str):
                    rec = dict(rec)
                    f2 = dict(frame)
                    try:
                        f2["observation"] = json.loads(base64.b64decode(obs_b64))
                    except Exception:  # noqa: BLE001
                        f2["observation"] = f"<b64 decode failed len={len(obs_b64)}>"
                    rec["frame"] = f2
            with open(self._raw_path, "a", encoding="utf-8") as fp:
                fp.write(json.dumps(rec, ensure_ascii=False,
                                    separators=(",", ":")) + "\n")
            self._raw_n += 1
        except Exception:  # noqa: BLE001
            pass

    def _request_stop(self) -> None:
        if not self._stop:
            self._stop = True
            self.log("收到停机信号 → 打完当前对局后退出（不中断本局）")

    def _should_stop(self) -> bool:
        if self._stop:
            return True
        sf = self.cfg.stop_file
        return bool(sf) and os.path.exists(sf)

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
        cfg_kw = dict(
            qgrp_ckpt=self.cfg.qgrp_ckpt, trans_ckpt=self.cfg.trans_ckpt,
            transcore_repo=self.cfg.transcore_repo, device=self.cfg.device,
            name=self.cfg.my_name)
        # 未指定＝走 BotConfig3P 默认（单一真源，不在此硬编码 8.0/12.0）
        if self.cfg.level is not None:
            cfg_kw["level"] = self.cfg.level
        if self.cfg.aggr is not None:
            cfg_kw["aggr"] = self.cfg.aggr
        self.bot_cfg = BotConfig3P(**cfg_kw)
        self.evcalc = EvCalc3P(self.bot_cfg)   # 模型 + trans_core 只载一次
        self.log(f"引擎就绪 ckpt={self.cfg.qgrp_ckpt} device={self.cfg.device} "
                 f"level={self.bot_cfg.level} aggr={self.bot_cfg.aggr}（剥削旋钮）")

    # ── 开局：定座位 + 重建 bot（协作在 start_kyoku 判定）─────────
    def _on_start_game(self, ev: dict) -> None:
        seat = ev.get("id")
        self.my_seat = int(seat) if seat is not None else 0
        self.pending = None
        self.bot = self._QgrpBot3P(self.my_seat, self.bot_cfg, evcalc=self.evcalc)
        self.evcalc.clear_coop()   # 新局先复位；同桌与否在 start_kyoku 定
        self._coop_third = None    # 每局重置：同桌判定基于本局指纹
        self._game_fp = None
        self._coop_attempts = 0
        self._in_game = True       # 进行中对局：优雅停机须打完它
        self.log(f"start_game seat={self.my_seat} coop={'侧信道' if self.coop else '关'}")

    # ── 每小局开局：侧信道判同桌（用整局不变指纹，重查直到命中）→ set/clear coop ──
    def _on_start_kyoku(self, ev: dict) -> None:
        if self.coop is None or self.my_seat is None:
            return
        from .coop_detect import fingerprint
        if self._game_fp is None:              # 首小局：锚定整局不变的对局指纹
            self._game_fp = fingerprint(ev)
        if self._coop_third is None:           # 尚未命中 → 刷新自己指纹并重查
            try:
                wait = self.cfg.coop_wait_sec if self._coop_attempts == 0 else 0.0
                third = self.coop.detect(self.my_seat, self._game_fp, wait=wait)
            except Exception:  # noqa: BLE001
                self.log("coop 检测异常：\n" + traceback.format_exc())
                third = None
            self._coop_attempts += 1
            if third is not None:
                self._coop_third = third
        kyoku = f"{ev.get('bakaze')}{ev.get('kyoku')}-{ev.get('honba')}"
        if self._coop_third is not None:
            self.evcalc.set_coop(self._coop_third, self.cfg.coop_w_self,
                                 self.cfg.coop_w_third)
            self.log(f"[coop ON] seat={self.my_seat} third_seat={self._coop_third} "
                     f"kyoku={kyoku}")
        else:
            self.evcalc.clear_coop()
            self.log(f"[coop OFF] seat={self.my_seat} kyoku={kyoku}（暂未匹配到队友）")

    # ── 喂一个 mjai 事件给 bot（跟踪状态 + 缓存动作）────────────
    def _feed(self, ev: dict) -> None:
        ev = _dialect_in(ev)
        et = ev.get("type")
        if et == "start_game":
            self._on_start_game(ev)
        elif et == "start_kyoku":
            self._on_start_kyoku(ev)   # 协作判定须在喂 bot（→evcalc.start_kyoku）前
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
        # 镜像服务器 select_action（riichienv-core observation/mjai_select.rs）的接受逻辑，
        # 否则合法动作会被兜底误判非法而回退。
        if p.get("type") != act.get("type"):
            return False
        t = act.get("type")
        if t == "dahai":
            # aka 归一化（仅 dahai，已 validate 实测证据确凿）：possible_actions 把红5折叠成
            # 普通5（同一局合法集里红5筒/非红5筒都写 "5p"），但服务器校验器 aka 敏感、照收
            # 5pr/5sr（实测发 5pr/5sr→action_ack=accepted）。归一化命中后 _sanitize 原样发
            # bot 的 5pr，服务器自行区分红/非红。不归一化则 bot 切/摸切红5被误判非法→回退成
            # 别的牌（＝用户报的"模型不认识红5"）。melds 未观察到折叠、保持严格（下方）。
            return _deaka(p.get("pai")) == _deaka(act.get("pai"))
        if t in ("pon", "chi", "daiminkan", "kakan", "ankan", "kan", "kita"):
            # consumed 唯一确定一次副露（含 aka）——服务器按 consumed 匹配。
            if sorted(p.get("consumed", [])) != sorted(act.get("consumed", [])):
                return False
            # pai 只对 chi/pon/daiminkan/kakan 二次校验（且需两侧都给）。ankan/kita 服务器
            # 不看 pai：服务器合法集里的 ankan 带「冗余」pai（Rust to_mjai 见 tile=Some 就插
            # pai），而标准 mjai / qgrp bot 的 ankan 不带 pai——旧逻辑一比 pai 就把每次暗杠
            # 误判非法→回退打牌（真机 Nosam 日志实证）。
            if t in ("pon", "chi", "daiminkan", "kakan") and p.get("pai") and act.get("pai"):
                return p.get("pai") == act.get("pai")
            return True
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
            self._in_game = False
            return None, "validation_result"
        if et == "end_game":
            self.log(f"end_game: {json.dumps(ev, ensure_ascii=False)[:300]}")
            self.pending = None
            self._in_game = False   # 本局打完（优雅停机的安全点）
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
            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                except asyncio.TimeoutError:
                    # 空闲（排队/局间）时轮询停机：无进行中对局才停，绝不中断本局
                    if self._should_stop() and not self._in_game:
                        return "stop"
                    continue
                except Exception:  # noqa: BLE001  连接关闭等
                    return "closed"
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
                    self._raw("recv", f)
                    out, control = self.handle_frame(f)
                    if out is not None:
                        self._raw("send", json.loads(out))
                        await ws.send(out)
                    if control in _TERMINAL:
                        # 本局打完；若已请求停机则不再重连
                        return "stop" if self._should_stop() else control

    async def run(self) -> None:
        import signal
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self._request_stop)
            except (NotImplementedError, ValueError):
                pass
        while True:
            if self._should_stop():
                self.log("停机（无进行中对局），退出"); break
            try:
                result = await self._run_once()
            except Exception as e:  # noqa: BLE001
                self.log(f"连接异常：{e!r}")
                result = "error"
            if result == "stop":
                self.log("已优雅停机：当前对局打完，退出"); break
            if result == "validation_result" or not self.cfg.reconnect:
                self.log(f"结束（{result}），不再重连"); break
            if self._should_stop():
                self.log("停机：当前对局已结束，不再重连"); break
            # 正常 end_game→立即重排（reconnect_sec，默认 0）；异常/断线→退避防猛捶
            delay = (self.cfg.reconnect_backoff_sec if result == "error"
                     else self.cfg.reconnect_sec)
            self.log(f"{result} → {delay}s 后重连（重新排队）…")
            if delay > 0:
                await asyncio.sleep(delay)


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
    # 剥削旋钮（aux 水平/激进度条件；三家同值＝对手 profile）。默认不覆盖＝BotConfig3P 默认 8.0/12.0
    ap.add_argument("--level", type=float, default=None,
                    help="aux 水平条件（剥削旋钮，train-003 §2；不给=默认 8.0=自产谱口径）")
    ap.add_argument("--aggr", type=float, default=None,
                    help="aux 激进度条件（同 --level；不给=默认 12.0）")
    ap.add_argument("--coop-w-self", type=float, default=0.5)
    ap.add_argument("--coop-w-third", type=float, default=0.5)
    ap.add_argument("--nukidora-out", choices=["kita", "nukidora"], default="kita")
    ap.add_argument("--no-reconnect", action="store_true")
    ap.add_argument("--reconnect-sec", type=float, default=0.0,
                    help="正常 end_game 后重连延迟秒（默认 0=立即重排）")
    ap.add_argument("--reconnect-backoff-sec", type=float, default=3.0,
                    help="异常/断线后重连退避秒（默认 3，防 0s 猛捶服务器）")
    # 侧信道协作（**默认开**）：同桌时 0.5·self−0.5·third；--no-coop 关＝纯自己 EV
    ap.add_argument("--no-coop", dest="coop_enabled", action="store_false",
                    default=True, help="关闭侧信道同桌检测（默认开）")
    ap.add_argument("--coop-dir", default="/tmp/riichi_coop",
                    help="两 bot 互认的共享目录")
    ap.add_argument("--teammates", default="Nosam,Mason", help="我方 bot 名集合")
    ap.add_argument("--coop-wait-sec", type=float, default=3.0)
    ap.add_argument("--stop-file", default="/tmp/riichi_coop/STOP",
                    help="该文件出现→打完当前对局后优雅退出（两 bot 同一文件＝同停）")
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
        level=args.level, aggr=args.aggr,
        nukidora_out=args.nukidora_out,
        reconnect=not args.no_reconnect, reconnect_sec=args.reconnect_sec,
        reconnect_backoff_sec=args.reconnect_backoff_sec,
        coop_enabled=args.coop_enabled, coop_dir=args.coop_dir,
        teammates=tuple(t.strip() for t in args.teammates.split(",")),
        coop_wait_sec=args.coop_wait_sec, stop_file=args.stop_file)


def main(argv=None) -> None:
    cfg = build_config(argv)
    try:
        import torch
        torch.set_num_threads(1)
    except Exception:  # noqa: BLE001
        pass
    coop = None
    if cfg.coop_enabled:
        from .coop_detect import FileFingerprintCoop
        coop = FileFingerprintCoop(cfg.coop_dir, cfg.my_name, cfg.teammates)
        sys.stderr.write(f"[{cfg.my_name}] 侧信道协作已开：dir={cfg.coop_dir} "
                         f"teammates={cfg.teammates}（仅传是否同桌，无手牌信息）\n")
    client = OnlineMjaiClient(cfg, coop=coop)
    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        client.log("Ctrl-C 退出")


if __name__ == "__main__":
    main()
