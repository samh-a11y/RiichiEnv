#!/usr/bin/env python3
"""RiichiEnv-backed WebSocket mock 平台（arena over WebSocket）——冒烟 online3p 客户端。

像真实平台一样对客户端：接受 WS 连接（Bearer JWT 或 ?token=，仅解码取 name 不验签），
按 join 顺序分座（前 --real 座给真实客户端，其余内置 dummy 补齐）；用 RiichiEnv
3p-red-half 天凤规则当裁判跑 --hanchan 半庄，向每个真实座推送其 ``new_events()``
（JSON 数组；**start_game 注入 id+names**，其余原样 = 原生 ``kita`` 方言），收回一条
reaction 交 ``obs.select_action_from_mjai``。收工给真实座发 ``end_game``。

⚠ 纯测试工具：不验签、单桌、顺序问询各座。真实平台协议以平台文档为准；此 mock 的
唯一职责是复刻「平台↔客户端」这段 wire 契约（batch 数组进 / 单 reaction 出 /
start_game 带 id+names / kita 方言 / end_game 收尾），好在没有平台时端到端验证客户端。

跑法（gpu16b，aigc venv 有 riichienv+websockets）：
    cd /root/riichienv
    /root/aigc_apps/venv/bin/python3 -m online3p.mock_server --host 127.0.0.1 --port 8899 --real 2 --hanchan 1
然后另起 Nosam / Mason 两个客户端连 ws://127.0.0.1:8899 。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from urllib.parse import parse_qs, urlparse

from .tokens import token_name


def _log(msg: str) -> None:
    sys.stderr.write(f"[mock] {msg}\n")
    sys.stderr.flush()


def _type_name(action_type) -> str:
    return str(action_type).split(".")[-1]


class MockTable:
    def __init__(self, n_real: int, seed: int, hanchan: int,
                 n_seats: int = 3, dummy_prefix: str = "DummyBot"):
        self.n_seats = n_seats
        self.n_real = min(n_real, n_seats)
        self.seed = seed
        self.hanchan = hanchan
        self.dummy_prefix = dummy_prefix
        self.seats: list = [None] * n_seats     # ws（真实座）或 None（dummy）
        self.names: list = [None] * n_seats
        self._n_reg = 0
        self.ready = asyncio.Event()
        self.done = asyncio.Event()
        self._lock = asyncio.Lock()

    # ── 连接注册 ────────────────────────────────────────────
    async def register(self, ws, name: str) -> int:
        async with self._lock:
            seat = self._n_reg
            self._n_reg += 1
            self.seats[seat] = ws
            self.names[seat] = name
            if self._n_reg >= self.n_real:
                for s in range(self.n_real, self.n_seats):
                    self.names[s] = f"{self.dummy_prefix}{s}"
                self.ready.set()
        return seat

    async def handler(self, ws):
        name = self._extract_name(ws) or "Anon"
        if self._n_reg >= self.n_real:
            _log(f"座位已满，拒绝 {name}")
            await ws.close()
            return
        seat = await self.register(ws, name)
        _log(f"seat {seat} = {name} 已连接（{self._n_reg}/{self.n_real}）")
        await self.done.wait()   # 保持连接直到整桌打完（game loop 直接读写此 ws）

    @staticmethod
    def _extract_name(ws):
        try:
            auth = ws.request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                if nm := token_name(auth[7:]):
                    return nm
            q = parse_qs(urlparse(ws.request.path).query)
            if "token" in q:
                if nm := token_name(q["token"][0]):
                    return nm
        except Exception:  # noqa: BLE001
            pass
        return None

    # ── 裁判（RiichiEnv）────────────────────────────────────
    async def run_game(self) -> None:
        try:
            await self._run_game_impl()
        except Exception:  # noqa: BLE001
            import traceback
            _log("run_game 异常：\n" + traceback.format_exc())
        finally:
            self.done.set()   # 无论成败都释放 handler，避免客户端悬挂

    async def _run_game_impl(self) -> None:
        await self.ready.wait()
        from riichienv import GameRule, RiichiEnv
        _log(f"开赛 names={self.names} seed0={self.seed} hanchan={self.hanchan}")
        for h in range(self.hanchan):
            env = RiichiEnv(game_mode="3p-red-half",
                            rule=GameRule.default_tenhou(), seed=self.seed + h)
            obs = env.reset(scores=[35000, 35000, 35000])
            _log(f"[hanchan {h}] reset ok，首 obs 座位={sorted(obs.keys())}")
            steps = 0
            while not env.done():
                acts = {}
                for pid, o in obs.items():
                    acts[pid] = await self._act(pid, o)
                obs = env.step(acts)
                steps += 1
                if steps % 50 == 0:
                    _log(f"[hanchan {h}] step {steps}…")
                if steps > 100000:
                    raise RuntimeError("step 上限保护（疑似死循环）")
            scores, ranks = env.scores(), env.ranks()
            _log(f"[hanchan {h}] 结束 steps={steps} scores={scores} ranks={ranks}")
        # 收尾：给真实座发 end_game 并读掉其回复
        for seat in range(self.n_real):
            ws = self.seats[seat]
            if ws is None:
                continue
            try:
                await ws.send(json.dumps([{"type": "end_game"}]))
                await asyncio.wait_for(ws.recv(), timeout=5)
            except Exception:  # noqa: BLE001
                pass
        _log("整桌结束")

    async def _act(self, pid: int, o):
        events = [json.loads(e) for e in o.new_events()]   # 原生 kita（客户端负责方言）
        for ev in events:                                   # 平台行为：start_game 注入 id+names
            if ev.get("type") == "start_game":
                ev["id"] = pid
                ev["names"] = list(self.names)
        ws = self.seats[pid] if pid < self.n_real else None
        if ws is None:
            return self._dummy_action(o)
        first = not getattr(self, "_acted", set()) or pid not in self._acted
        if first:
            self._acted = getattr(self, "_acted", set()) | {pid}
            _log(f"首次问询 seat {pid}（{self.names[pid]}）：发 {len(events)} 事件 "
                 f"types={[e.get('type') for e in events][:6]}…")
        await ws.send(json.dumps(events, separators=(",", ":")))
        resp = json.loads(await ws.recv())
        if first:
            _log(f"seat {pid} 首次回复 type={resp.get('type')}")
        if resp.get("type") == "none":
            return self._resolve_none(o)
        act = o.select_action_from_mjai(resp)   # resp 已是 kita（客户端转回）
        if act is None:
            legals = [_type_name(a.action_type) for a in o.legal_actions()]
            _log(f"WARN seat {pid} select 未匹配 resp={resp} legals={legals}")
            return self._resolve_none(o)
        return act

    def _resolve_none(self, o):
        a = o.select_action_from_mjai({"type": "none"})
        if a is not None:
            return a
        for la in o.legal_actions():
            if _type_name(la.action_type) == "PASS":
                return la
        legals = o.legal_actions()
        return legals[0] if legals else None

    def _dummy_action(self, o):
        a = o.select_action_from_mjai({"type": "none"})   # 响应窗优先 pass
        if a is not None:
            return a
        for la in o.legal_actions():                       # 自己回合优先打牌
            if _type_name(la.action_type) == "DAHAI":
                return la
        legals = o.legal_actions()
        return legals[0] if legals else None


async def _amain(args) -> None:
    from websockets.asyncio.server import serve
    table = MockTable(n_real=args.real, seed=args.seed, hanchan=args.hanchan)
    game_task = asyncio.create_task(table.run_game())
    async with serve(table.handler, args.host, args.port, max_size=None):
        _log(f"监听 ws://{args.host}:{args.port}  等待 {args.real} 个真实客户端…")
        await table.done.wait()
    try:
        await asyncio.wait_for(game_task, timeout=10)
    except Exception as e:  # noqa: BLE001
        _log(f"game_task 收束异常：{e!r}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="RiichiEnv-over-WebSocket mock 平台")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--real", type=int, default=2, help="等待的真实客户端数（其余座 dummy）")
    ap.add_argument("--hanchan", type=int, default=1)
    ap.add_argument("--seed", type=int, default=100)
    args = ap.parse_args(argv)
    asyncio.run(_amain(args))


if __name__ == "__main__":
    main()
