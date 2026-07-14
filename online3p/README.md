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
- ✅ **真机验证通过**：Nosam / Mason 各连 `/ws/validate`，qgrp v3 打完整局三麻、
  零 chombo/掉线 → `validation_result: passed`。
- ⬜ **ranked 上线**：把 `--url` 换成 `wss://game.riichi.dev/ws/ranked` 起两进程（下方）。
- ⚠ **协作（双 bot 同桌）暂不可自动触发**：见下。

## 上线跑法（gpu16b）
每个 bot 一个进程，aigc venv + PYTHONPATH 含 qgrp 仓根 + Mortal3/mortal：
```bash
cd /root/riichienv
PYTHONPATH=/root/Mortal3/mortal:/root/qgrp:/root/riichienv \
/root/aigc_apps/venv/bin/python3 -m online3p.client \
    --url wss://game.riichi.dev/ws/ranked --bot-name Nosam \
    --qgrp-ckpt /root/qgrp3p_run/qgrp3p_v3_ftb50k.pth --device cuda
# 另起一个进程 --bot-name Mason
```
（validate 端点把 url 换成 `.../ws/validate`；validate 默认 `--no-reconnect` 单局即止，
ranked 默认自动重连＝打完一局重新排队。）

## 协作（用户设计）现状与限制
协作 EV 已就绪且数值精确（`../qgrp/bot3p/ev.py::EvCalc3P.set_coop`：同桌时每小局
`leaf_pt = 0.5·自己 − 0.5·第三家`，rank-pt 零和下 = 自己 EV + 0.5·队友 EV）。
**但 riichi.dev 协议不暴露任何玩家身份 / 对局 ID**（`start_game` 只有座位号，observation 只有
牌局状态）——所以一个 bot **无法从协议数据判定队友是否在同桌**。因此：
- `client.py` 的 `coop_detector` 钩子默认 `None`＝纯自己 EV（= 未同桌行为）。
- 要触发协作，需**侧信道**（两 bot 都是本机进程）：各自把「本局公开状态指纹」
  （dora 指示 + scores + honba + kyoku + 公开牌河）写到共享目录，指纹一致且座位不同 ⇒ 同桌，
  第三家 = 剩下那个座位 → `set_coop`。属启发式（指纹碰撞极低），**待用户确认是否要做**
  （另注：在排位对他人 bot 用双账号协作压制第三家＝合谋，是否符合平台规则请先确认）。

## 文件
- `client.py` —— riichi.dev 在线客户端（**上线入口**）。
- `tokens.py` —— 从 `riichi.md` 按名取 JWT。
- `probe_riichidev.py` —— 协议探针（连真实 `/ws/validate` 原样记录每帧，拿 ground truth）。
- `test_coop_ev.py` —— 协作 `leaf_pt` 数值核验（coop == 0.5·self−0.5·third，仍有效）。
- `mock_server.py` / `_smoke_driver.sh` —— ⚠ **旧「mjai.app batch」假设的离线 mock，已被
  真机 `/ws/validate` 验证取代**（真实 riichi.dev 非 batch 协议）；保留仅作离线 gameplay 参考。
