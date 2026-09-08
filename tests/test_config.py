from pathlib import Path

from payroll_core.config.loader import load_config


ROOT = Path(__file__).parents[1]


def test_default_config_loads():
    config = load_config(ROOT / "config" / "default.yaml")
    assert config.period == "2026-08"
    assert config.active_adjustments() == ()


def test_effective_period_config_is_selected():
    config = load_config(ROOT / "config" / "example_2026_08.yaml")
    assert len(config.active_adjustments()) == 1
    later = config.__class__(period="2026-09", rules=config.rules)
    assert later.active_adjustments() == ()
