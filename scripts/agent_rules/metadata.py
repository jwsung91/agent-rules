"""The agent-rules metadata block: rendering, parsing, comparing."""

from __future__ import annotations

from datetime import datetime

from .constants import GENERATED_AT_RE, METADATA_RE, SOURCE_REF


def render_metadata(
    *,
    shared_url: str,
    profile: str,
    source_commit: str,
    generated_at: str | None = None,
) -> str:
    timestamp = generated_at or datetime.now().astimezone().isoformat(timespec="seconds")
    return "\n".join(
        [
            "<!-- agent-rules:",
            f"source={shared_url}",
            f"profile={profile}",
            f"source_ref={SOURCE_REF}",
            f"source_commit={source_commit}",
            f"generated_at={timestamp}",
            "managed_block=true",
            "-->",
        ]
    )


def parse_metadata(content: str) -> dict[str, str]:
    match = METADATA_RE.search(content)
    if not match:
        return {}

    metadata: dict[str, str] = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        metadata[key.strip()] = value.strip()
    return metadata


def mask_generated_at(content: str) -> str:
    """Return `content` with the metadata block's generated_at value blanked.

    Every render stamps a fresh `generated_at`, so a byte comparison reports a
    change even when nothing else moved — which made repeated `--sync` runs
    rewrite every entrypoint and produce an empty diff each time. Comparing
    with the timestamp masked keeps `--sync` idempotent while still detecting
    real content changes, including a new `source_commit`.

    Only the value inside the `<!-- agent-rules: ... -->` block is masked, so a
    line that happens to start with `generated_at=` elsewhere in the file is
    still compared literally.
    """
    match = METADATA_RE.search(content)
    if not match:
        return content
    masked = GENERATED_AT_RE.sub("generated_at=", match.group(0))
    return content[: match.start()] + masked + content[match.end() :]


def same_content(left: str, right: str) -> bool:
    """Compare rendered content while ignoring the generated_at timestamp."""
    return mask_generated_at(left) == mask_generated_at(right)


def generated_at_line(content: str) -> str | None:
    """The metadata block's generated_at line, if there is one."""
    match = METADATA_RE.search(content)
    if not match:
        return None
    line = GENERATED_AT_RE.search(match.group(0))
    return line.group(0) if line else None


def apply_generated_at(content: str, line: str | None) -> str:
    """Put `line` back as the metadata block's generated_at."""
    if line is None:
        return content
    match = METADATA_RE.search(content)
    if not match:
        return content
    replaced = GENERATED_AT_RE.sub(lambda _match: line, match.group(0), count=1)
    return content[: match.start()] + replaced + content[match.end() :]
