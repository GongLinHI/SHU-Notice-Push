from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.usefixtures("seed_runtime_config_for_temporary_repo")

from notice_push.settings.loader import load_config


def _runtime_path(root: Path) -> Path:
    return root / "resources" / "config" / "runtime.yml"


def _payload(root: Path) -> dict:
    return yaml.safe_load(_runtime_path(root).read_text(encoding="utf-8"))


def _write(root: Path, payload: dict) -> None:
    _runtime_path(root).write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _set(payload: dict, path: str, value) -> None:
    target = payload
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


def test_load_config_rejects_missing_runtime_file(tmp_path):
    _runtime_path(tmp_path).unlink()

    with pytest.raises(ValueError, match="Runtime config file is missing"):
        load_config(repo_root=tmp_path, env={})


def test_load_config_rejects_empty_source_definitions(tmp_path):
    payload = _payload(tmp_path)
    payload["sources"] = {}
    _write(tmp_path, payload)

    with pytest.raises(ValueError, match="sources must contain at least one source"):
        load_config(repo_root=tmp_path, env={})


def test_load_config_does_not_restore_removed_builtin_source(tmp_path):
    payload = _payload(tmp_path)
    payload["sources"] = {
        "custom": {
            "name": "Custom",
            "base_url": "https://example.edu/",
            "list_url": "https://example.edu/notices",
            "adapter": "example.CustomAdapter",
            "enabled": True,
        }
    }
    _write(tmp_path, payload)

    config = load_config(repo_root=tmp_path, env={})

    assert [source.id for source in config.sources] == ["custom"]


def test_load_config_does_not_restore_removed_builtin_provider(tmp_path):
    payload = _payload(tmp_path)
    payload["llm"]["providers"] = {
        "custom": {
            "base_url": "https://llm.example/v1",
            "api_key_env": "CUSTOM_API_KEY",
            "model_env": "CUSTOM_MODEL",
            "default_model": "custom-model",
            "kind": "openai_text",
        }
    }
    payload["llm"]["routing"] = {"text": "custom", "pdf": "custom", "image": "custom"}
    _write(tmp_path, payload)

    config = load_config(repo_root=tmp_path, env={})

    assert set(config.llm_providers) == {"custom"}


def test_load_config_supports_dotted_source_and_provider_ids(tmp_path):
    payload = _payload(tmp_path)
    payload["sources"] = {
        "custom.source": {
            "name": "Custom",
            "base_url": "https://example.edu/",
            "list_url": "https://example.edu/notices",
            "adapter": "example.CustomAdapter",
            "enabled": True,
        }
    }
    payload["llm"]["providers"] = {
        "openai.compat": {
            "base_url": "https://llm.example/v1",
            "api_key_env": "CUSTOM_API_KEY",
            "model_env": "CUSTOM_MODEL",
            "default_model": "custom-model",
            "kind": "openai_text",
        }
    }
    payload["llm"]["routing"] = {
        "text": "openai.compat",
        "pdf": "openai.compat",
        "image": "openai.compat",
    }
    _write(tmp_path, payload)

    config = load_config(repo_root=tmp_path, env={})

    assert [source.id for source in config.sources] == ["custom.source"]
    assert set(config.llm_providers) == {"openai.compat"}


def test_load_config_reports_full_path_for_missing_profile_field(tmp_path):
    payload = _payload(tmp_path)
    del payload["profiles"]["daily"]["http_timeout"]
    _write(tmp_path, payload)

    with pytest.raises(ValueError, match="profiles.daily.http_timeout is required"):
        load_config(repo_root=tmp_path, env={})


def test_load_config_reports_full_path_for_invalid_field_type(tmp_path):
    payload = _payload(tmp_path)
    payload["media"]["pdf_max_bytes"] = "many"
    _write(tmp_path, payload)

    with pytest.raises(ValueError, match="media.pdf_max_bytes must be an integer"):
        load_config(repo_root=tmp_path, env={})


@pytest.mark.parametrize(
    ("path", "value", "minimum"),
    [
        ("profiles.daily.max_pages_per_source", -1, 1),
        ("profiles.daily.detail_max_workers", 0, 1),
        ("profiles.daily.http_max_retries", -1, 0),
        ("profiles.daily.http_max_retry_delay_seconds", 0, 1),
        ("profiles.daily.http_retry_backoff", 0.5, 1),
        ("profiles.daily.llm_retry_backoff", 0.5, 1),
        ("media.pdf_max_bytes", 0, 1),
        ("audit.sample_detail_count", 0, 1),
        ("detail_min_chars", 0, 1),
        ("llm.summary_format_repair_retries", -1, 0),
    ],
)
def test_load_config_rejects_values_below_runtime_boundaries(tmp_path, path, value, minimum):
    payload = _payload(tmp_path)
    _set(payload, path, value)
    _write(tmp_path, payload)

    with pytest.raises(ValueError) as exc_info:
        load_config(repo_root=tmp_path, env={})

    assert str(exc_info.value) == f"{path} must be at least {minimum}"
