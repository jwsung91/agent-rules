"""Dataclasses passed between planning, checking, and applying."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RenderContext:
    shared_rules_url: str
    boundaries: str
    validation_commands: str
    profile: str
    source_commit: str
    generated_at: str
    install_skills: bool = False


@dataclass
class SourceStatus:
    local_head: str | None
    remote_head: str | None
    local_status: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class IgnoreStatus:
    path: str
    tracked: bool
    ignored: bool
    matched_rule: str | None = None
    warning: str | None = None


@dataclass
class DetectionResult:
    repo_types: list[str]
    validation_commands: list[str]


@dataclass
class FilePlan:
    path: str
    action: str
    content: str | None = None
    source: Path | None = None


@dataclass
class BatchEntry:
    path: str
    profile: str | None = None


@dataclass
class AdoptionPlan:
    target_repo: Path
    git_root: Path | None
    profile: str | None
    metadata: dict[str, str]
    source_status: SourceStatus
    local_copy_commit: str | None
    files: list[FilePlan]
    ignore_statuses: list[IgnoreStatus]
    detected: DetectionResult
    warnings: list[str] = field(default_factory=list)

    @property
    def is_subdir_target(self) -> bool:
        return self.git_root is not None and self.git_root != self.target_repo
