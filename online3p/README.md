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

## 打牌器后端（`--backend`）

| backend          | 打牌器                                              | coop / level / pt 旋钮                        | 权重参数                                                  |
| ---------------- | --------------------------------------------------- | --------------------------------------------- | --------------------------------------------------------- |
| `qgrp`（默认） | qgrp3p 的`EvCalc3P` + trans_core                  | 全部适用                                      | `--qgrp-ckpt` / `--trans-ckpt` / `--transcore-repo` |
| `mortal3`      | Mortal3 原生 Brain/DQN，greedy argmax Q = mse-best  | **不适用**（无 EV 混合，coop 自动关）   | `--mortal-ckpt`                                         |
| `hybrid`       | **qgrp3p v5 打主 + `A·ref_r3` 每动作修正** | 全部适用（bot 本体仍是 QgrpBot3P + EvCalc3P） | qgrp 三件 +`--ref-ckpt` / `--alpha`                   |

### hybrid —— qgrp3p v5 + ref_r3（2026-07-28 上线）

```
score[a] = EV_qgrp_v5[a] + A · Adv_ref_r3[a]        A 定档 0.18（pt）
```

`ref_r3` = workspace 仓 design-001 分支反事实 best-response 网。两侧同为「±90 制
顺位 pt」（qgrp `rank_pts` 默认与 design-001 标签 UMA 都是 `(90,0,−90)`）⇒ 直接
相加、不换算；ref 侧取 advantage（减 `mean_legal`，因为它的 Q 绝对水平位是自由
gauge）。实现在 **workspace 仓** `hybrid/`（`--hybrid-repo` 指其仓根，默认
`/home/administrator/workspace`），定案与标定数据见
[workspace/hybrid/README.md](../../workspace/hybrid/README.md)。

**上线（双 bot + coop，A=0.18）**：

```bash
cd ~/riichienv && bash online3p/live_start.sh --backend hybrid --alpha 0.18
```

**dry-run（vs 3 个内置 tsumogiri，不影响 rating）**：

```bash
cd ~/riichienv && /home/administrator/miniconda3/envs/mortal/bin/python -m online3p.client \
  --url wss://game.riichi.dev/ws/validate --bot-name Nosam --backend hybrid --alpha 0.18 \
  --qgrp-ckpt $HOME/qgrp3p_run/qgrp3p_v5_full.pth \
  --trans-ckpt $HOME/zeroppo-grp/grp_trans3p_v1.pth \
  --transcore-repo $HOME/zeroppo-grp --device cuda --no-reconnect --no-coop
```

hybrid 专属旋钮（也可用 env：`HYBRID_ALPHA` / `HYBRID_REF_CKPT` / `HYBRID_WS_REPO`）：

| flag                 | 默认                          | 含义                                                                                                  |
| -------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------- |
| `--alpha`          | `0.18`                      | ref 修正因子（pt）。0 = 退化成纯 qgrp v5                                                              |
| `--ref-ckpt`       | workspace`snaps/ref_r3.pth` | ref 权重                                                                                              |
| `--ref-slope`      | `1.0`                       | ref advantage→pt 标定斜率（`1.487` = ref_r3 实测，做 pt 无偏才用）                                 |
| `--ref-coop-scale` | 关                            | 开 = coop 局把 A 乘`w_self`（0.18→0.09），让 ref 项相对 qgrp 自身项权重恒定；默认关 = A 绝对值恒定 |
| `--hybrid-repo`    | `~/workspace`               | workspace 仓根（含`hybrid/`）                                                                       |

启动日志会打全套生效值（ckpt / `.so` 路径与 `ACTION_SPACE` / 定档配置 / coop 权重），
以 `引擎就绪(hybrid)` 开头——上线后先核对这一行。

> ⚠ hybrid 会把 **workspace 那份 `libriichi3p.so`** 抢占进 `sys.path` 头部（as81
> joint、752 平面，ref_r3 的输入要求）。它与 `Mortal3/mortal` 那份对 obs/mask 逐位
> 一致（1614 tick 实测），但额外带 `dataset.shanten_waits_batch`（v5 向听/待张平面
> 的 rust 快路径，且与 qgrp python 口径逐手一致），所以对 v5 是升级不是降级。

## 状态（2026-07-28）

- ✅ **hybrid 后端上线**：`--backend hybrid --alpha 0.18`（qgrp3p v5 + 0.18·ref_r3）；
  `/ws/validate` → `validation_result: passed`（本机 4070）。
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

## 协作（用户设计）—— 侧信道同桌检测，`--coop` 开

