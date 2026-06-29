# change-001 — 三模型（v8 / joint-v2 / community）接入 RiichiEnv 三麻对战器

状态：**进行中** — 步骤 0+1+2+3 DONE（c02/c03，**可以对战**：community+joint-v2 真实混桌跑通），下一步 = 步骤 4（v8）　创建：2026-06-29（c01）

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
- [x] 用一条已知事件序列喂 community，确认不报错、出合法动作 ✅（c03）。**实测修正**：community 的 .so 是 **4 人格式 mjai（第 4 座掩码）**，按座数组须 3→4 padding；`reason`/`tsumo`/`ura_markers` 等多余字段确被 serde 忽略（整局自对战无错）。c02 的「仅 kita↔nukidora」只对 joint（原生 3 座）成立。
- DoD：逐事件 diff ✅ + 差异记录 RESOURCES.md §C ✅ + 定适配方案 ✅ + 「被模型完整消费」实测 ✅（c03，community+joint 各整局跑通）。

### 步骤 2 — community 引擎适配器（最易，打通骨架）✅ DONE（c03）
- [x] 建**统一** MJAI 子进程框架（非每模型单文件）：`engines/mjai_runner.py`（子进程，数组进/一条出）+ `engines/subprocess_engine.py`（父进程 send/recv+方言+select_action_from_mjai+none→pass 兜底）+ `engines/registry.py` + `dialect.py` + `run_arena.py`。community 经 `engines/_pkgs/community` symlink package 调其 `model.load_model`（py3.12 .so），不改 Mortal3。
- [x] 自我对战 smoke：`community×3` 跑 1 半庄无错、scores 和守恒/ranks 正常、**全程 0 行 WARN（零静默兜底）**。
- [x] **方言修正**：community = 4 人格式（第 4 座掩码），按座数组 3→4 padding（scores+35000/tehais+13×"?"/deltas+0），照搬 Mortal3 `cross_validate_community_so.py` 的 17 步验证约定。
- DoD：`run_arena.py --players community,community,community --hanchan 1` 跑通 ✅。

### 步骤 3 — joint-v2 引擎适配器 ✅ DONE（c03）
- [x] joint .so = `Mortal3/mortal/libriichi3p.so`（已是 AS81/obs752）。runner joint 分支 sys.path 插入 `Mortal3/mortal`，复刻 `mortal.py:31-57` 加载，权重写死绝对路径 `train/sl3p-joint-v2/archive/mortal.final.pth`。
- [x] smoke：joint 自对战 + **joint vs community×2 混桌**多半庄无错、产出合法 scores/ranks。joint 原生 3 座（权威 `MJAI_SCHEMA_3P.md`），隔离测试直接吃 3 元事件回合法 dahai；action 81 在 .so 内透明（select_action_from_mjai 全程干净匹配，0 WARN）。
- DoD：joint 能在 RiichiEnv 里完整打完半庄 ✅。

### 步骤 4 — v8 引擎适配器（最重）🟡 代码完成·引擎双验（c04）
- [x] 从 gpuo fetch v8 资产到 `arena3p/engines/_pkgs/v8/`（gitignore）：`model.pth`(101MB,md5 校验) + `libriichi_sanma.so` + `model/net.py` + `features/`。脚本 `arena3p/fetch_v8.sh`（幂等）。
- [x] **关键探明**：v8 **有** `libriichi_sanma.mjai.Bot`（同事只是用 FastAPI 包装，没写 bot.py）；协议与 joint/community 同构——engine 是鸭子类型对象实现 `react_batch(states,masks,invisible)->(actions,q,masks,greedy)`，读 `engine_type/is_oracle/enable_quick_eval/enable_rule_based_agari_guard/name/version`。⇒ **不必自写完整 wrapper**，写最小 `SanmaV8Engine`（`mjai_runner.build_v8_bot`）即可，**guard 关 = 不挂 danger head**。
- [x] **.so abi3 兼容**：py3.10 编但本地 conda mortal py3.12 直接 import 成功 ⇒ **不必建 py3.10 venv**，registry v8 复用 `CONDA_MORTAL_PY`。
- [x] **方言实测 = standard**（训练 mjai：`start_game.names` 3 个、`start_kyoku.scores/tehais` 3 元、拔北叫 `nukidora`）——与 joint 同，复用 `to_model_standard`/`to_env`。
- [x] 引擎 smoke：远端（gpuo .venv py3.10）+ 本地（conda py3.12，喂自家 eval_runs god-view 日志）各跑一整局，3 座逐事件 react 不崩，出 dahai/nukidora/pon/hora/reach/kakan 全套。
- [ ] **全链路 arena smoke（候 10k 腾 RAM）**：`run_arena.py --players v8,community,community --hanchan 1 --seed 42` + `v8,v8,v8`。3 子进程≈5GB，须等 `joint_vs_comm_10k` 跑完。
- DoD：v8 能在 RiichiEnv 里完整打完半庄（引擎层已证；全链路候 smoke 确认）。

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
- **从步骤 4 开始**（v8 引擎适配器）。步骤 0+1+2+3 已 DONE（c02/c03）；community+joint 可在 RiichiEnv 真实对战。
- 步骤 4 已定方式 = **本地 fetch + py3.10 venv**：fetch `runs/v8_bc/model.pth` + libriichi-sanma .so（py3.10）+ `model/net.py` + `features/` 到本地 gitignore 路径；建 py3.10 venv 装 torch；`engines/mjai_runner.py` 加 v8 分支（建 `libriichi_sanma.mjai.Bot` + SanmaNet，**guard 关**）；`engines/registry.py` 加 v8 条目（python 指向 py3.10 venv）。
  - **v8 方言待实测**：隔离喂一条 3 元 `start_kyoku`——不报 `invalid length 3` 则原生 3 座（dialect="standard"）；报错则 4 座掩码（dialect="community"）。判别法见 c03。
- 步骤 5：`run_arena.py` 加**座位轮转** + 大样本 CRN（每对照量级参考 gpuo 5001 半庄），算 avg placement / rank 直方图 / 放铳和率分项。当前固定座位 avg_place 机械=2.00，非真实强度。
- 接入代码全在 `arena3p/`（统一 runner 架构，加模型 = registry 加一条 + runner 加一个 builder + 必要时 dialect 加一种），不碰 `riichienv-*` 上游树与 Mortal3。任何一步完成即 commit（节点粒度）。
