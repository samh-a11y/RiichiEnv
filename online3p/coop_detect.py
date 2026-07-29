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


# ── 时间+内容双判据（用户裁定 2026-07-28，现役）────────────────────────
#
# 公开指纹那套的致命弱点：开局 E1 全 35000 / oya=0 / honba=kyotaku=0 时，指纹里唯一
# 有区分力的只剩 dora_marker（约 1/34 撞上）。2026-07-28 实测就撞了——两 bot 各在
# 一桌，Nosam 在首小局误判同桌并锁存整局，全程按「0.5·自己 − 0.5·第三家」压制一个
# 与它无关的真人；同时因为命中后不再 announce，队友永远读不到它、恒为 coop OFF。
#
# 新判据用的是**同桌的物理必然性**：同一个服务器进程把同一串公开事件广播给三家。于是
# 两个本机 bot 的「公开事件序列」必然逐条相同（实测整局 730/730、699/699 全同）。
# 判别力主要来自**连续公共段长度**——真实 log 实测：同桌前 12 条即全对，而不同桌的两局
# 整局最长只能凑出 7 条连续相同、前 12 条内只有 1–3 条。时间只做两件次要的事：
# start_game 时刻差粗筛（进入游戏的时间差）+ 偏移一致性（防历史 log 撞车）。
#
# ⚠ 时间**不能**用来逐条配对：客户端同步阻塞，`bot.react()` 推理期间不读 WS，帧接收
# 时刻被自己的 GPU 耗时污染（同一条事件两 bot 实测差 0.3–0.5s 且方向不定）。第一版按
# 「绝对时刻最近」配对并要求零冲突，在**真同桌**样本上得到 match=10 / mismatch=46，
# 被自己的否决条件拒掉（假阴）。

_PRIVATE_KEYS = frozenset({
    "tehais",            # start_kyoku 的三家手牌：只有自家那份是真的
    "possible_actions", "observation", "request_id", "time", "bank",
    "elapsed_ms", "id",  # id = start_game 的座位号（两 bot 必然不同）
    "meta",
})