协作 EV 已就绪且数值精确（`../qgrp/bot3p/ev.py::EvCalc3P.set_coop`：同桌时每小局
`leaf_pt = 0.5·自己 − 0.5·第三家`，rank-pt 零和下 = 自己 EV + 0.5·队友 EV）。
**riichi.dev 协议不暴露玩家身份 / 对局 ID**（`start_game` 只有座位号，observation 只有牌局
状态）——一个 bot 无法从协议判定队友是否同桌，只能靠**侧信道**（两 bot 均本机进程，
共享 `/tmp/riichi_coop`，`coop_detect.py`）。

**判定方式 `--coop-mode`（用户裁定 2026-07-28）**

- **`timing`（默认，现役）** 两段式：① `start_game` 接收时刻差 < `--coop-sg-gate`（5s）
  粗筛「进入游戏的时间差」；② 公开事件流存在**连续公共段** ≥ `--coop-min-run`（8）条，
  且时间偏移同期一致（|median Δt| < `--coop-offset-gate` 5s、90 分位抖动 <
  `--coop-spread-gate` 2s）；③ 座位不同 ⇒ 第三家 = 剩下那个座位。**命中即开**——不等下
  一小局，命中当场 `set_coop` 并重算本小局 `leaf_pt`（`set_coop` 只改权重，`leaf_pt` 是
  `start_kyoku` 时算好的）。判据在**每个决策点、喂 bot 之前**重查（动作是 `_feed` 里算好
  存 `pending` 的，`request_action` 只是取出来发走，那时才开就晚一个决策）；命中后**仍持续
  announce**，否则队友永远读不到自己。
- **`fingerprint`（旧，保留可回退）**：start_kyoku 公开指纹相同。**已知会误判**——开局 E1
  全 35000 / oya=0 / honba=kyotaku=0 时，指纹里唯一有区分力的只剩 dora_marker（约 1/34
  撞上）。2026-07-28 实测撞了：一个 bot 首小局误判同桌并锁存整局，全程按
  `0.5·自己 − 0.5·第三家` 压制一个与它无关的真人；且命中后不再 announce，队友恒
  `coop OFF`（线上看到的**单向不对称**就是这个成因）。

**真实 log 验证**（`verify_coop_timing.py`，拿 RAW 帧离线回放；也是上线门2）：5×5 局交叉，
金标准 = 整局公开事件序列的最长连续公共段占比（真同桌实测 371/371、730/730 逐条全同）。
timing 判据 **4 对真同桌全部命中、21 对不同桌全部拒绝，0 假阳 0 假阴**。阈值来自实测边界：
不同桌整局最多凑出 7 条连续相同、前 12 条内只有 1–3 条，而同桌前 12 条即全对 ⇒
`min_run=8` 落在两者之间。真机上两 bot **双向对称**命中：`third_seat=0`、连续段 8/10 条、
Δstart_game 0.839s、抖动 0.46/0.98s。

⚠ 时间**不能**用来逐条配对：客户端同步阻塞，`bot.react()` 推理期间不读 WS，帧接收时刻
被自己的 GPU 耗时污染（同一条事件两 bot 实测差 0.3–0.5s 且方向不定）。第一版按「绝对时刻
最近」配对并要求零冲突，在**真同桌**样本上得 match=10 / mismatch=46，被自己的否决条件拒掉
（假阴）。改成「内容对齐连续段 + 偏移一致性」才稳。

- **默认开**（用户裁定＝核心测试；`--no-coop` 关＝纯自己 EV）。**只传公开局面/时序特征，
  不传任何私有手牌信息**（`public_digest` 把 tehais、自家摸牌的 pai、座位号一律抹掉），
  每 bot 仍只用自己观测独立优化 `0.5·self−0.5·third`（非隐藏信息共谋）。
- 旋钮：`--coop-dir`（默认 `/tmp/riichi_coop`）、`--teammates Nosam,Mason`、
  `--coop-w-self/--coop-w-third`（默认 0.5/0.5）、`--coop-mode`、`--coop-sg-gate`、
  `--coop-min-run`、`--coop-offset-gate`、`--coop-spread-gate`。

## 上线纪律（两道门，2026-07-28 事故后强制）

**正门只有一条命令**：

```bash
cd ~/riichienv && bash online3p/go_live.sh --backend hybrid --alpha 0.18
```

