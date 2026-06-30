# change-002 — 第二测试任务：2×joint-mse vs 1×v8guard 座位轮转复式 30k

状态：**接入完成 + 等价性验证 100% PASS** → gpu-16 部署中（资产传输 + 30k 跑）。创建：2026-06-30（c06）

## intent
在 change-001 的 RiichiEnv 中立三麻 arena 上，跑**复式 2v1**对战得真实强弱：
- **2 座** = `joint-mse`：我们 Mortal3 在线训练 joint 成品，权重 `../Mortal3/train/sl3p-joint-result/3p-mse-v1.1.pth`（v1.1=80k 步，2026-06-30 在线训练完成）。
- **1 座** = `v8guard`：同事 `../Mortal3/train/sanma_v8_guard/` 完整包 = v8 BC backbone + **danger head + mitoshi 防守 guard（guard 开）**。
- **30000 半庄**（= 10000 seed × 3 循环轮转座次），座位完全平衡。

与 change-001 步骤5（joint-v2/community/v8 三不同模型）的区别：①joint 换在线训练新权重 3p-mse-v1.1；②v8 换成**带 guard** 的 sanma_v8_guard（c04 接的是 guard 关的 v8_bc）；③**2v1 复式**（非 3 不同模型）。

## 关键事实（探查实测，c06）
- **3p-mse-v1.1 与 joint-v2 同构**：version=4 / conv_channels=192 / num_blocks=40 / 同 `config`+`mortal`+`current_dqn` keys ⇒ 直接复用 joint 引擎（libriichi3p `--features joint`，obs752/AS81），仅换权重路径。「相关 mjai 接口已完备」即此意。
- **v8guard = sanma_v8_guard 包**：`model/net.py` 是 **44-action build**（带 `.features()` / `SanmaDangerHead`），`features/consts.py` N_ACTIONS=44，`engine/libriichi_sanma.so`，`runs/v8_bc/model.pth`(97M, =c04 fetch 的 v8 BC, md5 同) + `runs/v8_danger/danger_head.pth`(13M) + `runs/v8_danger_suit4/danger_head.pth`(13M, 更新版) + `local_model/`（guard helpers + sanma_joint_api.py）。
- **guard 推理路径** = 同事 `local_model/sanma_joint_api.py::SanmaV8GuardEngine`（GUARD ON）：`features→head` 得 logits + `sigmoid(danger_head(phi))` 得每张放铳风险；在自家弃牌点用 `mitoshi_sanma_guard.sanma_guard`（不退向听 ∩ 枚数小让≤margin ∩ danger 显著更低≥gap → 换更安全张）+ 赤dora 保护 + Q 保护。sanma 标定参数 **floor=0.10 / gap=0.05 / margin=2 / aka_gap=0.25 / Q_gap=1.0**（非函数默认 0.15/0.08）。reach_suppress / tenpai_rescue 默认**关**（故 arena 无需 /decide 层的 pending_*）。
- **danger head 选用 `v8_danger`**（= sanma_joint_api 钉死默认）；另有 `v8_danger_suit4`(6.29 更新) 经 `ARENA_V8_DANGER` 一行可换（结构同，仅训练版本不同）。

## 接入（全在 arena3p/，复用 change-001 子进程框架）
- `engines/mjai_runner.py`：
  - `build_joint_bot` 权重参数化：`ARENA_JOINT_WEIGHT`（默认 joint-v2，本任务=3p-mse-v1.1）。
  - **新增 `build_v8guard_bot`**：精确复刻 `SanmaV8GuardEngine` 的 defense-guard 路径（backbone+danger head+sanma_guard+aka/Q 保护）。guard 参数读 env（`SANMA_GUARD_FLOOR/GAP/MARGIN/AKA_GAP/Q_GAP`，**与同事同名同默认** → 正式跑等价；可临时设宽松值压测）。资产经 `ARENA_V8GUARD_DIR` + `ARENA_V8_DANGER`。
- `engines/registry.py`：加 `joint-mse`（joint 引擎 + ARENA_JOINT_WEIGHT）+ `v8guard`（ARENA_V8GUARD_DIR/ARENA_V8_DANGER）。两者 dialect=standard（原生 3 座 + nukidora）。
- `run_eval.py`：`_seatings` 放宽支持 **2v1 轮转**（`[a,a,b]` 循环旋转 → `[a,a,b]/[a,b,a]/[b,a,a]`，单一模型 b 轮坐每座各 1 次、a 占其余 2 座各 2 次 → 座位完全平衡）。
- `engines/subprocess_engine.py`：加 `record` 开关（录 `(视角事件流, mjai动作)` tape，供 review）。

## 验证（DoD = 「拿牌谱分别去两模型原版 review，一致率 100%」）✅ PASS
`arena3p/review/`：①`gen_tapes.py` 跑 arena（真子进程链路）录每座 tape + god-view 牌谱；②`replay_truth.py` 分模型分进程用**各模型工程的独立/原版推理代码**重放 tape 逐决策点比对（避免循环论证：v8guard 用同事 `sanma_joint_api.SanmaV8GuardEngine` **原版**、joint 用独立原生加载 = mortal.py review_mode=0 同配置）。同进程不能同时 import joint/v8guard 的同名 `model` 包，故分进程。

