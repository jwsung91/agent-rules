"""Shared pytest configuration."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_proposal_store(tmp_path_factory, monkeypatch):
    # AI analyses persist their latest proposal; keep tests out of ~/.cache.
    monkeypatch.setenv(
        "AGENT_RULES_PROPOSAL_DIR", str(tmp_path_factory.mktemp("ai-proposals"))
    )