它依次跑：**门1** 离线双边回放（`replay_smoke.py`，整条链路 `handle_frame → _feed → _note_event → _try_coop_timing → bot.react` 真实推理 `→ _on_request_action → _sanitize`，
双边跑还覆盖 coop **命中**路径）→ **门2** coop 判据无假阳（`verify_coop_timing.py`）
→ 签发通行证（`gate.py`，绑定上线链路 **代码指纹** + 2h 时效）→ `live_start.sh`。

> **2026-07-29：去掉了原门3**（`/ws/validate` 拿 `passed:true`）。它是唯一真正连平台的
> 门，但要求先停机——ranked 在跑时用同一 JWT 连 validate 会把在跑的 bot 挤掉（又是摸切），
> 于是每次上线都得「停机 → 过门 → 再起」。**代价**：门禁不再覆盖「平台协议 / 服务器行为
> 变化」这类问题，只剩离线两门 + 代码指纹。要手动验平台（需 bot 当前没在 ranked 上跑）：
> `python -m online3p.client --url wss://game.riichi.dev/ws/validate --bot-name Nosam
> --no-reconnect --no-coop`。

关于 **2h 时效**：只在**发出上线命令那一刻**检查一次（`gate.py check`，由 hook 调用），
指的是「通行证签发 → 上线」的间隔上限。**bot 跑起来后不再校验，不会 2 小时自动断**。

Claude Code 的 PreToolUse hook（`online3p/hooks/live_gate.sh`，注册在
`~/.claude/settings.json`）拦下任何绕过正门的 `live_start.sh` / `ws/ranked` 命令，除非
通行证有效。**代码一改指纹就变，通行证立即失效**，必须重新过门。（改 settings 后需重启
Claude Code session 才生效。）

> 事故经过：改完 `client.py` 只做 `py_compile` 就上 ranked。字段改名（`coop_min_events`
> → `coop_min_run`）漏改了 `_try_coop_timing` 里一处引用，`AttributeError` 每帧触发 →
> 断线重连 120+ 次 → bot 全程无法出牌 → 平台代打摸切，真实排位分受损。**语法检查抓不到
> 属性名错误，必须跑运行时门。**

- ranked 正在跑时**不要**用同一 JWT 连 validate（撞 token 双连会把在跑的 bot 挤掉，又是
  摸切）——这正是门3被去掉的原因；如需手动验平台，先停机。
- 只过门不上线：`GATES_ONLY=1 bash online3p/go_live.sh`。
- 回放门的输入样本固定在 `online3p/_samples/{A,B}.frames.jsonl`（用
  `RIICHI_RAW=1` 采一局**同桌**对局即可更新；同桌样本才能覆盖 coop 命中路径）。
- 进程与 session 的关系：`live_start.sh` 用 `setsid nohup`，两 bot 的 SID = 自身 PID、
  无控制终端 ⇒ **关掉终端 / Claude Code session 不会杀它们**；但父链仍挂在 WSL 的
  `SessionLeader` 下，`wsl --shutdown` 或 Windows 重启会一起没，且进程级崩溃**无守护**
  （client 内部只有 WS 重连）。要真正常驻建议改用 systemd user service（`Restart=always`）。

## pt 目标函数（打牌倾向调参）

bot 最大化的是 **pt EV**（引擎 `../qgrp/bot3p/ev.py::EvCalc3P`，参数在 `bot3p/config.py::BotConfig3P`）：

```
EV(动作) = Σ_leaf w_leaf · [ Σ_r P(名次=r|leaf)·rank_pts[r]   ← 名次项（“pt 分布”）
                             + pt_per_1000·Δ素点_self/1000       ← 素点价值项
                             + bonus(leaf) ]                       ← 自摸/役满/流満 加成
```

`w_leaf`、`P(名次|leaf)` 由 GRP 模型（`grp_trans3p_v1`：续局叶 f̂ 名次边缘 / 终局叶硬排位）给出，
**非配置项**——要改「模型对名次概率的估计」得换 `--trans-ckpt` / 重训 GRP。可拨的旋钮（`BotConfig3P` 字段）：

| 字段                                                             | 默认             | 含义                                                                  |
| ---------------------------------------------------------------- | ---------------- | --------------------------------------------------------------------- |
| `rank_pts`                                                     | `(90, 0, -90)` | **pt 分布**：1/2/3 位各值多少 pt（bot 最终最大化的名次期望）    |
| `pt_per_1000`                                                  | `0.0`          | **素点价值**：每 1000 素点折多少 pt（`0`＝纯名次 / 天凤口径） |
| `tsumo_bonus_pt` / `yakuman_bonus_pt` / `nagashi_bonus_pt` | `0`            | 自己 自摸 / 役满 / 流し満貫 和了加成                                  |

**调参语义（别踩坑）**：

