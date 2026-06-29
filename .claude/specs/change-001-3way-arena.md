# change-001 — 三模型（v8 / joint-v2 / community）接入 RiichiEnv 三麻对战器

状态：**进行中** — 步骤 0+1 DONE（c02），下一步 = 步骤 2　创建：2026-06-29（c01）

## intent
把三个 Mortal 系三麻模型接入 RiichiEnv（中立公共 arena），跑三人 sanma 半庄循环赛，得出三者在同一裁判下的真实强度关系（avg placement，公平均 2.00，越低越强）。

被测模型见 `PROJECT.md` §2 / `RESOURCES.md` §B：v8（gpuo `libriichi-sanma` 575/44）、joint-v2（我们 `libriichi3p --features joint` 752/81）、community（社区 `libriichi3p` 775/44）。

## 设计（已定，见 PROJECT.md §3）
- 桥接层 = **MJAI**。每个模型 = 一个 **MJAI 引擎适配器**：吃 `obs.new_events()` 的 mjai 事件、回一条 mjai 动作；RiichiEnv 用 `obs.select_action_from_mjai(resp)` 收回。
- 优先实现方式 = **子进程引擎**（Mortal `bot.py` 已是 stdin/stdout mjai 协议）：三者各用各的 python/torch/.so，零版本冲突。joint-v2、community 直接有 bot.py；v8 需自写 MJAI loop wrapper。
- 备选方式 = in-process import（仅当某模型 .so 能与 RiichiEnv 同 venv 共存且无冲突时，省 IPC 开销）。
- 不改上游 Rust。我们的接入代码放本仓库专属目录（建议 `arena3p/`，含 `engines/`、`run_arena.py`、`configs/`），加进 `.gitignore` 忽略权重/.so。

## 任务分解（建议顺序，每步可独立验证）

### 步骤 0 — RiichiEnv 自身可用 ✅ DONE（c02）
- [x] 装 `uv`(本机缺)；`uv sync --dev && uv run maturin develop --release` 成功（Rust 1.92, pyo3 0.28, .venv py3.12）；`RiichiEnv(game_mode='3p-red-half').reset()` 通过。
- [x] DoD：哑策略跑通一整局半庄，`obs.new_events()` 样例存档 `arena3p/samples/*.jsonl`（供 §C MJAI diff）。

### 步骤 1 — MJAI 方言对齐（头号风险，先做）✅ 核心 DONE（c02）
- [x] 取 RiichiEnv `3p-red-half` 整局 mjai 事件流逐事件 diff（vs Mortal3 schema + 官方 riichi.dev 文档）。**结论：唯一硬差异 = 拔北 `kita`(RiichiEnv) vs `nukidora`(Mortal)，需 wrapper 双向改写 type；其余字段全兼容**。座位/kyoku/牌集/tsumogiri 边界均符合。详见 `RESOURCES.md §C`。
- [ ] 用一条已知事件序列喂 community `bot.py`，确认不报错、出合法动作。→ **顺延步骤 2**（需 community 子进程骨架，与步骤 2 重叠；届时一并实测 `reason`/`tsumo` 等多余字段是否真被 libriichi serde 忽略）。
- DoD：逐事件 diff ✅ + 差异记录 RESOURCES.md §C ✅ + 定适配方案（wrapper 内 kita↔nukidora，不改上游）✅。「被模型完整消费」实测随步骤 2 闭合。

### 步骤 2 — community 引擎适配器（最易，打通骨架）
- [ ] 写 `arena3p/engines/community.py`：subprocess 拉起 `~/miniconda3/envs/mortal/bin/python community_3p/v0.1.0/bot.py`（按其 README 选对 .so），stdin 喂事件、stdout 收动作，封装成 `act(obs)->Action`（内部 `select_action_from_mjai`）。
- [ ] 自我对战 smoke：3×community 跑 1 半庄无错、产出 scores/ranks。
- DoD：`run_arena.py --players community,community,community --hanchan 1` 跑通。

