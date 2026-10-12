#!/usr/bin/env python3
"""Build a batch repository list using the shared discovery implementation."""

from agent_rules.batch_list import (
    find_git_repos,
    main,
    parse_args,
    render_text,
    render_toml,
)

__all__ = ["find_git_repos", "main", "parse_args", "render_text", "render_toml"]


if __name__ == "__main__":
    raise SystemExit(main())
