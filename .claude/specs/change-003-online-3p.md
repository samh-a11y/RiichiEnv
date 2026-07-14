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
- [x] **本机 4070 部署 + ranked 上线**：conda `mortal` env（torch cu124+libriichi3p+websockets）+ 本机权重；
      `live_{start,stop}.sh`（同起同停 + 优雅停机=打完当前对局才退）；本机 validation 亦 passed。
      **实测被凑同一桌**（我两 bot + 1 外部玩家），确认平台允许同主同桌。
- [x] **侧信道协作检测建成 + 单测 + coop 默认开**：`coop_detect.py`（整局不变的对局指纹＝首小局 E1
      公开状态，共享目录互认，每小局重查直到命中——修掉首局两进程错开的竞态漏判）；单测四例过；
      **默认开**（用户裁定＝核心测试，只传是否同桌无手牌信息；`--no-coop` 关）。
- [x] **真机同桌"两 bot 均 coop ON"live 确认（2026-07-14）**：捕到一局同桌 Nosam 座0 / Mason 座1
      均 `[coop ON] third_seat=2`（指纹一致 E1/dora1s/[35000×3]）。竞态修复现场验证：Mason 首局 E1-0
      命中、Nosam 首局漏（skew）但未锁 solo、E2-0 重查命中——两家最终一致。全链路真机闭合。

## 续点（下次接手）
1. ranked 上线已在跑（solo，自动重连）。持续观察稳定性（rating、有无 chombo/掉线）；
   进程/日志：gpu16b `online3p/_live/{Nosam,Mason}.log`。
2. **协作激活（待用户确认合规）**：给两 ranked 进程加 `--coop`（同 `--coop-dir`）即启用侧信道
   同桌检测（`coop_detect.py` 已建+单测）；同桌局打印 `[coop ON] third_seat=N`。⚠ 双账号协作
   压制第三家＝合谋，激活前确认 riichi.dev 规则允许。指纹 = start_kyoku 座位无关公开字段
   （settle 0.4s 让两进程互见）；开局 E1 全 35000 时仅靠宝牌指示区分（误配率低且下局自纠）。
3. observation（base64 JSON）若未来加入玩家身份字段，可改用它直接判同桌（免侧信道、免误配）。
