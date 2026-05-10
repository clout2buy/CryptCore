"""Best-effort secret redaction for tool outputs."""
from __future__ import annotations

import os
import re
from copy import deepcopy


_SECRET_NAME_RE = re.compile(r"(key|token|secret|password|credential)", re.I)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?im)^(\s*(?:\d+\s*(?:\u2192|->|=>))?\s*[A-Z0-9_.-]*"
    r"(?:TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|APIKEY|AUTH(?:ORIZATION)?|"
    r"CREDENTIAL|WEBHOOK|PRIVATE[_-]?KEY)"
    r"[A-Z0-9_.-]*\s*[:=]\s*)(.+?)\s*$"
)
_GENERIC_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\b[MN][A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{20,}\b"),
]


def text(value: str) -> str:
    out = str(value)
    for secret in _env_secrets():
        out = out.replace(secret, "[redacted]")
    out = _SECRET_ASSIGNMENT_RE.sub(r"\1[redacted]", out)
    for pattern in _GENERIC_PATTERNS:
        out = pattern.sub("[redacted]", out)
    return out


def content(value):
    if isinstance(value, str):
        return text(value)
    if isinstance(value, list):
        cloned = deepcopy(value)
        for item in cloned:
            _redact_in_place(item)
        return cloned
    if isinstance(value, dict):
        cloned = deepcopy(value)
        _redact_in_place(cloned)
        return cloned
    return value


def _redact_in_place(value) -> None:
    if isinstance(value, dict):
        for key, child in list(value.items()):
            if key == "data":
                # Native media payloads are base64 data, not prompt text.
                continue
            if isinstance(child, str):
                value[key] = text(child)
            else:
                _redact_in_place(child)
    elif isinstance(value, list):
        for i, child in enumerate(value):
            if isinstance(child, str):
                value[i] = text(child)
            else:
                _redact_in_place(child)


def _env_secrets() -> list[str]:
    secrets: list[str] = []
    for name, value in os.environ.items():
        if not value or len(value) < 8:
            continue
        if _SECRET_NAME_RE.search(name):
            secrets.append(value)
    secrets.sort(key=len, reverse=True)
    return secrets
