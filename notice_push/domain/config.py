from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from notice_push.domain.audit import AuditPolicy
from notice_push.domain.notices import NoticeSource
from notice_push.domain.runtime import LLMProviderConfig, MediaPolicy, NoticeRuntimeProfile, ParsingConfig


@dataclass(frozen=True)
class AppConfig:
    repo_root: Path
    state_path: Path
    output_dir: Path
    prompt_name: str
    llm_providers: dict[str, LLMProviderConfig]
    llm_routing: dict[str, str]
    summary_format_repair_retries: int
    parsing: ParsingConfig
    media_policy: MediaPolicy
    audit_policy: AuditPolicy
    detail_min_chars: int
    runtime_profiles: dict[str, NoticeRuntimeProfile]
    sources: tuple[NoticeSource, ...]

    def source_by_id(self, source_id: str) -> NoticeSource:
        for source in self.sources:
            if source.id == source_id:
                return source
        raise KeyError(source_id)

    def runtime_profile(self, profile_name: str) -> NoticeRuntimeProfile:
        try:
            return self.runtime_profiles[profile_name]
        except KeyError as exc:
            raise KeyError(profile_name) from exc
