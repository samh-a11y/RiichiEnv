# STATUS — 活文档（每次会话更新）

> 维护约定：本文件只放「当前状态 / 产物 / 下一步 / 待决」这类会变的事实。
> 会话日志只做索引：每个 session 一行（日期 + 一句话 + 链接），详情写进 `sessions/cNN.md`。

## 当前阶段（2026-07-14）：**change-003 qgrp v3 接入 riichi.dev 在线三麻——已本机 4070 ranked 上线 + coop 默认开；c08 修掉真机 ankan 误判非法回退的兜底 bug（待 live 重启生效）**

### change-003（c07/c08）：qgrp v3 接入 riichi.dev 在线三麻对战 ✅ 真机验证通过，✅ ranked 上线，🐛 c08 修 ankan 兜底误判
- **🐛 c08 修复（真机 ranked 日志暴露）**：`_sanitize` 每次把合法的 **ankan 误判非法回退成打牌**（少一番/宝牌指示牌不翻）。根因：服务器合法集里 ankan 带**冗余 `pai`**（`legal_actions` 用 `tile=Some` → `to_mjai` 插 pai），bot/标准 mjai 的 ankan **不带 pai**，旧 `_match` 比 pai 恒不中。服务器收无 pai 的 ankan 是接受的（`mjai_select.rs` 对 ankan 只按 consumed 匹配、pai 二次校验仅 chi/pon/daiminkan/kakan）⇒ **纯客户端兜底 bug，无需给出站 ankan 补 pai**。修法：`_match` 镜像服务器逻辑——ankan/kita 只比 `consumed`。回归测试 `online3p/test_action_match.py`（9/9 PASS）。⚠ **live 进程仍跑旧码，需 `live_stop→live_start` 重载才生效**。详见 `sessions/c08.md`。
- **任务**：`../qgrp` v3 打牌器接进 **riichi.dev / RiichiLab** 在线三麻；两平台 bot **Nosam/Mason**（JWT 在仓根 `riichi.md`，gitignore）；权重 **qgrp3p_v3_ftb50k.pth**。协作（用户设计）：未同桌→最大化自己 EV；同桌→`0.5·自己 + 0.5·(−第三家)`（= 自己 EV + 0.5·队友 EV）。
- **真实协议（探针 `/ws/validate` 实测，非先前 batch 假设）**：`wss://game.riichi.dev/ws/{validate,ranked}` + Bearer；**每帧单 JSON**，逐帧 mjai 事件，bot **只对 `request_action` 回**且回显 `request_id`；`request_action` 带 `possible_actions`（防 chombo 兜底）+ base64 `observation`（不用，状态从事件流跟踪）；`start_game` **只有座位 id，无 names/身份/game_id**；`end_game` 后 validate 发 `validation_result`、ranked 断开重连；拔北=`kita`；非法/超时=chombo。
- **产物**：`online3p/`（`client.py` 真实协议上线入口=进程内接 qgrp bot3p、模型只载一次、逐帧喂 react 缓存动作、request_action 补 request_id、possible_actions 兜底、kita↔nukidora；`probe_riichidev.py` 协议探针；`tokens.py`/`test_coop_ev.py`；`mock_server.py`/`_smoke_driver.sh` 为旧 batch 假设的 mock，已被真机取代）+ qgrp `bot3p/ev.py::set_coop`（additive 默认关，同步 gpu16b）。
- **验证**：① 协作 leaf_pt 数值 coop==`0.5·self−0.5·third` **max|err|=0**；② **真机验证通过**——Nosam/Mason 各连 `/ws/validate` 打完整局三麻、零 chombo/掉线 → `validation_result: passed`（日志 `online3p/_smoke/val_{nosam,mason}.log`）。
- **本机 4070 部署上线 + 协作默认开**：部署在**本机 4070 WSL**（conda `mortal` env：py3.12+torch cu124+libriichi3p+websockets；权重拷本机 `~/qgrp3p_run/`，trans_core `~/zeroppo-grp`）。启停脚本 `online3p/live_{start,stop}.sh`（同起同停）。**实测被凑同一桌**（我两 bot+1 外部玩家）⇒ 平台允许同主同桌。协作检测因平台**无玩家身份/game_id**用**侧信道指纹**（`coop_detect.py`：整局不变的对局指纹＝首小局 E1 公开状态，经共享目录 `/tmp/riichi_coop` 互认→同桌返回第三家→`set_coop`；每小局重查直到命中，修掉首局竞态漏判）。**coop 默认开**（用户裁定＝核心测试；只传是否同桌、无手牌信息，非隐藏信息共谋；`--no-coop` 关）。**优雅停机**：STOP 标记/SIGTERM → 打完当前对局才退（不中断本局）。
- **环境事实**：客户端用 **aigc venv**（torch/libriichi3p/websockets，纯 MJAI 桥不需 riichienv 包）；`import riichienv` 在 aigc venv 是空 namespace，真包在仓库 `.venv`（见记忆 riichienv-pkg-in-repo-venv）。