### 步骤 3 — joint-v2 引擎适配器
- [ ] 准备 joint .so（AS81/obs752）：从 Mortal3 `artifacts/so/` 取或本地编 `--features joint`，与 `mortal/{model,engine,bot}.py` + `mortal.final.pth` 组成子进程引擎。
- [ ] smoke：joint vs community×2 跑 1 半庄无错。⚠ 确认 action 81 joint 在 MJAI 层透明（44≤a<81 映射在其 engine 内）。
- DoD：joint 能在 RiichiEnv 里完整打完半庄。

### 步骤 4 — v8 引擎适配器（最重）
- [ ] 从 gpuo fetch v8 资产到本地 gitignore 路径：`runs/v8_bc/model.pth` + `engine/libriichi-sanma` .so + `model/net.py` + `features/`。
- [ ] 因 v8 无 stdin/stdout bot，自写 MJAI loop wrapper（参照 `eval/agent_v8_guard.py` 的 react 流程 + `sanma_joint_api.py`），**guard 关闭**（guard 是负结果，且非模型本体强度）。
- [ ] smoke：v8 vs community×2 跑 1 半庄无错。
- 备选：若本地 .so/torch 装不起来，改远程子进程（ssh 常驻 bot），但 IPC 延迟更高。
- DoD：v8 能在 RiichiEnv 里完整打完半庄。

### 步骤 5 — 三方循环赛 + 强度报告
- [ ] `run_arena.py` 支持三个不同引擎同局；统一 greedy/设备/温度口径；CRN 同 seed。
- [ ] 跑足量半庄（参考 gpuo：每对照 5001 半庄量级；三方混桌需注意座位平衡，每个模型轮坐三个座位）。
- [ ] 算各模型 avg placement + rank histogram + 放铳/和率分项，对齐 2.00 公平线。
- DoD：产出三者强度排序表（带样本量、CRN、座位平衡说明），写进 STATUS + 新 session。

## 验证门禁（可被命令/grep 证实）
- `python -c "from riichienv import RiichiEnv"` 通过。
- 三个 `arena3p/engines/*.py` 各自 self-play 1 半庄无 Traceback。
- `run_arena.py` 三方混桌 ≥1 半庄产出 scores/ranks。
- 最终 ≥N 半庄循环赛产出 avg placement 表（N 在 STATUS 记定）。

## 已知风险 / 坑
1. **MJAI 方言不一致**（头号）：见步骤 1。三麻拔北/座位/牌集差异会让 bot 拒动作或崩。
2. **v8 无现成 MJAI bot**：需自写 wrapper，且 .so/权重在远端。
3. **三引擎版本地狱**：子进程隔离已规避导入冲突；但要确认各自 python 能 import 各自 .so（community py3.10 ok、joint 用 aigc_apps venv、v8 用 sanma .venv 或本地重建）。
4. **公平性**：座位平衡（三麻座次影响大）、统一 greedy、统一规则集（`default_tenhou` 三麻）。
5. **joint action 81 vs 44**：确认映射在引擎内透明。
6. **性能**：子进程 IPC 每步开销；大批量对战时考虑常驻进程 + 批量 react。

## 续点
- **从步骤 2 开始**（community 引擎适配器）。步骤 0+1 已 DONE（c02）。
- 步骤 2 关键事实（c02 已探明）：community 子进程 = conda `mortal`(py3.12) python + `../Mortal3/community_3p/v0.1.0/libriichi-3.12-x86_64-unknown-linux-gnu.so`（软链成 `libriichi.so`）+ `mortal.pth`；接口 `libriichi.mjai.Bot(engine, seat).react(单条mjai事件JSON字符串)`，engine 由 `model.load_model(seat)` 起（torch 2.6 已在 conda mortal）。wrapper 在喂入/收回处做 kita↔nukidora 改写。
- 接入代码全部新建在 `arena3p/`，不碰 `riichienv-*` 上游树。任何一步完成即 commit（节点粒度）。
