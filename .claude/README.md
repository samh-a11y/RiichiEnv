# `.claude/` — RiichiEnv 三模型对战器接入项目文档

本文件夹是本项目（在 RiichiEnv 上接入 Mortal3 / v8 / community 三麻模型做对战）的工作记忆。上游 RiichiEnv 自带的 `docs/`（FEATURE_ENCODING / RULES / …）是引擎文档，**与此处互不覆盖**：`docs/` 讲引擎怎么用，`.claude/` 讲我们的接入任务怎么推进。

## 阅读顺序
1. `../CLAUDE.md` —— 项目入口（自动加载），先看它。
2. `STATUS.md` —— 当前进度 / 产物 / 下一步（**每次开工必读**）。
3. `specs/change-001-3way-arena.md` —— 核心任务规格（接入设计 + DoD + 续点）。
4. 需要背景：`PROJECT.md`（目标/约束/已定结论）、`RESOURCES.md`（三模型资产 + RiichiEnv 接口 + 环境）。
5. 找某主题的来龙去脉：`sessions/INDEX.md` → 对应 `sessions/cNN.md`。

## 维护
- 收工更新 `STATUS.md` + 新建 `sessions/cNN.md` + `sessions/INDEX.md` 追加行（见 `../CLAUDE.md` §跨会话工作协议）。
- 文件结构变化时更新本 README。
