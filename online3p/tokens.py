#!/usr/bin/env python3
"""从 riichi.md 读取平台下发的 bot JWT，按 name 索引（change-003 在线对战接入）。

riichi.md 每个 JWT 独占一行（标准三段式 ``eyJ...eyJ...``）；payload 里
``name`` 字段 = 平台上的 bot 名（Nosam / Mason）。仅本地解码取 name，不做
签名校验（签名由平台服务端验）。⚠ 该文件含长期有效凭证，勿入 git。
"""
from __future__ import annotations

import base64
import json
import re

_JWT_RE = re.compile(r"eyJ[\w-]+\.eyJ[\w-]+\.[\w-]+")


def decode_payload(jwt: str) -> dict:
    """JWT → payload dict（base64url，补齐 padding）。"""
    seg = jwt.split(".")[1]
    seg += "=" * (-len(seg) % 4)
    return json.loads(base64.urlsafe_b64decode(seg))


def token_name(jwt: str) -> str | None:
    """JWT payload 里的 bot 名。"""
    try:
        return decode_payload(jwt).get("name")
    except Exception:  # noqa: BLE001
        return None


def load_tokens(path: str) -> dict[str, str]:
    """riichi.md → {bot 名: JWT}。"""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    out: dict[str, str] = {}
    for m in _JWT_RE.finditer(text):
        jwt = m.group(0)
        name = token_name(jwt)
        if name:
            out[name] = jwt
    return out
