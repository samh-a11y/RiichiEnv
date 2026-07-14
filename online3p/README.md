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

## pt 目标函数（打牌倾向调参）
bot 最大化的是 **pt EV**（引擎 `../qgrp/bot3p/ev.py::EvCalc3P`，参数在 `bot3p/config.py::BotConfig3P`）：
```
EV(动作) = Σ_leaf w_leaf · [ Σ_r P(名次=r|leaf)·rank_pts[r]   ← 名次项（“pt 分布”）
                             + pt_per_1000·Δ素点_self/1000       ← 素点价值项
                             + bonus(leaf) ]                       ← 自摸/役满/流満 加成
```
`w_leaf`、`P(名次|leaf)` 由 GRP 模型（`grp_trans3p_v1`：续局叶 f̂ 名次边缘 / 终局叶硬排位）给出，
**非配置项**——要改「模型对名次概率的估计」得换 `--trans-ckpt` / 重训 GRP。可拨的旋钮（`BotConfig3P` 字段）：

| 字段 | 默认 | 含义 |
|---|---|---|
| `rank_pts` | `(90, 0, -90)` | **pt 分布**：1/2/3 位各值多少 pt（bot 最终最大化的名次期望）|
| `pt_per_1000` | `0.0` | **素点价值**：每 1000 素点折多少 pt（`0`＝纯名次 / 天凤口径）|
| `tsumo_bonus_pt` / `yakuman_bonus_pt` / `nagashi_bonus_pt` | `0` | 自己 自摸 / 役满 / 流し満貫 和了加成 |

**调参语义（别踩坑）**：
- `rank_pts` **只有差值有意义**（整体加常数不改选择）。`1位−2位` 差＝拼一位的动机，`2位−3位` 差＝防三的
  动机；默认 `(90,0,-90)` 对称。**防三优先** → 3 位更负如 `(90,10,-100)`；**拼一位** → 拉大 1-2 差如 `(120,-10,-110)`。
- `pt_per_1000` **尺度警告**：`rank_pts` 量级 ~90，一庄素点摆动常 ±20~40k，故 `=1` 就等于给素点 ±20~40 pt 的
  直接权重、与名次同量级。想「略贪点」给 **0.1~0.5**；只有素点排名赛才给到 ~1 让素点主导。

**在哪设**：
- **standalone bot（`../qgrp/bot3p/run_stdio.py`）已有 CLI**：`--rank-pts 90,10,-100`、`--pt-per-1000 0.3`、
  `--tsumo-bonus-pt`、`--yakuman-bonus-pt`、`--nagashi-bonus-pt`。
- **本客户端（`client.py` / `live_start.sh`）目前只吃默认值**——`_build_engine` 造 `BotConfig3P` 只传
  ckpt/trans/repo/device/name，pt 字段全走默认 `(90,0,-90)`/`0.0`。**要调真机 ranked bot**：改
  `../qgrp/bot3p/config.py` 里 `BotConfig3P` 的默认值（`live_stop`→`live_start` 重启生效），或把上述 CLI
  接进 online3p（`ClientConfig`+argparse+`_build_engine` 传参+`live_start.sh`，尚未做，需要时再加）。
- ⚠ 与协作权重 `--coop-w-self/--coop-w-third`（上一节）是**两组独立**旋钮：前者调「名次 vs 素点」的口径，
  后者调「自己 vs 压第三家」的协作强度。
- ⚠ 另与 arena **评测报告**口径 `REPORT_PTS`（`arena3p/stat_report.py` 的 avg_pt 顺位点 + 单列素点）是两码事：
  一个是给对局打分的评委，一个是 bot 自己的目标函数。

## 文件
- `client.py` —— riichi.dev 在线客户端（**上线入口**）。
- `coop_detect.py` —— 侧信道同桌检测（共享目录指纹互认）。
- `tokens.py` —— 从 `riichi.md` 按名取 JWT。
- `probe_riichidev.py` —— 协议探针（连真实 `/ws/validate` 原样记录每帧，拿 ground truth）。
- `test_coop_ev.py` —— 协作 `leaf_pt` 数值核验（coop == 0.5·self−0.5·third，仍有效）。
- `mock_server.py` / `_smoke_driver.sh` —— ⚠ **旧「mjai.app batch」假设的离线 mock，已被
  真机 `/ws/validate` 验证取代**（真实 riichi.dev 非 batch 协议）；保留仅作离线 gameplay 参考。