- `rank_pts` **只有差值有意义**（整体加常数不改选择）。`1位−2位` 差＝拼一位的动机，`2位−3位` 差＝防三的
  动机；默认 `(90,0,-90)` 对称。**防三优先** → 3 位更负如 `(90,10,-100)`；**拼一位** → 拉大 1-2 差如 `(120,-10,-110)`。
- `pt_per_1000` **尺度警告**：`rank_pts` 量级 ~90，一庄素点摆动常 ±20~40k，故 `=1` 就等于给素点 ±20~40 pt 的
  直接权重、与名次同量级。想「略贪点」给 **0.1~0.5**；只有素点排名赛才给到 ~1 让素点主导。

**在哪设**：

- **standalone bot（`../qgrp/bot3p/run_stdio.py`）已有 CLI**：`--rank-pts 90,10,-100`、`--pt-per-1000 0.3`、
  `--tsumo-bonus-pt`、`--yakuman-bonus-pt`、`--nagashi-bonus-pt`。
- **本客户端（`client.py`）已接通同名 CLI**：`--rank-pts 90,10,-100`、`--pt-per-1000 0.3`、
  `--tsumo-bonus-pt`、`--yakuman-bonus-pt`、`--nagashi-bonus-pt`（不给=`BotConfig3P` 默认，单一真源）。
- **`live_start.sh` 透传任意 client flag**：脚本名后面接的 flag 原样转发给两 bot（同参），如
  `bash online3p/live_start.sh --coop-w-third 0.4 --pt-per-1000 0.3 --level 4.0 --aggr 17.4`
  （⚠ 别透传 `--bot-name`/`--url`——bot 名由脚本设、URL 用 `RIICHI_URL` env，否则撞 token 双连；
  `LEVEL=`/`AGGR=` env 仍可用，命令行 flag 优先）。生效值全打在**引擎就绪日志**（`level/aggr | pt: rank_pts/pt_per_1000/bonus | coop(self/third)`），`live_stop`→`live_start` 重启后据此确认。
- ⚠ 与协作权重 `--coop-w-self/--coop-w-third`（上一节）是**两组独立**旋钮：前者调「名次 vs 素点」的口径，
  后者调「自己 vs 压第三家」的协作强度。
- ⚠ 另与 arena **评测报告**口径 `REPORT_PTS`（`arena3p/stat_report.py` 的 avg_pt 顺位点 + 单列素点）是两码事：
  一个是给对局打分的评委，一个是 bot 自己的目标函数。

## 剥削旋钮（对手 profile：水平 / 激进度）

模型在自博弈谱上**条件于 (水平, 激进度) 身份**训练（train-003 §2），推理端喂这对值 = **告诉模型对手是什么
profile，让它针对性调整打法去剥削对手**。编码在 aux `AUX_LEVEL_AGGR`（`../qgrp/bot3p/seq_encoder.py`），
**三家同值**（一个整桌常数，非逐座；`for r in range(3)` 三家写同值）——所以拨的是「这桌对手的整体 profile」。

- 旋钮：`--level`（水平）、`--aggr`（激进度）；**不给 = `BotConfig3P` 默认 `level=8.0`/`aggr=12.0`**
  （`BOT_LEVEL`/`BOT_AGGR`，= 自产谱口径，对手 Mortal 系）。归一化：aux 里 `level/10`、`aggr/20`
  （量级 level~0-10、aggr~0-20）。config 注释另给 **H 凤桌口径 `--level 7.5 --aggr 13`**。
- `live_start.sh` env 透传：`LEVEL=7.5 AGGR=13 bash online3p/live_start.sh`（不设=默认）。
- ⚠ 三家同值＝**没有「自家 vs 对手」分别设**的能力（要分座建模得改编码器 + 重训）。

## 文件

- `client.py` —— riichi.dev 在线客户端（**上线入口**）。
- `coop_detect.py` —— 侧信道同桌检测（共享目录指纹互认）。
- `tokens.py` —— 从 `riichi.md` 按名取 JWT。
- `probe_riichidev.py` —— 协议探针（连真实 `/ws/validate` 原样记录每帧，拿 ground truth）。
- `test_coop_ev.py` —— 协作 `leaf_pt` 数值核验（coop == 0.5·self−0.5·third，仍有效）。
- `mock_server.py` / `_smoke_driver.sh` —— ⚠ **旧「mjai.app batch」假设的离线 mock，已被
  真机 `/ws/validate` 验证取代**（真实 riichi.dev 非 batch 协议）；保留仅作离线 gameplay 参考。
