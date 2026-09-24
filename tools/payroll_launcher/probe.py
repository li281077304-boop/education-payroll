"""Identify whatever is listening on the Payroll port.

The launcher must never assume that "the port answers" means "our service is
running".  Every start decision goes through this probe first.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from payroll_ui.health import APP_ID, HEALTH_CONTRACT, HEALTH_PATH, SERVICE_ID, data_dir_fingerprint


class ProbeKind(str, Enum):
    ABSENT = "absent"                     # nothing is listening
    OURS = "ours"                         # our service, on our data directory
    OTHER_DATA = "other_data"             # our service, different data dir
    FOREIGN = "foreign"                   # something else owns the port


@dataclass(frozen=True)
class ProbeResult:
    kind: ProbeKind
    detail: str = ""
    payload: dict | None = None

    @property
    def pid(self) -> int | None:
        payload = self.payload or {}
        pid = payload.get("pid")
        return int(pid) if isinstance(pid, int) else None


def probe(host: str, port: int, data_dir: Path, timeout: float = 0.8) -> ProbeResult:
    """Classify the process on ``host:port`` without side effects."""
    expected = data_dir_fingerprint(data_dir)
    url = f"http://{host}:{port}{HEALTH_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                return ProbeResult(ProbeKind.FOREIGN, f"端口返回状态 {response.status}")
            raw = response.read()
    except urllib.error.HTTPError as exc:
        return ProbeResult(ProbeKind.FOREIGN, f"端口返回状态 {exc.code}")
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, ConnectionRefusedError):
            return ProbeResult(ProbeKind.ABSENT, "端口没有服务监听")
        return ProbeResult(ProbeKind.ABSENT, f"端口没有响应：{reason}")

    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return ProbeResult(ProbeKind.FOREIGN, "端口上的程序不是工资核算服务")

    if not isinstance(payload, dict):
        return ProbeResult(ProbeKind.FOREIGN, "端口上的程序不是工资核算服务")
    if payload.get("contract") != HEALTH_CONTRACT or payload.get("app") != APP_ID or payload.get("service") != SERVICE_ID:
        return ProbeResult(ProbeKind.FOREIGN, "端口已被其它程序占用", payload)

    if payload.get("data_dir_fingerprint") != expected:
        return ProbeResult(ProbeKind.OTHER_DATA, "工资服务正在使用另一个数据目录", payload)

    return ProbeResult(ProbeKind.OURS, "工资核算服务已在运行", payload)
