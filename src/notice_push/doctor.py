from __future__ import annotations

import os
from pathlib import Path

import yaml

from src.notice_push.models import AppConfig
from src.notice_push.storage_migrations import BASELINE_SCHEMA_VERSION
from src.notice_push.storage import NoticeStorage
from src.notice_push.summary_validator import REQUIRED_SUMMARY_FIELDS


def run_doctor(config: AppConfig) -> tuple[str, ...]:
    findings: list[str] = []
    _check_runtime_config(config, findings)
    _check_workflow_yaml(config, findings)
    _check_prompt(config, findings)
    _check_media_policy(config, findings)
    _check_state_parent(config, findings)
    _check_sources(config, findings)
    _check_api_keys(config, findings)
    _check_sqlite_health(config, findings)
    return tuple(findings)


def has_doctor_errors(findings: tuple[str, ...]) -> bool:
    return any(finding.startswith("error:") for finding in findings)


def _check_prompt(config: AppConfig, findings: list[str]) -> None:
    prompt_path = config.repo_root / "resources" / "prompts" / f"{config.prompt_name}.md"
    if not prompt_path.exists():
        findings.append(f"error: prompt file not found: {prompt_path}")
        return
    prompt_text = prompt_path.read_text(encoding="utf-8")
    missing_fields = [field for field in REQUIRED_SUMMARY_FIELDS if f"**{field}**" not in prompt_text]
    if missing_fields:
        findings.append(f"error: prompt missing summary fields: {', '.join(missing_fields)}")


def _check_runtime_config(config: AppConfig, findings: list[str]) -> None:
    runtime_path = config.repo_root / "resources" / "config" / "runtime.yml"
    if not runtime_path.exists():
        findings.append(f"error: runtime config not found: {runtime_path}")
        return
    try:
        yaml.safe_load(runtime_path.read_text(encoding="utf-8"))
    except Exception as exc:
        findings.append(f"error: runtime config YAML parse failed: {exc}")


def _check_workflow_yaml(config: AppConfig, findings: list[str]) -> None:
    workflow_dir = config.repo_root / ".github" / "workflows"
    for workflow_name in ("daily_report.yml", "ci.yml"):
        workflow_path = workflow_dir / workflow_name
        if not workflow_path.exists():
            findings.append(f"error: workflow file not found: {workflow_path}")
            continue
        try:
            yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        except Exception as exc:
            findings.append(f"error: workflow YAML parse failed: {workflow_path}: {exc}")


def _check_media_policy(config: AppConfig, findings: list[str]) -> None:
    values = {
        "media.pdf_max_bytes": config.media_policy.pdf_max_bytes,
        "media.image_max_bytes": config.media_policy.image_max_bytes,
        "media.pdf_extracted_text_max_chars": config.media_policy.pdf_extracted_text_max_chars,
    }
    invalid = [name for name, value in values.items() if value <= 0]
    if invalid:
        findings.append(f"error: media policy values must be positive: {', '.join(invalid)}")


def _check_state_parent(config: AppConfig, findings: list[str]) -> None:
    try:
        config.state_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        findings.append(f"error: state path parent is not writable: {config.state_path.parent}: {exc}")


def _check_sources(config: AppConfig, findings: list[str]) -> None:
    enabled_sources = [source for source in config.sources if source.enabled]
    if not enabled_sources:
        findings.append("error: no enabled sources")
        return

    for source in enabled_sources:
        missing_fields = [
            field
            for field in ("name", "base_url", "list_url", "adapter")
            if not str(getattr(source, field, "")).strip()
        ]
        if missing_fields:
            findings.append(f"error: source {source.id} missing fields: {', '.join(missing_fields)}")


def _check_api_keys(config: AppConfig, findings: list[str]) -> None:
    for provider in config.llm_providers.values():
        if not os.getenv(provider.api_key_env, "").strip():
            findings.append(f"warning: {provider.api_key_env} is not set")


def _check_sqlite_health(config: AppConfig, findings: list[str]) -> None:
    if not Path(config.state_path).exists():
        return
    try:
        health = NoticeStorage(config.state_path, config.sources).health_check()
    except Exception as exc:
        findings.append(f"error: SQLite health check failed: {exc}")
        return
    if BASELINE_SCHEMA_VERSION not in health.schema_versions:
        findings.append(f"error: SQLite schema migration missing: {BASELINE_SCHEMA_VERSION}")