def public_digest(ev: dict) -> str:
    """mjai 事件 → **座位无关的公开内容**摘要（同桌两客户端必然逐条相同）。

    要抹掉的是「因视角而异」的部分，否则同桌也对不上：
      · tsumo 只留 actor —— 自家摸牌的 pai 是私有的，他家的已被服务器隐藏成 '?'；
      · start_kyoku 去掉 tehais（只有自家那份是真牌）；
      · start_game 去掉 id（座位号），只留类型。
    dahai / pon / kan / reach / nukidora / hora / dora / ryukyoku / end_kyoku 等
    本就是公开广播，原样进摘要。
    """
    t = ev.get("type")
    if t == "tsumo":
        d = {"type": t, "actor": ev.get("actor")}
    else:
        d = {k: v for k, v in ev.items() if k not in _PRIVATE_KEYS}
    return json.dumps(d, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


class TimingCoop:
    """同桌检测：进入游戏时间差粗筛 + 公开事件流「内容连续段 × 时间偏移一致」确认。

    判据（四条全过才认同桌，命中即开、不等下一小局）：
      ① `start_game` 接收时刻差 < `sg_gate`（默认 5s）——进入游戏的时间差粗筛；
      ② 两边公开事件序列存在**连续公共段** ≥ `min_run` 条（默认 8）。判别力主要在
         这里：连续 8 条一模一样的公开事件（含具体打了哪张、谁碰了什么）在两桌独立
         对局里凑不出来——真实 log 实测不同桌整局最长公共段只有 7 条、前 12 条内 1–3 条，
         而同桌前 12 条即全对；
      ③ 该段配对的时间差**同期且一致**：|median(Δt)| < `offset_gate`（默认 5s）且
         90 分位抖动 < `spread_gate`（默认 2s）——不要求时刻接近，只要求偏移一致；
      ④ 座位不同 ⇒ 第三家 = `{0,1,2}` 剩下那个。

    判据的真实 log 验证见 `verify_coop_timing.py`（2026-07-28：3×3 局交叉，2 对真同桌
    全部命中、7 对不同桌全部拒绝，0 假阳 0 假阴）。假阳的代价远大于假阴——假阳会让 bot
    对一个无关真人做协作压制、白扔自己的 EV；假阴只是少赚。故 `min_run` 宁大勿小。
    """

    def __init__(self, share_dir: str, my_name: str, teammates,
                 ttl_sec: float = 120.0, sg_gate: float = 5.0,
                 min_run: int = 8, offset_gate: float = 5.0,
                 spread_gate: float = 2.0, keep: int = 120):
        self.dir = pathlib.Path(share_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.my_name = my_name
        self.teammates = frozenset(teammates)
        self.ttl = ttl_sec
        self.sg_gate = float(sg_gate)
        self.min_run = int(min_run)
        self.offset_gate = float(offset_gate)
        self.spread_gate = float(spread_gate)
        self.keep = int(keep)
        self.my_file = self.dir / f"{my_name}.timing.json"

    # ── 侧信道读写 ───────────────────────────────────────────
    def announce(self, seat: int, t_start_game: float | None,
                 feats: list) -> None:
        payload = {"name": self.my_name, "seat": int(seat),
                   "t_start_game": t_start_game,
                   "feats": [[round(float(t), 4), d]
                             for t, d in list(feats)[-self.keep:]],
                   "ts": time.time()}
        tmp = self.my_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.my_file)      # 原子替换，避免读到半写

    def _peers(self):
        now = time.time()
        for f in self.dir.glob("*.timing.json"):
            if f.name == self.my_file.name:
                continue
            try:
                peer = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if (peer.get("name") in self.teammates
                    and peer.get("name") != self.my_name
                    and (now - float(peer.get("ts", 0))) < self.ttl):
                yield peer

    # ── 判据 ────────────────────────────────────────────────
    @staticmethod
    def longest_run(mine: list, peer_feats: list) -> tuple[int, int, int]:
        """两条公开事件序列的**最长连续公共段** → (长度, mine 起点, peer 起点)。

        O(n·m) DP，n/m ≤ keep（120）⇒ 最坏 1.4 万格，决策点上跑得起。
        """
        A = [d for _, d in mine]
        B = [d for _, d in peer_feats]
        best = (0, 0, 0)
        if not A or not B:
            return best
        prev = [0] * (len(B) + 1)
        for i, a in enumerate(A, 1):
            cur = [0] * (len(B) + 1)
            for j, b in enumerate(B, 1):
                if a == b:
                    cur[j] = prev[j - 1] + 1
                    if cur[j] > best[0]:
                        best = (cur[j], i - cur[j], j - cur[j])
            prev = cur
        return best

    def check(self, mine: list, peer_feats: list) -> tuple[bool, dict]:
        """判据②③：连续公共段够长 + 段内时间偏移「同期且一致」。→ (是否通过, 明细)。

        统计量用**中位数 + 90 分位绝对偏差**，不用均值/极差：同步阻塞的客户端偶尔会
        有一帧被推理拖住（实测某帧偏 +1.0s，其余稳定在 −0.26s），极差会被这种离群值
        顶到 3s 以上，在**真同桌**样本上造成假阴。
          · `offset` = median(Δt)：两客户端的系统性偏移，用来确认「两局是同期进行的」
            （防历史 log 撞车），门槛宽（`offset_gate`，默认 5s）；
          · `jitter` = 90 分位 |Δt − offset|：偏移的一致性，门槛紧（`spread_gate`，
            默认 2s）。
        真正的判别力仍在 `run` 上——连续 N 条公开事件（含具体牌）全同即同桌。
        """
        L, ia, ib = self.longest_run(mine, peer_feats)
        info = {"run": L}
        if L < self.min_run:
            return False, info
        dts = sorted(float(mine[ia + k][0]) - float(peer_feats[ib + k][0])
                     for k in range(L))
        med = dts[len(dts) // 2]
        devs = sorted(abs(d - med) for d in dts)
        jitter = devs[min(len(devs) - 1, int(0.9 * len(devs)))]
        info.update(offset=round(med, 3), jitter=round(jitter, 3))
        return (abs(med) < self.offset_gate
                and jitter < self.spread_gate), info

    def detect(self, my_seat: int, t_start_game: float | None,
               feats: list) -> tuple[int, dict] | None:
        """announce 自己 → 查队友。同桌返回 (第三家绝对座位, 判据明细)，否则 None。"""
        self.announce(my_seat, t_start_game, feats)
        mine = [[float(t), d] for t, d in list(feats)[-self.keep:]]
        for peer in self._peers():
            info = {"peer": peer.get("name"), "peer_seat": peer.get("seat")}
            if peer.get("seat") == my_seat:                   # 判据④
                continue
            t_peer = peer.get("t_start_game")
            if t_start_game is None or t_peer is None:
                continue
            dsg = abs(float(t_start_game) - float(t_peer))
            info["dt_start_game"] = round(dsg, 3)
            if dsg >= self.sg_gate:                           # 判据①
                continue
            ok, det = self.check(mine, peer.get("feats") or [])
            info.update(det)
            if not ok:                                        # 判据②③
                continue
            seats = {0, 1, 2} - {int(my_seat), int(peer["seat"])}
            if len(seats) != 1:
                continue
            return seats.pop(), info
        return None
