#!/usr/bin/env python3
"""侧信道同桌检测（change-003 协作触发）。

riichi.dev 协议不暴露玩家身份/对局 ID ⇒ 一个 bot 无法从协议判断队友是否同桌。
但两个我方 bot（Nosam/Mason）都是本机进程，可经共享目录互认：每局 start_kyoku 时各自把
**座位无关的公开局面指纹**（场风/局/本场/供托/亲/三家点数/宝牌指示——所有人所见一致）写文件，
短暂 settle 后读对方；若队友报了**相同指纹**且**座位不同**且**时间新鲜** ⇒ 同桌，
第三家 = 剩下那个座位。指纹碰撞极低（点数序列+宝牌+局数，两局独立对局同时同此几乎不可能；
仅开局 E1 全 35000 时靠宝牌指示区分，误配也只影响该局且下局自纠）。

⚠ 合规：在排位对他人 bot 用双账号协作压制第三家 = 合谋，启用（--coop）前请确认平台规则允许。
"""
from __future__ import annotations

import json
import pathlib
import time


def fingerprint(start_kyoku: dict) -> str:
    """start_kyoku 的座位无关公开指纹（不含 tehais＝本座手牌）。"""
    keys = ("bakaze", "kyoku", "honba", "kyotaku", "oya", "scores", "dora_marker")
    return json.dumps({k: start_kyoku.get(k) for k in keys},
                      sort_keys=True, ensure_ascii=False)


class FileFingerprintCoop:
    """共享目录指纹互认。每个 bot 一个 <dir>/<name>.json。"""

    def __init__(self, share_dir: str, my_name: str, teammates,
                 ttl_sec: float = 120.0, poll_sec: float = 0.25):
        self.dir = pathlib.Path(share_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.my_name = my_name
        self.teammates = frozenset(teammates)
        self.ttl = ttl_sec        # 对方 announce 的新鲜窗（一局几分钟，宽松取 120s）
        self.poll = poll_sec
        self.my_file = self.dir / f"{my_name}.json"

    def _write(self, seat: int, fp: str) -> None:
        payload = {"name": self.my_name, "seat": int(seat), "fp": fp,
                   "ts": time.time()}
        tmp = self.my_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(self.my_file)   # 原子替换，避免读到半写

    def _match_once(self, my_seat: int, fp: str) -> int | None:
        now = time.time()
        for f in self.dir.glob("*.json"):
            if f.name == self.my_file.name:
                continue
            try:
                peer = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if (peer.get("name") in self.teammates
                    and peer.get("name") != self.my_name
                    and peer.get("fp") == fp
                    and peer.get("seat") != my_seat
                    and (now - float(peer.get("ts", 0))) < self.ttl):
                seats = {0, 1, 2} - {int(my_seat), int(peer["seat"])}
                if len(seats) == 1:
                    return seats.pop()
        return None

    def detect(self, my_seat: int, fp: str, wait: float = 0.0) -> int | None:
        """刷新自己的（稳定对局）指纹 → 查队友；同桌返回第三家绝对座位，否则 None。
        fp 应为**整局不变**的对局指纹（首小局 E1 公开状态），调用方每小局重查直到匹配——
        即便某局两进程错开，下局瞬时重读也能命中（对方 announce 仍在 TTL 内）。
        wait>0 时轮询等待至多 wait 秒（首局用以加速常见的近同时场景）。"""
        self._write(my_seat, fp)
        deadline = time.time() + max(0.0, wait)
        while True:
            third = self._match_once(my_seat, fp)
            if third is not None:
                return third
            if time.time() >= deadline:
                return None
            time.sleep(self.poll)