（历史）**change-002 ✅ 2×joint-mse vs 1×v8guard 30k**；**change-001 核心完成**——见下。

### change-002（c06）：2×joint-mse vs 1×v8guard 座位轮转复式 30k ✅ DONE
- joint 换在线训练 `3p-mse-v1.1`（实测 ≡joint-v2 同构，仅换权重路径）；v8 换**带 guard** 的 `sanma_v8_guard`（v8 BC backbone + danger head + mitoshi 防守 guard；c04 接的是 guard 关的 v8_bc）；**2v1 复式**（`run_eval._seatings` 放宽；Stat 同名多座=全聚合，joint.game=2×v8guard.game）。
- **等价性 review 100% PASS（DoD）**：arena 牌谱去各模型**独立/原版**推理代码逐决策点重放——默认实战 **6739 点 100%+select_fail=0**；宽松压测 **6690 点 100%**（guard 换牌440/Q保护1565/aka保护6 全覆盖）；helper 穷举 **335449 组全等**。gpu-16↔本机 20 局 god-view 牌谱 md5 全同（闭合 aigc 无 fastapi 跑不了 truth 重放的缺口）。
- **30000 半庄跑完（gpu-16, 157.6min @190/min）→ 最终强弱**：**名次维度（avg_rank + 官方 avg_pt=顺位点[90,0,-90]）实质平手** —— joint avg_rank 1.9998±.003 / 顺位pt +0.013；v8guard 2.0003±.005 / 顺位pt −0.027（差 0.0005 << 噪声；顺位 pt 与 rank 严格同向 `−90·(r−2)` 自洽）。**素点**（归还立直棒后零和）v8guard +0.301k(~2.4σ)/joint −0.151k——v8guard 激进赢得大但更常掉 3 位，单局多收 ~300 点却没换成名次（与顺位点可反向，非矛盾）。⚠`RiichiEnv.scores` 终局不归还桌上未回收立直棒（3.2% 局三家和<105000），原始素点非零和、缺 36 点/局=漏点，归还 1 位后才零和。**风格**：v8guard 激进（立直27.4%/和率29.2%/放铳15.4%/1st·3rd双高=波动大），joint 稳健（放铳13.8%最低/2nd34.1%最多/立直后和率53.0%高）。延续 change-001「joint 稳·v8 凶·极接近」格局。存 gpu-16 `eval_runs/c002_2v1_30k/stat_2v1_30k.txt`。详见 `specs/change-002-2v1-duplicate.md`、`sessions/c06.md`。

