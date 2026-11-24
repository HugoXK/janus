from __future__ import annotations

import json
from pathlib import Path

import pytest

from janus.config import load_settings


def test_defaults(tmp_path: Path) -> None:
    settings = load_settings(config_path=tmp_path / "missing.toml", env={})
    assert settings.timezone == "UTC"
    assert settings.log_level == "INFO"
    assert settings.database.endswith("janus.db")


def test_environment_wins_over_defaults(tmp_path: Path) -> None:
    settings = load_settings(
        config_path=tmp_path / "missing.toml",
        env={
            "JANUS_HOME": str(tmp_path / "home"),
            "JANUS_DB": str(tmp_path / "janus.db"),
            "JANUS_TIMEZONE": "Asia/Shanghai",
            "JANUS_LOG_LEVEL": "debug",
            "TIINGO_API_KEY": "secret-tiingo",
        },
    )
    assert settings.home == tmp_path / "home"
    assert settings.database == str(tmp_path / "janus.db")
    assert settings.timezone == "Asia/Shanghai"
    assert settings.log_level == "DEBUG"
    assert settings.providers["tiingo_api_key"] == "secret-tiingo"


def test_toml_config_is_loaded(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        'timezone = "Asia/Shanghai"\n'
        'log_level = "warning"\n'
        "[providers]\n"
        'tiingo_api_key = "from-toml"\n'
        "[data]\n"
        'watchlist = ["ACME", "BETA"]\n'
    )
    settings = load_settings(config_path=config, env={})
    assert settings.timezone == "Asia/Shanghai"
    assert settings.log_level == "WARNING"
    assert settings.providers["tiingo_api_key"] == "from-toml"
    assert settings.data["watchlist"] == ["ACME", "BETA"]


def test_cli_overrides_win(tmp_path: Path) -> None:
    settings = load_settings(
        config_path=tmp_path / "missing.toml",
        env={"JANUS_TIMEZONE": "Asia/Shanghai"},
        overrides={"timezone": "Europe/London", "log_level": "ERROR"},
    )
    assert settings.timezone == "Europe/London"
    assert settings.log_level == "ERROR"


def test_invalid_timezone_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown timezone"):
        load_settings(
            config_path=tmp_path / "missing.toml",
            env={"JANUS_TIMEZONE": "Mars/Olympus"},
        )


def test_redacted_masks_provider_secrets(tmp_path: Path) -> None:
    settings = load_settings(
        config_path=tmp_path / "missing.toml",
        env={"TIINGO_API_KEY": "super-secret"},
    )
    redacted = settings.redacted()
    assert redacted["providers"]["tiingo_api_key"] == "***"
    assert "super-secret" not in json.dumps(redacted)


def test_doctor_is_honest_about_optional_config(tmp_path: Path) -> None:
    settings = load_settings(
        config_path=tmp_path / "missing.toml",
        env={"JANUS_HOME": str(tmp_path / "home")},
    )
    checks = {check.name: check for check in settings.doctor()}
    assert checks["home"].ok
    assert checks["database"].ok
    assert checks["timezone"].ok
    assert not checks["config"].ok
    assert not checks["config"].critical
    assert not checks["provider:tiingo_api_key"].ok
    assert not checks["provider:tiingo_api_key"].critical


def test_ensure_home_creates_the_directory(tmp_path: Path) -> None:
    settings = load_settings(
        config_path=tmp_path / "missing.toml",
        env={"JANUS_HOME": str(tmp_path / "nested" / "home")},
    )
    created = settings.ensure_home()
    assert created.is_dir()
