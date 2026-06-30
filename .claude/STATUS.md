# STATUS — 活文档（每次会话更新）

> 维护约定：本文件只放「当前状态 / 产物 / 下一步 / 待决」这类会变的事实。
> 会话日志只做索引：每个 session 一行（日期 + 一句话 + 链接），详情写进 `sessions/cNN.md`。

## 当前阶段（2026-06-30）：**change-001 步骤 2+3+4+5 DONE —— 核心任务完成**（三模型接入 + 12000 局复式循环赛得真实强弱：joint > v8 > community，极接近）
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

## 下一步（change-001 核心已完成；以下为可选收尾）
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