### change-001（核心已完成，c02-c05）
- 步骤 5 ✅ DONE（座位轮转复式大样本，c05）：gpu-16 跑 **joint/community/v8 × 4000 seed × 3 循环轮转 = 12000 半庄**（每模型每座正好 4000 局，座位效应彻底对消，94.5min @127 半庄/min）。**最终强弱**：joint(avg_rank 1.984/avg_pt +1.4) > v8(1.999/+0.1) > community(2.017/-1.5)，三者极接近；joint>community ~3σ 站得住，joint/v8/community 两两差距在噪声内。存 `eval_runs/rr_4k3/stat_rotate_12000.txt`。**全在 gpu-16 aigc 3.12 真环境**（见 CLAUDE.md 服务器环境铁律）。
- 步骤 4 ✅ DONE（v8 同事模型，c04）：`libriichi_sanma.mjai.Bot(engine, seat)` 协议与 joint/community 同构；最小 `SanmaV8Engine`（react_batch / obs575 / mask44 / version3 / SanmaNet cfg.in_channels=575，**guard 关=不挂 danger head**）。.so py3.10 编但 **abi3 兼容**，conda mortal py3.12 直接 import（**无需 py3.10 venv**）。资产 fetch 到 `_pkgs/v8`（gitignore）。方言 = **standard**（实测训练 mjai：原生 3 座 + nukidora，同 joint）。**全链路 arena smoke 通过**：`v8,v8,v8` 自对战 + `v8,community,community` 混桌各跑半庄，scores 和守恒/ranks 合法。引擎层另有远端(py3.10)+本地(py3.12)双 smoke。
- 步骤 2 ✅（community 适配器 + arena 框架，c03）：统一 MJAI 子进程 runner + 父进程引擎 + run_arena；`community×3` 自对战整局半庄跑通（scores 和守恒/ranks 正常，零静默兜底）。**闭合步骤1 第二 DoD**（事件流被 community libriichi 完整消费）。
- 步骤 3 ✅（joint-v2 适配器 + 里程碑，c03）：joint 自对战 + **joint vs community×2 混桌真实对战**多半庄跑通，产出合法 scores/ranks。
- **大样本评测工具 + 复现 Mortal 指标（c03 末，commit `7e2a667`）**：`run_eval.py`（并行 N 半庄，落 god-view mjai 日志）+ `stat_report.py`（原生 `libriichi3p.stat.Stat`，复现 test-play 全套指标）。**joint vs community×2 N=10000 跑中**（`eval_runs/joint_vs_comm_10k`，~47 半庄/min，7 workers，ETA 见 run.log）；N=60 预览已显 joint 强于 community（avg_rank 1.82 vs 2.09）。牌谱 `Mortal3/tools/joint_review` 原生可视化已确认。
- **方言修正（c03 实测）**：c02 的「仅 kita↔nukidora」只对 joint 成立。**community 的 .so 是 4 人格式 mjai（第 4 座掩码）**，按座数组须 3→4 padding（scores+35000/tehais+13×"?"/deltas+0），照搬 Mortal3 `cross_validate_community_so.py` 的 17 步验证约定。方言按模型分。
- 步骤 0+1 ✅（c02）：RiichiEnv 三麻可用（uv/maturin 编译，`RiichiEnv("3p-red-half").reset()` 通）+ MJAI 方言逐事件对齐。前情（c01）：clone smly/RiichiEnv（HEAD `b1d08b3`）+ workspace 接入 + `.claude/` 文档系统 + 规格化 change-001。

## 关键事实
- 接入点 = **MJAI 层**（`obs.new_events()` ↔ `obs.select_action_from_mjai()`），三者 obs(575/752/775)/action(44/81/44) 不必统一。
- 三模型资产位置见 `RESOURCES.md` §B。头号风险 = 三麻 MJAI 方言对齐（拔北/座位/牌集），见 change-001 步骤 1。

