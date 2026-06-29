# PROJECT — 目标 / 约束 / 已定结论

## 1. 目标
在 [smly/RiichiEnv](https://github.com/smly/riichienv) 这个**中立的高性能三麻环境**上，把三个来自不同工程、互不相通的 Mortal 系三麻模型接入同一个对战器，跑三人 sanma 半庄循环赛，**首次得到三者在同一裁判下的真实强度关系**。

为什么需要它：三个模型各自只有自己的原生 arena（v8 用同事 `libriichi-sanma` 的 `arena.py_vs_py`；joint-v2 用我们 `libriichi3p` 的 OneVsThree；community 只有推理 bot），**彼此从未在同一环境里直接对打过**。RiichiEnv 提供引擎无关的 MJAI 裁判层 ⇒ 公平对照。

## 2. 三个被测模型（详见 RESOURCES.md §模型）
| 模型 | 来源 | 引擎 | obs | action | 强度先验 |
|---|---|---|---|---|---|
| **v8** | 同事 gpuo `/root/sanma` | `libriichi-sanma`(fork) | 575×34 | 44 | 同事主线最强，但相对前代仅边际（见 Mortal3 `.claude/gpuo-coworker-progress.md`） |
| **joint-v2** | 我们 Mortal3 离线 SL | 我们 `libriichi3p --features joint` | (752,27) | 81 | 「训练有效·真实强度待标定」首个有意义基线 |
| **community** | 社区下载 | 社区 `libriichi3p` .so | 775×34 | 44 | 用户告知**较弱**，当下限参照 |

## 3. 核心设计决策（已定）
- **桥接层 = MJAI**，不是 obs/logits。三者 obs 维度/action 空间都不同，强行统一编码不可行也无必要。RiichiEnv `3p-red-half` 产出 3p MJAI 事件流；每个模型内部的 libriichi bot 自己把 MJAI 翻成自己的 obs、推理、回 MJAI 动作；RiichiEnv 用 `obs.select_action_from_mjai()` 收回。
- **每个模型 = 一个 MJAI 子进程引擎**。Mortal `bot.py` 本就是 stdin 读 mjai 事件行、stdout 出动作行的协议。子进程化的收益：① 三者各用各的 python/torch/.so，零版本冲突；② v8 在远端也能同构（远程子进程或先 fetch 到本地）；③ 崩溃隔离。代价：每步进程间通信开销（三麻对战量级可接受，必要时批量/常驻）。
- **裁判口径** 对齐 Mortal3/gpuo 既有评测：三人 avg placement（公平均 **2.00**，越低越强）、CRN 同 seed 对齐、半庄、`env.pts=[3,0,-3]` 顺位分。
- **不改上游 Rust**。所有接入代码（per-model MJAI 引擎 wrapper、对战 driver、配置）放本仓库我们专属的目录，不混进 `riichienv-*` 上游源码树。

## 4. 约束 / 红线
- 三模型权重/.so 是百 MB 级二进制 → **不入 git**，fetch 的 v8 资产放 gitignore 路径。
- 三麻 MJAI 方言一致性是**头号风险**：拔北(nukidora/北抜き)事件命名、dora_marker 数、三麻牌集（无 2–8 万）、座位编码。RiichiEnv 的 3p MJAI 必须与每个 libriichi 期望的 MJAI 完全对齐，否则 bot 会拒动作/崩。**接入第一步就是逐事件 smoke 验证**，而非直接跑万局。
- joint-v2 是 action 81 的 joint 变体（真实动作落在 44≤a<81），但映射在其 bot/engine 内部完成，MJAI 层透明——仍需 smoke 确认。
- 公平性：三模型推理设备/温度/greedy 口径需统一（默认 greedy argmax），否则强度不可比。

## 5. 与姊妹项目的关系
- 母项目 `../Mortal3`：三模型里有两个（joint-v2、community）的源头都在那；改三麻的工程经验、`libriichi3p` crate、MJAI 3p 契约（`Mortal3/.claude/MJAI_SCHEMA_3P.md`）是本项目对齐 MJAI 方言的**权威参照**。
- v8 调研快照在 `Mortal3/.claude/gpuo-coworker-progress.md`（含 v8 引擎/obs/arena 强度数据）。
