"""arena3p.engines — 每个被测模型 = 一个 MJAI 子进程引擎。

父进程侧（.venv，有 riichienv）：base / subprocess_engine / registry。
子进程侧（各模型匹配的 torch+.so python）：mjai_runner。
两侧不互相 import，只经 stdin/stdout 传 MJAI JSON。本 __init__ 故意留空以免触发跨侧导入。
"""
