# RESOURCES — 三模型资产 / RiichiEnv 接口 / 环境

## A. RiichiEnv（上游引擎，本仓库）
- 仓库结构：`riichienv-core`(Rust 引擎) / `riichienv-python`(maturin pyo3 桥，module `riichienv._riichienv`) / `riichienv-ml`(训练+评测 Python，pkg `riichienv_ml`) / `riichienv-ui`(可视化) / `riichienv-wasm`。Python 包源在 `src/riichienv/`。
- 构建：需 Rust 工具链。`uv sync --dev && uv run maturin develop --release`（venv 在 `./.venv`，py3.10–3.14）。
- 三麻 game_mode：`3p-red-single` / `3p-red-east` / `3p-red-half`（天凤三麻规则）。我们用 **`3p-red-half`**。
- 规则：`GameRule.default_tenhou()` / `default_mjsoul()` + 细粒度 flag（见 `docs/RULES.md`）。
- **MJAI 桥接接口**（接入三模型的关键，承上游 README）：
  - `obs.new_events() -> list[str]`：本观测窗新增的 MJAI JSON 事件（首观测含 `start_game`/`start_kyoku` 等）。
  - `obs.events`：该窗完整历史。
  - `obs.select_action_from_mjai(mjai_dict) -> Action | None`：MJAI 动作 → 合法 Action。返回 None 表示非法。
  - 原生 `riichienv_ml.agents.Agent`：用 RiichiEnv 自带 `feat_v*` 编码器 + `obs.mask()` + `obs.find_action(idx)`。**仅适用 RiichiEnv 原生模型，三个 Mortal 模型不走这条**。
  - 已有评测脚手架：`riichienv_ml.agent_eval.AgentEvaluator`（1-vs-N hero vs 固定对手）、`riichienv_ml.evaluator.load_evaluator`。可参考但需为 MJAI-bridge 适配。

## B. 三个被测模型

### B1. v8（同事 gpuo 服务器，最重的一项）
- 机器：`ssh gpuo`（同事的机器，规格/venv 见 `~/.claude/machine.md`）。
- 引擎：`/root/sanma/engine/libriichi-sanma`（pkg `libriichi-sanma`，`[lib] name=libriichi_sanma`，pyo3+numpy0.25），产物 `engine/libriichi-sanma/target/release/liblibriichi_sanma.so`。obs `version==3` rich 575ch×34，**action space 44**（v8 扩的）。
- 权重：`/root/sanma/runs/v8_bc/model.pth`（101MB；`latest.pth`=304MB 含 optimizer）。net=`model/net.py::SanmaNet`(ch384/blk24/in575, 25.31M params)。
- 推理代码：`/root/sanma/eval/agent_v8_guard.py`（含 guard，可关）、`model/net.py`、`features/`(consts.py/encode.py)。
- **✅ c04 实测推翻"最高风险/需自写 wrapper"**：v8 **有** `libriichi_sanma.mjai.Bot(engine, seat)`，协议与 joint/community 同构（engine 鸭子类型实现 `react_batch(states,masks,invisible)->(actions,q,masks,greedy)`；属性 `engine_type='mortal'/is_oracle=False/enable_quick_eval=False/enable_rule_based_agari_guard=False/name/version`）。同事只是没写 bot.py（用 FastAPI `sanma_joint_api.py` /decide 包装，那就是 mjai.Bot 路径）。⇒ 我方**最小 engine** 即可（`arena3p/engines/mjai_runner.build_v8_bot` 复刻 `eval/agent_v2.SanmaV2Engine` 改 obs575/mask44/version3，**guard 关=不挂 danger head**）。
- **本地接入（c04）**：`.so` abi3 兼容 → conda mortal py3.12 直接 import，**无需 py3.10 venv**；资产 `bash arena3p/fetch_v8.sh` fetch 到 `_pkgs/v8/`（.so/model/features/model.pth，gitignore）。权重 `model.pth` keys=`['model','cfg']`、cfg=`{channels:384,blocks:24,in_channels:575,oracle:False}`、`weights_only=False` 加载。action 44 布局见 `features/consts.py`（0..36 discard 含赤/37 riichi/38 pon/39 kan/40 kita/41 hora/42 ryukyoku/43 pass）；id→mjai 由 .so 内部映射，最小 engine 不用管。
- **方言 = standard**（同 joint）：训练 mjai 实测原生 3 座（scores/tehais 3 元）+ 拔北叫 `nukidora`，复用 `to_model_standard`/`to_env`。
- 部署参照：`/root/sanma/sanma_joint_api.py`（FastAPI /decide，torch 接 Rust Bot，契约同 Akagi）——MJAI react 流程可借鉴。
- ⚠ 调研快照（含强度数据）：`../Mortal3/.claude/gpuo-coworker-progress.md`。该目录非 git，只读。

