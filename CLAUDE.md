# CLAUDE.md — RiichiEnv 三麻「三模型公共对战器」接入项目（入口）

> 本文件是 Claude Code 每次会话**自动加载**的项目记忆。详情在 `.claude/` 下，本文件只放「立刻要知道的」+ 指向。

## 这是什么项目
- 上游：[smly/RiichiEnv](https://github.com/smly/riichienv)，Rust(`riichienv-core`) + Python(maturin) 的高性能麻将环境，**Gym 式 API + 原生支持三麻(sanma) + MJAI 协议 + Mortal Bot 兼容**（README 称已在 100 万+ 半庄无错跑通 MortalAgent）。本仓库是其本地克隆（`git clone` 于 2026-06-29，HEAD `b1d08b3`）。
- **本项目不改上游引擎**。我们把 RiichiEnv 当作**中立的三麻公共对战器**，把三个来自不同工程、互不相通的 Mortal 系三麻模型接进来，做一次真正 apples-to-apples 的三人对战评测。
- **姊妹项目**：母项目是 Mortal3（把 Mortal 改三麻 + 训练），再往上是 Mortal（4p 复刻）；三个 repo 同在 `~/Workspace.code-workspace` / `~/Workspace-side.code-workspace`。完整姊妹项目地图见 `~/.claude/CLAUDE.md`。

## 🎯 核心任务（change-001）
把下面**三个三麻模型**接入 RiichiEnv 对战器，跑三人 sanma 半庄循环赛，得出三者真实强度关系：
1. **v8**（同事 gpuo 服务器）：`libriichi-sanma` 引擎（575ch×34 / action 44），权重 `gpuo:/root/sanma/runs/v8_bc/model.pth`。
2. **joint-v2**（我们 Mortal3 离线 SL 成品）：我们的 `libriichi3p`（`--features joint`，obs(752,27) / action 81），权重 `../Mortal3/train/sl3p-joint-v2/archive/mortal.final.pth`。
3. **community**（社区较弱 3麻权重）：社区 `libriichi3p` .so（775ch×34 / action 44），权重 `../Mortal3/community_3p/v0.1.0/mortal.pth`。

**关键洞察**：三者 obs 维度（575/752/775）、action（44/81）、引擎各不相同，**但都说 3p MJAI（含拔北 nukidora）**，而 RiichiEnv `game_mode="3p-red-half"` 正好产出 3p MJAI。⇒ **桥接点在 MJAI 层，不必统一三者 obs/action**。每个模型作为一个 **MJAI 子进程引擎**（Mortal `bot.py` 本就 stdin 读 mjai 事件、stdout 出动作），由 RiichiEnv 驱动：`obs.new_events()` → 引擎 stdin → 读 MJAI 动作 → `obs.select_action_from_mjai(resp)`。子进程化彻底回避三者 python/torch/.so 版本冲突。

详细规格、续点、DoD 见 **`.claude/specs/change-001-3way-arena.md`**。

## 🔴 跨会话工作协议（每个会话必读必做）
1. **开工先读**：`.claude/STATUS.md`（当前进度/下一步）→ 需要背景查 `.claude/PROJECT.md`（目标/约束）、`.claude/RESOURCES.md`（三模型资产/RiichiEnv 接口/环境）。要动接入代码先看相关 `.claude/specs/`。
2. **收工前更新** `.claude/STATUS.md`：本会话详情写进新的 `.claude/sessions/c<下一编号>.md`，在 STATUS「会话日志」补一行（一句话 + `[详情]` 链接），刷新「当前状态/下一步」；主题在 `sessions/INDEX.md` 追加 `cNN`。

## `.claude/` 文档地图
| 文件 | 作用 |
|---|---|
| `README.md` | 文件夹索引 + 阅读顺序 |
| `STATUS.md` | **活文档**：当前状态、产物、下一步、会话日志（只一行索引） |
| `sessions/cNN.md` | 每个会话的详情存档 |
| `sessions/INDEX.md` | 主题→会话二级索引 |
| `specs/change-NNN-*.md` | 可续执行规格（带 DoD/续点） |
| `PROJECT.md` | 项目目标 + 已定结论 + 约束 |
| `RESOURCES.md` | 三模型资产 / RiichiEnv 接口 / 上游 / 环境要点 |

## RiichiEnv 关键接口（接入会用到，承上游 README）
```python
from riichienv import RiichiEnv, GameRule
env = RiichiEnv(game_mode="3p-red-half", rule=GameRule.default_tenhou())  # 三麻半庄 天凤规则
obs_dict = env.reset()                       # {player_id: Observation}
while not env.done():
    actions = {pid: agent.act(obs) for pid, obs in obs_dict.items()}
    obs_dict = env.step(actions)
print(env.scores(), env.ranks())
```
- `obs.new_events() -> list[str]`：自上次观测以来的新 MJAI JSON 事件（喂给各模型 bot）。
- `obs.select_action_from_mjai({"type":"dahai",...}) -> Action`：把模型回的 MJAI 动作映射成合法 `Action`（**这是接 Mortal 系模型的关键桥**）。
- 原生 `riichienv_ml.agents.Agent` 走 RiichiEnv 自带编码器(feat_v1/2/3)+`obs.mask()`/`obs.find_action(idx)`——**仅适用 RiichiEnv 原生训练的模型，不适用我们三个 Mortal 模型**（它们用各自 libriichi obs）。

## ⚠ 服务器环境铁律（c05 血泪，务必遵守）
**在 gpu-16/远端跑这些项目，一律用既有「真环境」`~/aigc_apps/venv`（py3.12，带 torch + 现代 pip + 全依赖），不要新建空白 `python3.10 -m venv` 去较劲。** 空白 venv 的老 pip 不认 maturin 的 `pip install --group`（需 pip≥25.1）、`pip install -U pip` 走国内镜像会装坏 pip——c05 在这上面耗了大量时间。
- 三引擎（joint/community/v8）+ riichienv 父进程**同住 aigc 3.12**（模块名 libriichi3p/libriichi/libriichi_sanma/riichienv 互不冲突）；父进程与引擎都用 `~/aigc_apps/venv/bin/python`，置 `ARENA_ENGINE_PY=~/aigc_apps/venv/bin/python`。
- gpu-16 装 riichienv：`cd ~/riichienv && PATH=$HOME/.cargo/bin:$PATH RUSTUP_TOOLCHAIN=stable ~/aigc_apps/venv/bin/maturin build --release -i ~/aigc_apps/venv/bin/python` → `~/aigc_apps/venv/bin/python -m pip install <cp312 wheel>`。（`RUSTUP_TOOLCHAIN=stable` 绕开 repo 钉的、装坏过的 rust 1.92 toolchain；`build -i` 出 cp312 wheel 再普通 pip install，避开 `--group`、不动 aigc 真环境的 pip。cargo 走 rsproxy.cn 镜像很快。）
- 本地↔服务器传大文件极慢（~30kB/s）：权重等大资产**打包让用户传**，别直接 scp/rsync 大二进制。
- **同样适用于姊妹项目 Mortal / Mortal3 / autoplay / learnrust / zeroppo**（共用这些服务器，都用 aigc 真环境）。

## 约定
- 中文交流与文档（同 Mortal3）。
- 不修改上游 Rust 引擎；接入代码、配置、文档放本仓库专属位置（见 specs，避免污染上游目录）。
- 所有「会变的事实」（路径、机器、数据量、跑分）写进 `STATUS.md`，不散落对话。
- 完成一个节点（DoD 达成、验证通过）即在当前分支 `git commit`；`push` 前先问。
- ⚠ 三模型权重/.so 体积大（百 MB 级），勿入 git；fetch 来的 v8 资产放 gitignore 路径。
