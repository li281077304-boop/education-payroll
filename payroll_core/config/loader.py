from __future__ import annotations

from pathlib import Path
from typing import Any

from .schema import PayrollConfig


def load_config(path: str | Path) -> PayrollConfig:
    """Load YAML without hiding parse errors or silently accepting another file."""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment error
        raise RuntimeError("PyYAML is required to load payroll configuration") from exc

    config_path = Path(path)
    with config_path.open(encoding="utf-8") as handle:
        raw: Any = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"Configuration must be a mapping: {config_path}")
    period = raw.get("period")
    if not isinstance(period, str) or not period:
        raise ValueError("Configuration requires a non-empty period")
    tolerance = float(raw.get("tolerance", 0.000001))
    rules = raw.get("rules", {})
    if not isinstance(rules, dict):
        raise ValueError("Configuration rules must be a mapping")
    excluded = raw.get("excluded_roles", [])
    if not isinstance(excluded, list) or not all(isinstance(v, str) for v in excluded):
        raise ValueError("excluded_roles must be a list of strings")
    return PayrollConfig(
        period=period,
        tolerance=tolerance,
        rules=rules,
        excluded_roles=tuple(excluded),
    )
