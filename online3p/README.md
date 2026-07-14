# online3p —— qgrp3p 打牌器接入在线对战（标准 MJAI over WebSocket）

把 qgrp v3 三麻打牌器（`../qgrp/bot3p/`）接进在线三麻对战平台。两个已注册 bot
**Nosam / Mason**（JWT 见仓根 `riichi.md`，已 gitignore）。

## 协议假设（= mjai.app / akagi「标准 MJAI bot」约定，搬到 WebSocket）
- 连接：默认 `Authorization: Bearer <JWT>` 头（`--auth-mode` 可切 `query`/`message`/`none`）。
- 平台自动配桌；每条 WS 消息 = 一批 mjai 事件（JSON 数组；亦容忍单事件 dict 或
  `{"events":[...]}` 信封）；客户端每批回**恰好一条** reaction（无动作 = `{"type":"none"}`）。
- `start_game.id` = 本座（权威）；`start_game.names` = 三家名。
- `end_game` 收尾；默认保持连接等下一局（`--exit-on-end-game` 可改）。
- 方言：平台线 `kita` ↔ bot 侧 `nukidora`，客户端自持双向改写（`--nukidora-out` 控出站）。

> ⚠ 平台的真实 endpoint / 鉴权位置 / 消息信封 / 配桌握手以平台文档为准。以上是通用
> 假设，全部做成 CLI/env 旋钮，上线时对齐即可（见「上线待对齐」）。

## 协作逻辑（用户设计）
- 两 bot **未同桌** → 每个 bot 纯最大化自己 pt EV（qgrp v3 原样）。
- 两 bot **同桌** → 每个 bot 目标 = `0.5·自己 pt_EV + 0.5·(−第三家 pt_EV)`。
  实现 = 每小局把 `leaf_pt` 换成 `0.5·self − 0.5·third`（`../qgrp/bot3p/ev.py::EvCalc3P.set_coop`；
  第三家 pt 复用同一次前向的叶分布，零额外前向）。rank-pt `[90,0,−90]` 零和下等价
  「自己 EV + 0.5·队友 EV」。两 bot 各自从 `start_game.names` 独立判定同桌 + 定位第三家，
  **无需侧信道**。权重可调（`--coop-w-self` / `--coop-w-third`）。

## 文件
- `client.py` —— 在线客户端（进程内接 qgrp bot3p，模型只载一次）。**上线入口。**
- `tokens.py` —— 从 `riichi.md` 按名取 JWT（本地解码 name，不验签）。
- `mock_server.py` —— RiichiEnv-over-WebSocket mock 平台（测试工具，复刻平台↔客户端 wire 契约）。
- `test_coop_ev.py` —— 协作 `leaf_pt` 数值核验（coop == 0.5·self−0.5·third）。
- `_smoke_driver.sh` —— gpu16b 端到端冒烟驱动（mock + Nosam/Mason + dummy 跑半庄）。

## 上线跑法（gpu16b）
每个 bot 一个进程，用 **aigc venv**（有 torch/libriichi3p/websockets），PYTHONPATH 含
qgrp 仓根 + Mortal3/mortal：
```bash
cd /root/riichienv
PYTHONPATH=/root/Mortal3/mortal:/root/qgrp:/root/riichienv \
/root/aigc_apps/venv/bin/python3 -m online3p.client \
    --url wss://<平台地址> --bot-name Nosam \
    --qgrp-ckpt /root/qgrp3p_run/qgrp3p_v3_ftb50k.pth --device cuda
# 另起一个进程 --bot-name Mason
```

## 本地冒烟（无需真实平台；gpu16b）
mock 用**仓库 .venv**（有 riichienv），客户端用 aigc venv：
```bash
cd /root/riichienv
# 协作（2 真实 bot + dummy 第三家）
setsid nohup bash online3p/_smoke_driver.sh 2 1 100 8903 >/dev/null 2>&1 &
# 独自（1 真实 bot + 2 dummy → coop OFF）
setsid nohup bash online3p/_smoke_driver.sh 1 1 100 8904 >/dev/null 2>&1 &
# 结果看 online3p/_smoke/{mock,nosam,mason}.log
```
已验证（2026-07-14）：协作桌 Nosam/Mason 均 `coop ON` 定位第三家=dummy，186 步整半庄
零 select 失配，第三家被压到垫底；独自桌 `coop OFF`。协作 `leaf_pt` 数值 `max|err|=0`。

## 上线待对齐（真实平台）
1. **endpoint**：`--url wss://…`（现无，等平台给）。
2. **鉴权位置**：默认 header Bearer；若平台走 query（`?token=`）或首消息登录，用
   `--auth-mode query`/`--auth-mode message`（或 `--hello-msg '<json>'` 自定握手）。
3. **消息信封**：默认裸数组/裸事件/`{"events":[…]}`；若平台包了别的外层，改 `client.py`
   `_run_once` 里的解包分支。
4. **配桌**：默认「连上即自动配桌，平台推 start_game」；若需先发 join/ready，用 `--hello-msg`。
5. **拔北命名**：默认出站写回 `kita`；若平台本就收 `nukidora`，`--nukidora-out nukidora`。