## 产物
- `.claude/` 文档系统。
- **arena 对战器（c03，全在 `arena3p/`）**：
  - `engines/mjai_runner.py`（统一 MJAI 子进程入口；`build_{community,joint,v8}_bot`）、`engines/subprocess_engine.py`（父进程侧）、`engines/base.py`、`engines/registry.py`（启动规格+每模型方言+强制 CPU；community/joint/v8 三条）。
  - `dialect.py`（按模型方言：joint+v8 仅 kita↔nukidora；community 还需 4 座 padding）。
  - `run_arena.py`（`--players a,b,c --hanchan N --seed S`，产出 scores/ranks + avg placement 汇总）；`run_eval.py`（并行大样本）+ `stat_report.py`（原生 Stat 指标）。
  - `setup_pkgs.sh`（建 `engines/_pkgs/community` symlink package）+ `fetch_v8.sh`（从 gpuo fetch v8 .so/net/features/权重到 `_pkgs/v8`）；`_pkgs/`、`eval_runs/` 已 gitignore。
  - 跑法：`.venv/bin/python arena3p/run_arena.py --players joint,community,community --hanchan 2 --seed 100`（v8 同理，待 arena smoke）。
- `arena3p/collect_mjai_sample.py`、`arena3p/probe_mjai_dialect.py`、`arena3p/samples/*.jsonl`（步骤1 样例/探针）。
- 构建产物：`.venv`（uv）+ 已 `maturin develop` 的 `riichienv._riichienv`（editable）。

## 下一步
### change-003（本机 4070 已部署上线 + coop 默认开）
0. **🐛 c08 ankan 修复需重启生效**：`bash online3p/live_stop.sh`（优雅停，打完当前局）→ `bash online3p/live_start.sh` 让 live 进程重载修好的 `client.py`。重启后关注日志里 `WARN 动作不在合法集` 是否消失（该杠正常出杠）。
1. **运维**：本机 `bash online3p/live_start.sh` 起 / `bash online3p/live_stop.sh` 优雅停（打完当前对局、同停）/ `--force` 强停。日志 `online3p/_live/{Nosam,Mason}.log`。⚠ 别在 gpu16b 同时跑（同 token 双连冲突）。
2. **持续观察**：同桌局 `[coop ON] third_seat=N`；关注 rating、有无 chombo/掉线、协作效果（第三家是否被压制）。
3. ✅ **真机同桌"两 bot 均 coop ON"已 live 确认**（捕到一局：Nosam 座0/Mason 座1 均 third_seat=2、指纹一致；竞态修复现场生效——Nosam 首局漏后 E2 重查命中）。全链路真机闭合。push 前先问用户（本会话已 commit 未 push）。
### change-002（✅ 完成）
1. gpu-16 资产传完 → 解压 sanma_v8_guard + 软链 `_pkgs/v8` 的 v8_bc → smoke 1-2 局 → nohup 跑 30k（`run_eval --players joint-mse,joint-mse,v8guard --rotate --n 10000 --resume`）→ `stat_report --rotate` 出 2v1 强弱。
### change-001（核心已完成；可选收尾）
1. （可选）牌谱可视化复核：`Mortal3/tools/joint_review` 看几局 rr_4k3 的 god-view 日志，定性确认对局合理。
2. （可选）出一份正式强弱报告/图表；或扩大样本（--resume 可续）进一步收紧 joint/v8/community 的置信区间。

## 已得结论
### 权威（座位轮转复式 N=12000/模型，座位平衡，c05；存 `eval_runs/rr_4k3/stat_rotate_12000.txt`）
- **真实强弱：joint > v8 > community，但三者极接近**（avg_rank 1.984 / 1.999 / 2.017，跨度仅 0.033；avg_pt +1.4 / +0.1 / -1.5）。joint > community ~3σ 站得住；joint vs v8、v8 vs community 在噪声内分不清。
- 风格（已去座位混淆）：v8 立直最凶(27.2%)+放铳最高(15.3%)+立直后和率最低(52.0%)=激进；joint 防守最稳(放铳14.7%最低/立直后和率53.1%最高)+转化1位最好；community 副露最多(25.8%)/立直最少，略弱。
### 历史（fixed-seat N=6302，joint vs community×2，c04；**已被复式结论取代**）
- 固定座位下 joint≈community（1.998 vs 2.001）——**座位效应（座间 0.08）糊住了模型差异**；座位轮转后才看清 joint 微弱领先。印证「固定座位无法定强弱、N=2/30 无意义」。

