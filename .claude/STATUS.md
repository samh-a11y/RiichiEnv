# STATUS — 活文档（每次会话更新）

> 维护约定：本文件只放「当前状态 / 产物 / 下一步 / 待决」这类会变的事实。
> 会话日志只做索引：每个 session 一行（日期 + 一句话 + 链接），详情写进 `sessions/cNN.md`。

## 当前阶段（2026-06-29）：**change-001 步骤 0+1 · DONE**（RiichiEnv 可用 + MJAI 方言已对齐）
- 步骤 0 ✅：装 `uv`、`uv sync --dev` + `maturin develop --release`（Rust 1.92）编译通过；`RiichiEnv("3p-red-half").reset()` 通；哑策略跑通一整局半庄（scores/ranks 正常）。
- 步骤 1 ✅：取整局 MJAI 事件流逐事件 diff vs Mortal3 schema + 官方文档（riichi.dev）。**结论：唯一硬性方言差异 = 拔北 `kita`(RiichiEnv) vs `nukidora`(Mortal 模型)，需在 wrapper 双向改写 type 字段，其余原样透传**。详见 `RESOURCES.md §C`。
- 前情（c01）：clone smly/RiichiEnv（HEAD `b1d08b3`）+ workspace 接入 + `.claude/` 文档系统 + 规格化 change-001。

## 关键事实
- 接入点 = **MJAI 层**（`obs.new_events()` ↔ `obs.select_action_from_mjai()`），三者 obs(575/752/775)/action(44/81/44) 不必统一。
- 三模型资产位置见 `RESOURCES.md` §B。头号风险 = 三麻 MJAI 方言对齐（拔北/座位/牌集），见 change-001 步骤 1。

## 产物
- `.claude/` 文档系统。
- `arena3p/collect_mjai_sample.py`（采全事件覆盖样例）、`arena3p/probe_mjai_dialect.py`（双向往返+边界探针）。
- `arena3p/samples/*.jsonl`（整局半庄 god-view + 各座 new_events 流，方言 diff 依据）。
- 构建产物：`.venv`（uv）+ 已 `maturin develop` 的 `riichienv._riichienv`（editable）。

## 下一步
1. **步骤 2：community 引擎适配器**（最易，打通骨架）。conda `mortal`(py3.12) + community `libriichi-3.12-x86_64-unknown-linux-gnu.so` + `mortal.pth`，子进程跑其 `bot.py`；wrapper 做 kita↔nukidora 双向改写；3×community self-play 1 半庄无错。**顺带闭合步骤1 第二个 DoD**（事件流被 community libriichi 完整消费，实测 `reason`/`tsumo` 等多余字段是否真被忽略）。
2. 步骤 3：joint-v2 适配器；步骤 4：v8 适配器；步骤 5：三方循环赛。

## 待决
- v8 接入用「本地 fetch .so+权重自写 wrapper」还是「远程常驻子进程」？（步骤 4 决，看本地能否装起 libriichi-sanma .so + torch）

## 会话日志（索引；详情见 sessions/cNN.md）
- 2026-06-29 · c01 · clone RiichiEnv + 接入 workspace + 建 .claude 文档系统 + 规格化 change-001 三模型对战器接入。[详情](sessions/c01.md)
- 2026-06-29 · c02 · change-001 步骤0+1：建 .venv/maturin 编译跑通 RiichiEnv 三麻；MJAI 方言对齐实测，定位唯一硬差异 kita↔nukidora 双向改写。[详情](sessions/c02.md)
