# change-003 —— qgrp v3 接入在线三麻对战（标准 MJAI over WebSocket）+ 双 bot 协作

> 用户任务（2026-07-14）：把 `../qgrp` 的 v3 打牌器接进 riichienv 在线对战（3 人麻将）。
> 权重在 gpu16b `~/qgrp3p_run`；两个平台 bot（Nosam / Mason）的 JWT 在仓根 `riichi.md`。
> 协作规则：两 bot **未同桌**→最大化自己 EV；**同桌**→「最小化第三家 EV」与「最大化
> 自己 EV」各占一半权重。

## 结论（决策，用户已拍板）
- **平台协议 = 标准 MJAI over WebSocket**（= mjai.app / akagi 约定：batch 数组进 /
  单 reaction 出 / `start_game.id`+`names` / `end_game` 收尾）。真实 endpoint/鉴权位置/
  消息信封/配桌握手边测边调（全做成 CLI/env 旋钮）。
- **权重** = `qgrp3p_v3_ftb50k.pth`（v3 + B 微调，ce B +0.6826、n3000 电池 2.075）。
- **协作目标（每个 bot）**：同桌时 `EV_used = 0.5·自己 pt_EV + 0.5·(−第三家 pt_EV)`。
  rank-pt `[90,0,−90]` 零和下等价「自己 EV + 0.5·队友 EV」。

## 架构
- **进程内**：`online3p/client.py` 与 qgrp `bot3p` 同进程（gpu16b **aigc venv**：
  torch/libriichi3p/websockets），`import QgrpBot3P` 直接驱动；模型 + trans_core 只载一次
  （`EvCalc3P` 跨 game 复用，run_stdio renew 同款）。每个 bot 一个进程、各自 JWT/WS 连接。
- **接入点 = MJAI 层**：WS 收到的 batch 逐事件喂 `bot.react()`，回一条动作——就是 qgrp
  `run_stdio` 默认 batch 协议搬到 WebSocket。
- **方言归客户端**：平台线 `kita` ↔ bot 侧 `nukidora`，进站 `kita→nukidora` / 出站
  `nukidora→kita`（`--nukidora-out` 控）。
- **同桌判定**：每个 bot 从 `start_game.names` 独立判断队友（另一我方 bot 名）是否在桌、
  定位第三家座位 → `evcalc.set_coop(third_pid, w_self, w_third)`；否则 `clear_coop()`。
  **无侧信道**（两 bot 看同一 names 各自得出一致结论）。

## 协作 EV 实现（qgrp `bot3p/ev.py`，additive、默认关）
`EvCalc3P.start_kyoku` 里每个终局叶对**所有座位**都有确定名次/素点映射
（`perms[:,pid]` + `A/B/C_rot[...,pid]`）。改动：
- 加 `set_coop(third_pid, w_self=.5, w_third=.5)` / `clear_coop()`。
- `start_kyoku` 重构：续局叶的 6 排列名次分布 `p6` 与 pid 无关 → 提出来两家共用一次 `f̂`
  前向；`_rank_pt(pid)` / `_delta_pt(pid)` 闭包按座算 pt。
- `coop_third_pid is None` → `leaf_pt = 自家 pt`（**逐位与原行为不变**）；否则
  `leaf_pt = w_self·自家 − w_third·第三家`（第三家只计名次+素点，不含自家 bonus）。
- 下游 `ev_from_heads`（`w @ self.leaf_pt`）一行不改 ⇒ 协作 = 每小局换一次 `leaf_pt` 向量，
  零额外前向。

## 产物（本仓 `online3p/`）
- `client.py`（上线入口）/ `tokens.py` / `mock_server.py`（RiichiEnv-over-WS mock 平台，
  测试工具，用**仓库 .venv**）/ `test_coop_ev.py` / `_smoke_driver.sh` / `README.md`。
- qgrp `bot3p/ev.py` 加协作模式（见上；本仓无法 vendor，改在 `../qgrp` 并同步 gpu16b `/root/qgrp`）。
- `.gitignore`：`riichi.md`（凭证）、`online3p/_smoke/`（冒烟产物）。

## DoD 与验证（2026-07-14 全绿）
- [x] 协作 `leaf_pt` 数值核验（`test_coop_ev.py`，gpu16b cpu）：coop == `0.5·self−0.5·third`
      `max|err|=0`；权重 0.7/0.3+素点 `max|err|=0`；`clear_coop` 逐位回自家 `max|err|=0`；
      coop 与自家显著不同（`max|diff|=45`）。
- [x] 端到端 mock 冒烟（RiichiEnv-over-WS + 真实 Nosam/Mason + dummy 第三家，1 半庄）：
      两 bot 均 `coop ON` 正确定位第三家=dummy 座位、186 步整半庄零 select 失配、
      终局 scores/ranks 合法（两队友合计 107900、第三家 −2900 垫底）。
- [x] coop OFF 分支：单 Nosam + 2 dummy → `coop OFF`（队友不在桌），394 步整半庄合法。
- [ ] **真实平台**：等用户给 WS endpoint + 确认鉴权位置/消息信封/配桌握手（见 README「上线待对齐」），
      连真平台跑通、观察线上 coop 触发与胜负。

## 续点（下次接手）
1. 拿到平台 endpoint → `--url` 起 Nosam/Mason 两进程；按线上首包调 `--auth-mode`/
   `--hello-msg`/信封解包/`--nukidora-out`。
2. 线上先各自 solo 跑几局确认协议不失步，再让两 bot 进同一队列验证 coop 触发（看客户端
   `[coop ON]` 日志 + 第三家被压制）。
3. 若平台 batch 粒度/none 语义与假设不符（例：只在本座回合才要回复），调 `client.py`
   `handle_batch`/`_run_once` 的回复策略。
