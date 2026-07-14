# online3p —— qgrp3p 打牌器接入 riichi.dev / RiichiLab 在线三麻对战

把 qgrp v3 三麻打牌器（`../qgrp/bot3p/`）接进 **riichi.dev（RiichiLab）** 在线三麻平台。
两个已注册 bot **Nosam / Mason**（JWT 见仓根 `riichi.md`，已 gitignore）。

## 真实协议（探针 `/ws/validate` 实测，见 `.claude/sessions/c07.md`）
- 连接 `wss://game.riichi.dev/ws/{validate,ranked}`，`Authorization: Bearer <JWT>` 头。
  `/ws/validate` = 待验证 bot（vs 3 个内置 tsumogiri）；`/ws/ranked` = 已激活 bot 排位。
- 平台自动配桌 + 驱动游戏；每帧 = **单个 JSON 对象**。服务器逐帧下发 mjai 事件
  （start_game / start_kyoku / tsumo / dahai / kita / pon / kan / reach / hora / end_kyoku…）。
- bot **只对 `request_action` 帧回复**：一条 mjai 动作 + **回显 `request_id`**
  （不响应 = `{"type":"none","request_id":N}`）。`request_action` 带：
  `possible_actions`（合法集，本客户端用作防 chombo 兜底）、base64 `observation`
  （RiichiEnv 原生状态，**本客户端不用**——状态从 mjai 事件流跟踪）、`time`（预算约 18s）。
- `start_game` = `{"type":"start_game","id":<座位 0-2>}`，**无 names / 无玩家身份 / 无 game_id**。
- `action_ack` 确认（含 bank/elapsed_ms）；`end_game` 收工；validate 端点随后发
  `{"type":"validation_result","passed":true}`。ranked 下 `end_game` 即断开（重连=重新排队）。
- 拔北 = `kita`（`{"type":"kita","pai":"N"}`）；客户端 `kita↔nukidora` 双向改写。
- 非法/超时动作 → **chombo（満貫罚）**；本客户端 `possible_actions` 兜底确保永不 chombo。

## 架构
进程内接 qgrp bot3p（`EvCalc3P` 模型 + trans_core 只载一次，跨局复用）：每个 mjai 事件
喂 `bot.react()` 跟踪状态 + 缓存其触发的动作；`request_action` 到达时发出缓存动作 + 补
`request_id`，并对 `possible_actions` 做合法性兜底。**不需要 riichienv 包**（纯 MJAI 桥）。
全在 gpu16b **aigc venv**（torch/libriichi3p/websockets）。

## 状态（2026-07-14）
- ✅ **真机验证通过**：Nosam / Mason 各连 `/ws/validate` → `validation_result: passed`（gpu16b + 本机 4070 均过）。
- ✅ **本机 4070 部署上线 ranked**：`live_start.sh` 起两进程续排位（coop 默认开、自动重连、同起）。
- ✅ **实测被凑同一桌**（我两 bot + 1 外部玩家）；平台允许同主同桌。

## 部署（本机 4070 WSL）
环境 = conda **mortal** env（`~/miniconda3/envs/mortal`，py3.12 + torch cu124 + libriichi3p + websockets），
权重 `~/qgrp3p_run/qgrp3p_v3_ftb50k.pth`，trans_core `~/zeroppo-grp`。

**启动（同起，coop 默认开）**：
```bash
cd ~/riichienv && bash online3p/live_start.sh
```
**停止（打完当前对局再停、同停）**：
```bash
cd ~/riichienv && bash online3p/live_stop.sh          # 优雅：发 STOP 标记，两 bot 各打完当前对局后退
cd ~/riichienv && bash online3p/live_stop.sh --force  # 立即强杀（不等当前对局）
```
**看状态**：`tail -f ~/riichienv/online3p/_live/{Nosam,Mason}.log`（`[coop ON] third_seat=N` = 同桌协作中）。

> 优雅停机机制：`live_stop.sh` 触碰 `/tmp/riichi_coop/STOP`；两 bot 检测到后**不中断进行中对局**，
> 各自打完当前一整局（收到 `end_game`）才退出；空闲排队时约 5s 内退。也响应 `SIGTERM`/`SIGINT`。
> 手动单进程调试：`--url .../ws/validate --no-reconnect --no-coop` 跑单局验证。

## 协作（用户设计）—— 侧信道指纹，`--coop` 开
协作 EV 已就绪且数值精确（`../qgrp/bot3p/ev.py::EvCalc3P.set_coop`：同桌时每小局
`leaf_pt = 0.5·自己 − 0.5·第三家`，rank-pt 零和下 = 自己 EV + 0.5·队友 EV）。
**riichi.dev 协议不暴露玩家身份 / 对局 ID**（`start_game` 只有座位号，observation 只有牌局
状态）——一个 bot 无法从协议判定队友是否同桌。故用**侧信道**（`coop_detect.py`，两 bot 均本机
进程）：每局 start_kyoku 各自把座位无关的公开指纹（场风/局/本场/供托/亲/三家点数/宝牌指示）写
共享目录、settle 后读对方；指纹一致且座位不同 ⇒ 同桌，第三家 = 剩下座位 → `set_coop`。

- **默认开**（用户裁定＝核心测试；`--no-coop` 关＝纯自己 EV）。**只传"是否同桌"的公开局面指纹，
  不传任何私有手牌信息**，每 bot 仍只用自己观测独立优化 `0.5·self−0.5·third`（非隐藏信息共谋）。
- 匹配用**整局不变的对局指纹**（首小局 E1 公开状态），每小局重查直到命中并锁存——即便首局两进程
  错开，次局瞬时重读也能命中（对方 announce 在 120s TTL 内）。已单测四例 + 真机实测同桌两 bot 均 `coop ON`。
- 旋钮：`--coop-dir`（默认 `/tmp/riichi_coop`）、`--teammates Nosam,Mason`、`--coop-wait-sec`（首局轮询上限）、
  `--coop-w-self/--coop-w-third`（默认 0.5/0.5）。

## 文件
- `client.py` —— riichi.dev 在线客户端（**上线入口**）。
- `coop_detect.py` —— 侧信道同桌检测（共享目录指纹互认）。
- `tokens.py` —— 从 `riichi.md` 按名取 JWT。
- `probe_riichidev.py` —— 协议探针（连真实 `/ws/validate` 原样记录每帧，拿 ground truth）。
- `test_coop_ev.py` —— 协作 `leaf_pt` 数值核验（coop == 0.5·self−0.5·third，仍有效）。
- `mock_server.py` / `_smoke_driver.sh` —— ⚠ **旧「mjai.app batch」假设的离线 mock，已被
  真机 `/ws/validate` 验证取代**（真实 riichi.dev 非 batch 协议）；保留仅作离线 gameplay 参考。
