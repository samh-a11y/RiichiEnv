# sessions INDEX — 主题 → 会话二级索引

> 按主题找回起源。时间序日志在 `STATUS.md` §会话日志。

| 主题 | 会话 |
|---|---|
| 项目初始化（clone + workspace 接入 + 文档系统） | c01 |
| change-001 三模型对战器接入（MJAI 桥 / 子进程引擎） | c01（规格化） |
| MJAI 三麻方言对齐 | c02（步骤0+1，kita↔nukidora）；c03（修正：community 是 4 座掩码格式） |
| arena 对战框架（统一 MJAI 子进程 runner + run_arena） | c03 |
| community 引擎适配器 | c03（4 座 padding + symlink package） |
| joint-v2 引擎适配器 | c03（原生 3 座，仅 kita↔nukidora） |
| v8 引擎适配器 | c04（mjai.Bot 同构 / .so abi3 跑 py3.12 / 方言 standard / 引擎双 smoke）；c05（gpu-16 aigc 3.12 部署） |
| 大样本评测 + 复现 Mortal 指标（run_eval/stat_report/可视化） | c03 末（commit 7e2a667）；c04（fixed-seat 6302）；c05（rotate 12000） |
| 三方循环赛 + 强度报告 | c05 ✅（座位轮转复式 12000 局：joint>v8>community 极接近） |
| gpu-16 部署 + 服务器环境铁律（aigc 3.12，别空白 python3.10） | c05（commit 3798431；CLAUDE.md + 记忆） |
| change-002 第二测试任务（2×joint-mse vs 1×v8guard 复式 30k） | c06（接入 build_v8guard_bot 复刻同事 guard + 2v1 轮转） |
| 接入等价性验证（牌谱去原版模型 review 一致率 100%） | c06（gen_tapes/replay_truth + guard 压测 + helper 穷举对拍） |
| change-003 qgrp v3 接入在线对战（MJAI over WebSocket） | c07（online3p 客户端 + mock 平台 + 端到端冒烟全绿） |
| 双 bot 协作 EV（同桌 0.5·self−0.5·third；qgrp ev.py set_coop） | c07（数值 max\|err\|=0 + mock coop ON/OFF 两分支） |
| 在线对战环境坑（aigc venv riichienv 空 namespace，真 riichienv 在仓 .venv） | c07 |
| 真机 ankan 兜底误判非法回退（服务器合法集带冗余 pai / `_match` 镜像 select_action） | c08（`_match` ankan/kita 只比 consumed + `test_action_match.py`） |
| 红5「模型不认识」（possible_actions 折叠手牌红5→`5p`，服务器仍收 `5pr`；`_deaka` 归一化 dahai） | c08（实现 `_deaka`）；c09（真机探针坐实折叠+服务器照收 `5pr` + 带修复重启上线） |
| level/aggr 剥削旋钮 / end_game 立即重排 / 原始帧诊断（RIICHI_RAW） | c08 |