### B2. joint-v2（我们 Mortal3 离线 SL 成品）
- 权重：`../Mortal3/train/sl3p-joint-v2/archive/mortal.final.pth`（127MB，=final/68000 步）。同目录另有 15000/30000/45000/60000 里程碑。
- 引擎：我们的 `libriichi3p` crate，**`--features joint`** 编出（obs(752,27) / **ACTION_SPACE=81** joint / version=4）。产物在 `../Mortal3/mortal/libriichi3p.so`（或 `artifacts/so/` 库，见 Mortal3 `scripts/so_use.sh`）。⚠ 必须用 joint 那颗 .so（AS81/obs752），不是普通 44。
- 推理代码：`../Mortal3/mortal/{model.py(Brain ResNet192/40),engine.py(MortalEngine),bot.py}`。bot.py 是 stdin/stdout MJAI 协议（直接可作子进程引擎）。
- torch python：gpu-16 用 `~/aigc_apps/venv/bin/python`；本机带 torch 的是 `~/miniconda3/envs/mortal/bin/python`。
- 备注：Akagi 部署记录证实「自训 joint 接 Akagi 原生引擎无需 adapter」⇒ 说标准 3p MJAI。
- spec/配置：`../Mortal3/mortal/versions/sl3p-joint-v2/{spec.md,config.toml}`。

### B3. community（社区较弱 3麻权重）
- 资产：`../Mortal3/community_3p/`，两版网络结构相同（仅 import 名 + 在线模式差异）：
  - `v0.1.0/`：模块名 `libriichi`，**有权重** `mortal.pth`(273MB)，`bot.py`(stdin/stdout MJAI)、`model.py`、多平台 `.so/.pyd`。本机用 `libriichi-3.10-x86_64-unknown-linux-gnu.so`。
  - `v0.1.1/`：模块名 `libriichi3p`，无权重(复用 v0.1.0)，`w__init__.py` 需改名 `__init__.py`。
- 权重事实：version=4 / 256ch·52blk / 262k steps / `env.pts=[6,3,0,0]` / **action 44** / obs in_channels **775**。完整 ckpt。用户告知**较弱**。
- 跑法：torch 用 `~/miniconda3/envs/mortal/bin/python`，`bot.py` stdin 读 mjai、stdout 出动作。详见 `../Mortal3/community_3p/README.md`。

## C. MJAI 方言对齐 —— change-001 步骤1 实测结论（2026-06-29 c02）

### 官方文档（先读原文，别只靠二手 schema）
- MJAI 协议：**https://riichi.dev/docs/protocol** —— 上游 smly 官方站，但**以 4p 为主**（start_game/start_kyoku/tsumo/dahai/chi·pon·kan/reach/hora/end_*/tile notation/time control）；**无 sanma 专章、无 kita/nukidora 定义**，3p 仅在 decode 例子提到 `Observation3P`。⇒ 3p 拔北命名属实现层事实，文档不覆盖，**只能以实测为准**。
- Mortal 接入：**https://riichi.dev/docs/mortal** —— 证实桥接：`obs.new_events()` 是按座 delta 流；模型回的 MJAI 动作先 `obs.select_action_from_mjai()` 转回 Action、再 `action.to_mjai()`。
- 权威 3p mjai 契约（我方）：`../Mortal3/.claude/MJAI_SCHEMA_3P.md`（逐字段对齐 `libriichi3p/.../mjai/event.rs`）。