## 待决
- ~~v8 的 mjai 方言~~ **已定（c04 实测）= standard**（原生 3 座 + nukidora，同 joint）。
- numpy ABI：本地 numpy 2.4.6 vs .so 编译期 2.2.6，本地单进程 smoke 已互通无误；全链路 arena 再确认一次。

## 会话日志（索引；详情见 sessions/cNN.md）
- 2026-06-29 · c01 · clone RiichiEnv + 接入 workspace + 建 .claude 文档系统 + 规格化 change-001 三模型对战器接入。[详情](sessions/c01.md)
- 2026-06-29 · c02 · change-001 步骤0+1：建 .venv/maturin 编译跑通 RiichiEnv 三麻；MJAI 方言对齐实测，定位唯一硬差异 kita↔nukidora 双向改写。[详情](sessions/c02.md)
- 2026-06-29 · c03 · change-001 步骤2+3：建统一 MJAI 子进程 arena 框架，接入 community（实测须 4 座 padding）+ joint-v2（原生 3 座），joint vs community 混桌真实对战跑通 = 「可以对战」。[详情](sessions/c03.md)
- 2026-06-29 · c04 · 步骤4 v8 接入：探明 `libriichi_sanma.mjai.Bot`+react_batch 协议同构、.so abi3 可跑 py3.12、方言=standard；fetch 资产到 _pkgs/v8、写 build_v8_bot+registry，引擎远端&本地双 smoke 通过；arena 全链路候 10k 腾 RAM。[详情](sessions/c04.md)
- 2026-06-30 · c05 · 步骤5 座位轮转复式：部署 gpu-16（aigc 3.12 真环境，踩 rust1.92坏toolchain/老pip--group 坑后定铁律入 CLAUDE.md），run_eval 加 --rotate+--resume，跑 joint/community/v8 12000 局复式得真实强弱 **joint>v8>community（极接近）**。[详情](sessions/c05.md)
- 2026-06-30 · c06 · change-002 第二测试任务：2×joint-mse(3p-mse-v1.1) vs 1×v8guard(同事 guard 完整版) 接入（build_v8guard_bot 复刻 SanmaV8GuardEngine + joint 权重参数化 + 2v1 轮转 + review 工具）+ **等价性 review 100% PASS**（牌谱去两模型原版重放：6739 实战 + 6690 压测 + 335449 helper 全等）→ gpu-16 跑 30k。[详情](sessions/c06.md)
- 2026-07-14 · c07 · change-003 qgrp v3 接入 **riichi.dev** 在线三麻：探针实测真实协议（单帧 mjai + request_action/request_id + 无玩家身份）→ 重写 `online3p/client.py`（纯 MJAI 桥、aigc venv、possible_actions 防 chombo）+ qgrp `ev.py::set_coop`；**Nosam/Mason 真机 `/ws/validate` 均 passed**；协作触发受限于平台无身份/game_id（需侧信道，待用户定）。[详情](sessions/c07.md)
- 2026-07-14 · c08 · 真机 ranked 日志暴露 **ankan 被兜底误判非法回退打牌**：读 Rust 源定根因（服务器合法集 ankan 带冗余 pai / bot 不带，`_match` 比 pai 恒不中；服务器收无 pai ankan 按 consumed 接受 ⇒ 纯客户端 bug）→ `_match` 镜像服务器 `select_action`（ankan/kita 只比 consumed）+ 回归测试 `test_action_match.py` 9/9 PASS。⚠ 待 live 重启生效。[详情](sessions/c08.md)
