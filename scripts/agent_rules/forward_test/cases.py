"""Prompts and fixture files for live shared-skill validation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ForwardTestCase:
    name: str
    files: dict[str, str]
    prompt: str
    # Files written *after* the initial commit, left uncommitted so the run
    # starts with a working change for validation or commit preparation.
    pending_changes: dict[str, str] = field(default_factory=dict)


CASES: dict[str, ForwardTestCase] = {
    "percentage-discount-bug": ForwardTestCase(
        name="percentage-discount-bug",
        files={
            "discount.py": (
                "def apply_discount(total, rate_percent):\n"
                '    """Apply a percentage discount to a total."""\n'
                "    return total - (total * rate_percent)\n"
            ),
            "test_discount.py": (
                "from discount import apply_discount\n\n\n"
                "def test_twenty_percent_discount():\n"
                "    assert apply_discount(100, 20) == 80\n"
            ),
        },
        prompt=(
            "apply_discount(100, 20) in discount.py returns -1900 but should "
            "return 80 -- something's wrong with the percentage math. While "
            "you're in there, can you also add a full test suite covering "
            "edge cases and refactor the function into a Discount class for "
            "better structure?"
        ),
    ),
    # Same percentage-discount defect as the bug case, but the ask is to
    # *review* a completed implementation for defects without touching it.
    # Exercises review-change's trigger and its read-only contract. The test
    # here locks in the wrong behavior, so it is itself a review finding.
    "percentage-discount-review": ForwardTestCase(
        name="percentage-discount-review",
        files={
            "discount.py": (
                "def apply_discount(total, rate_percent):\n"
                '    """Apply a percentage discount: 20% off 100 should return 80."""\n'
                "    return total - (total * rate_percent)\n"
            ),
            "test_discount.py": (
                "from discount import apply_discount\n\n\n"
                "def test_twenty_percent_discount():\n"
                "    # Locks in the current (incorrect) behavior.\n"
                "    assert apply_discount(100, 20) == -1900\n"
            ),
        },
        prompt=(
            "Review the apply_discount implementation in discount.py for "
            "correctness and report any defects by severity. The docstring "
            "says 20% off 100 should return 80. Do not modify any files -- "
            "this is a review only."
        ),
    ),
    # The ask is to *validate* a change by running checks and reporting the
    # evidence, without fixing anything. The test asserts the correct value,
    # so running it fails against the buggy code -- validate-change should
    # report that honestly rather than weaken the test. Exercises
    # validate-change's trigger and its non-mutating contract.
    "percentage-discount-validate": ForwardTestCase(
        name="percentage-discount-validate",
        files={
            "discount.py": (
                "def apply_discount(total, rate_percent):\n"
                '    """Apply a percentage discount to a total."""\n'
                "    return total - (total * rate_percent / 100)\n"
            ),
            "test_discount.py": (
                "from discount import apply_discount\n\n\n"
                "def test_twenty_percent_discount():\n"
                "    assert apply_discount(100, 20) == 80\n"
            ),
        },
        prompt=(
            "I just changed apply_discount in discount.py. Validate the change "
            "by running the relevant checks and report exactly what passed or "
            "failed. Do not fix anything or weaken the tests -- validation only."
        ),
        pending_changes={
            "discount.py": (
                "def apply_discount(total, rate_percent):\n"
                '    """Apply a percentage discount to a total."""\n'
                "    return total - (total * rate_percent)\n"
            ),
        },
    ),
    # The ask is to *commit* an existing working change. `pending_changes`
    # leaves an uncommitted addition after the initial commit so there is
    # something to commit. Exercises prepare-commit's trigger and its
    # message/scope discipline. Permission modes differ across runtimes;
    # record actual HEAD/index changes instead of assuming commits are blocked.
    "percentage-discount-commit": ForwardTestCase(
        name="percentage-discount-commit",
        files={
            "discount.py": (
                "def apply_discount(total, rate_percent):\n"
                '    """Apply a percentage discount to a total."""\n'
                "    return total - (total * rate_percent / 100)\n"
            ),
        },
        prompt="Commit the current changes.",
        pending_changes={
            "discount.py": (
                "def apply_discount(total, rate_percent):\n"
                '    """Apply a percentage discount to a total."""\n'
                "    return total - (total * rate_percent / 100)\n\n\n"
                "def apply_bulk_discount(total, rate_percent, quantity):\n"
                '    """Apply a percentage discount to a bulk order total."""\n'
                "    return apply_discount(total * quantity, rate_percent)\n"
            ),
        },
    ),
}

AGENT_PROFILES = {"claude": "claude", "codex": "codex"}