### 实测 ground truth
脚本：`arena3p/collect_mjai_sample.py`（采全事件覆盖样例）+ `arena3p/probe_mjai_dialect.py`（双向往返 + 边界）。环境：`RiichiEnv(game_mode="3p-red-half", rule=GameRule.default_tenhou())`。

> **c03 实测修正**：下面「唯一硬差异=kita↔nukidora」**只对 joint（我们 libriichi3p，原生 3 座）成立**。**community 的 .so 是 4 人格式 mjai（第 4 座掩码）**：按座数组（`start_kyoku.scores/tehais`、`hora/ryukyoku.deltas`）须 3→4 padding（scores+35000 / tehais+13×"?" / deltas+0），否则报 `invalid length 3, expected an array of length 4`。⇒ **方言按模型分**（见 `arena3p/dialect.py`：`to_model_standard` vs `to_model_community`）。社区 4 座掩码约定照搬 Mortal3 `scripts/cross_validate_community_so.py`（17 步状态比对 PASS）。

**拔北命名差异（两模型共有）= `kita`（RiichiEnv）vs `nukidora`（Mortal 系模型期望）**：

| 方向 | RiichiEnv 行为 | Mortal 模型期望 | 桥接适配 |
|---|---|---|---|
| 产出 env→模型 | 事件流出 `{"type":"kita","actor":a,"pai":"N"}` | `{"type":"nukidora","actor":a,"pai":"N"}` | wrapper 改写 **kita→nukidora** |
| 收回 模型→env | `select_action_from_mjai({"type":"kita",...})`→合法 Action3P；`(...,"nukidora",...)`→**返回 None（拒绝）** | bot 回 `nukidora` | wrapper 改写 **nukidora→kita** |

⇒ **桥接层只需双向改写拔北的 `type` 字段，其余事件原样透传**。

其余逐事件 diff vs Mortal3 schema **全兼容**：
- 已覆盖全部事件：start_game / start_kyoku / tsumo / dahai / pon / ankan / kakan / daiminkan / dora / reach / reach_accepted / hora / ryukyoku / end_kyoku / end_game / kita。
- RiichiEnv 多产出的字段：`ryukyoku.reason`(如 `"exhaustive_draw"`)、`hora.tsumo`(bool)、`hora.ura_markers`(可空数组)。libriichi 用 serde 默认（未 `deny_unknown_fields`）忽略未知字段 → **c03 已实测确认无害**（community+joint 各整局自对战，含 hora/ryukyoku 无错）。
- 边界全部符合 schema：actor/oya ∈ {0,1,2}、kyoku ∈ {1,2,3}、bakaze ∈ {E,S,W}、万子仅 `1m`/`9m`（无 2m–8m）、`dahai.tsumogiri` 必填、按座观测对手手牌/摸牌为 `"?"`、`start_game` 无 `names`（schema 允许省略）。

### 三麻坑（Mortal3 c04/c06 已踩，接入沿用）
拔北是自家动作无 dahai、不翻新宝牌、后紧跟岭上 tsumo；天凤三麻仍按 `bakaze*4+oya` 编码座位（牌目标/oya/bakaze 用 %4、活动轮转用 %n）；无 2–8 万；抢拔北不给槍槓役。

### 产物
`arena3p/samples/godview_hanchan.jsonl`（上帝视角整局）+ `player{0,1,2}_events_hanchan.jsonl`（各座 new_events 流）。

## D. 环境/机器速查
| 用途 | 位置 |
|---|---|
| RiichiEnv 构建 venv | `riichienv/.venv`（uv，py3.10+，需 Rust） |
| 本机 torch | `~/miniconda3/envs/mortal/bin/python`(py3.10) |
| GPU 机（gpu-16=训练机 / gpuo=v8 同事机） | 规格/venv/开关机见 `~/.claude/machine.md` |
| 三模型权重 | 见 B1/B2/B3（均百 MB，勿入 git） |
