# change-003 —— qgrp v3 接入在线三麻对战（标准 MJAI over WebSocket）+ 双 bot 协作

> 用户任务（2026-07-14）：把 `../qgrp` 的 v3 打牌器接进 riichienv 在线对战（3 人麻将）。
> 权重在 gpu16b `~/qgrp3p_run`；两个平台 bot（Nosam / Mason）的 JWT 在仓根 `riichi.md`。
> 协作规则：两 bot **未同桌**→最大化自己 EV；**同桌**→「最小化第三家 EV」与「最大化
> 自己 EV」各占一半权重。

## 结论（决策 + 真实协议实测）
- **平台 = riichi.dev / RiichiLab**，真实协议（探针 `/ws/validate` 实测，非先前假设的
  mjai.app batch）：`wss://game.riichi.dev/ws/{validate,ranked}` + `Authorization: Bearer`；
  **每帧单个 JSON 对象**，服务器逐帧下发 mjai 事件，bot **只对 `request_action` 回**且
  **回显 `request_id`**；`request_action` 带 `possible_actions`（防 chombo 兜底）+ base64
  `observation`（本客户端不用）；`start_game` **只有座位 `id`，无 names/身份/game_id**；
  `end_game` 后 validate 发 `validation_result`、ranked 断开重连；拔北 = `kita`；
  非法/超时 = chombo（満貫罚）。文档：riichi.dev/docs/{protocol,validation,local-testing}。
- **权重** = `qgrp3p_v3_ftb50k.pth`（v3 + B 微调，ce B +0.6826、n3000 电池 2.075）。
- **协作目标（每个 bot）**：同桌时 `EV_used = 0.5·自己 pt_EV + 0.5·(−第三家 pt_EV)`。
  rank-pt `[90,0,−90]` 零和下等价「自己 EV + 0.5·队友 EV」。**但平台无玩家身份/game_id ⇒
  无法从协议判定同桌**（详见 DoD/续点）。

## 架构
- **进程内**：`online3p/client.py` 与 qgrp `bot3p` 同进程（gpu16b **aigc venv**：
  torch/libriichi3p/websockets），`import QgrpBot3P` 直接驱动；模型 + trans_core 只载一次
  （`EvCalc3P` 跨 game 复用，run_stdio renew 同款）。每个 bot 一个进程、各自 JWT/WS 连接。
- **接入点 = MJAI 层**：逐帧 mjai 事件喂 `bot.react()` 跟踪状态 + 缓存触发的动作，
  `request_action` 到达时发缓存动作 + 补 `request_id`；`possible_actions` 做合法性兜底
  防 chombo。**不需要 riichienv 包**（纯 MJAI 桥；observation 忽略）。
- **方言归客户端**：平台线 `kita` ↔ bot 侧 `nukidora`，进站 `kita→nukidora` / 出站
  `nukidora→kita`（`--nukidora-out` 控）。
- **同桌判定**：平台无玩家身份/game_id ⇒ 无法从协议判定。`coop_detector` 钩子默认 None＝
  纯自己 EV。侧信道方案见续点 2。

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

## DoD 与验证
- [x] 协作 `leaf_pt` 数值核验（`test_coop_ev.py`，gpu16b）：coop == `0.5·self−0.5·third`
      `max|err|=0`；权重 0.7/0.3+素点 `max|err|=0`；`clear_coop` 逐位回自家 `max|err|=0`。
- [x] **真机验证通过（2026-07-14）**：Nosam / Mason 各连 `wss://game.riichi.dev/ws/validate`，
      qgrp v3 打完整局三麻、零 chombo/掉线、零 react 异常、零 sanitize 回退 →
      `validation_result: {"passed": true}`（两 bot 均过）。日志 `online3p/_smoke/val_{nosam,mason}.log`。
- [ ] **ranked 上线**：`--url wss://game.riichi.dev/ws/ranked` 起两进程持续排位（solo 自己 EV）。
- [ ] **协作触发**：平台无玩家身份/game_id ⇒ 需侧信道，待用户定（见续点 + README）。

## 续点（下次接手）
1. ranked 上线：`--url .../ws/ranked --bot-name Nosam|Mason`（默认自动重连＝续排位）。先观察
   线上稳定性（rating 变化、有无 chombo/掉线）。
2. **协作检测（待用户决策）**：riichi.dev 不给玩家身份/对局 ID，`names` 路线作废。可行方案 =
   **侧信道指纹**（两 bot 均本机进程）：各自把本局公开状态指纹（dora 指示 + scores + honba +
   kyoku + 公开牌河）写共享目录，指纹一致且座位不同 ⇒ 同桌，第三家 = 剩下座位 →
   `client.py` 的 `coop_detector` 返回 third_pid → `evcalc.set_coop`。启发式（碰撞极低）。
   ⚠ **合规**：排位对他人 bot 用双账号协作压制第三家＝合谋，落地前先确认平台规则允许。
3. observation（base64 JSON）若未来加入玩家身份字段，可改用它直接判同桌（免侧信道）。