| 验证 | 决策点/样本 | 结果 |
|---|---|---|
| 默认配置（实战）joint×2 seat0/1 + v8guard seat2 | 2250+2253+2236=6739 | **100% 一致, select_fail=0** |
| 宽松压测 v8guard（floor=0/gap=0/margin=99，强制 guard 换牌）seat0/1/2 | 2235+2225+2230=6690 | **100%**，guard 换牌 440 + Q 保护 1565 + aka 保护 6 全覆盖 |
| helper 穷举对拍 `slot_to_t34`(44) + `aka_protect_skip`(335405) | 335449 组 | **全等** |

⇒ arena 接入的两模型与各自原版逐决策点**零偏差**。牌谱守恒（Σscore=105000）/ranks 合法/select 全匹配。

## gpu-16 部署
- gpu-16 已有：aigc venv（py3.12 + riichienv-0.4.8 cp312）、arena3p 代码（c06 rsync）、`_pkgs/v8/model.pth`(=v8_bc, md5 同)。
- 需传：`3p-mse-v1.1.pth`(121M) → `~/Mortal3/train/sl3p-joint-result/`；`sanma_v8_guard_nov8bc.tgz`(26M, 排除已有 v8_bc) → 解压 `~/Mortal3/train/` 后把 `_pkgs/v8/model.pth` 软链/拷到 `sanma_v8_guard/runs/v8_bc/model.pth`。
- 跑法（aigc 真环境，铁律）：
  ```
  ARENA_ENGINE_PY=~/aigc_apps/venv/bin/python ARENA_MORTAL3=~/Mortal3 \
  ~/aigc_apps/venv/bin/python arena3p/run_eval.py \
    --players joint-mse,joint-mse,v8guard --rotate \
    --n 10000 --seed0 <S> --workers 26 --resume \
    --log-dir arena3p/eval_runs/c002_2v1_30k
  ```
- 统计（2v1 同名聚合）：`stat_report.py --rotate` 按模型名 `Stat.from_dir`；**须验证 Stat 对同名多座（joint 占 2 座、names=["joint-mse","joint-mse","v8guard"]）是全聚合**（joint.game 应=2×v8guard.game）；否则用 summary.jsonl 直算 avg_rank（主指标，按模型聚合全部座位样本，精确无偏）。

## DoD
- [x] joint-mse + v8guard 接入，本机 arena 跑通（守恒/ranks/select 全合法）。
- [x] review 等价性 100%（默认 + guard 全路径压测 + helper 穷举）。
- [x] gpu-16 资产就位 + smoke 通过。
- [x] 30k 跑完，出 2v1 强弱（avg_rank/avg_pt + 细分指标）。

## 最终结论（30000 半庄座位轮转复式，2026-06-30 gpu-16，157.6min @190 半庄/min）
存 `eval_runs/c002_2v1_30k/stat_2v1_30k.txt`。样本：joint-mse 60000 座 = 2×v8guard 30000 座（2v1 轮转，每座样本相等，座位完全平衡）。

| 模型 | 座样本 | avg_rank | avg_pt | 1st% | 2nd% | 3rd% | 和率 | 放铳率 | 立直率 | 立直后和率 |
|---|---|---|---|---|---|---|---|---|---|---|
| **joint-mse** ×2座 | 60000 | **1.9998** ±.0033 | **−0.162** ±.087 | 32.93% | 34.14% | 32.92% | 28.42% | **13.78%** | 23.02% | **53.0%** |
| **v8guard** ×1座 | 30000 | **2.0003** ±.0048 | **+0.288** ±.127 | 34.13% | 31.71% | 34.16% | 29.23% | 15.42% | 27.35% | 51.4% |

- **avg_rank 实质平手**（1.9998 vs 2.0003，差 0.0005 << 噪声 ±.003~.005）。tenhou 主指标顺位上二者打平。
- **avg_pt：v8guard 微正 +0.288(≈2.3σ)、joint 微负 −0.162**；2×(−0.162)+(+0.288)≈0（零和自洽）。faint 信号 = v8guard 每局略多收点（与其激进一致），但仅 ~2σ，不构成强结论。
- **风格对比**（去座位混淆）：v8guard = 激进（立直 27.4% vs 23.0%、和率 29.2% vs 28.4%、放铳 15.4% vs 13.8%、1st/3rd 双高=波动大）；joint-mse = 稳健（放铳最低 13.8%、2nd 最多 34.1%、立直后和率更高 53.0%）。延续 change-001「joint 稳/v8 凶、强弱极接近」的格局——guard 加在 v8 上 + joint 换在线 mse 权重后，**仍是顺位平手、点数 v8guard 微弱占优**。

## 续点
- 已完成。danger head 用 `v8_danger`；若要 `v8_danger_suit4` 改 registry 的 `ARENA_V8_DANGER` 一行重跑。
