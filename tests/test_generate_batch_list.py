from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate_batch_list.py"
ADOPT_SCRIPT = ROOT / "scripts" / "adopt.py"


def run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


class GenerateBatchListTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def make_repo(self, relative: str) -> Path:
        repo = self.base / relative
        repo.mkdir(parents=True)
        run(["git", "init"], repo)
        return repo

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return run([sys.executable, str(SCRIPT), *args], ROOT)

    def test_scans_root_and_writes_toml_with_profile_detection(self) -> None:
        repo1 = self.make_repo("workspace/repoA")
        repo2 = self.make_repo("workspace/repoB")
        adopt_result = run(
            [sys.executable, str(ADOPT_SCRIPT), str(repo1), "--profile", "claude", "--shared-url", str(ROOT)],
            ROOT,
        )
        self.assertEqual(adopt_result.returncode, 0, adopt_result.stderr + adopt_result.stdout)

        output = self.base / "repos.toml"
        result = self.cli(str(self.base / "workspace"), "--output", str(output))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

        content = output.read_text(encoding="utf-8")
        self.assertIn(f'path = "{repo1.as_posix()}"', content)
        self.assertIn(f'path = "{repo2.as_posix()}"', content)
        self.assertIn('profile = "claude"', content)

    def test_prunes_repos_nested_inside_a_found_repo(self) -> None:
        repo = self.make_repo("workspace/repoA")
        nested = self.make_repo("workspace/repoA/vendored")
        output = self.base / "repos.toml"

        result = self.cli(str(self.base / "workspace"), "--output", str(output))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

        content = output.read_text(encoding="utf-8")
        self.assertIn(f'path = "{repo.as_posix()}"', content)
        self.assertNotIn(nested.as_posix(), content)

    def test_writes_text_format_without_profile_field(self) -> None:
        repo1 = self.make_repo("workspace/repoA")
        repo2 = self.make_repo("workspace/repoB")
        output = self.base / "repos.txt"

        result = self.cli(str(self.base / "workspace"), "--output", str(output))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

        lines = output.read_text(encoding="utf-8").splitlines()
        self.assertEqual(sorted(lines), sorted([repo1.as_posix(), repo2.as_posix()]))

    def test_refuses_to_overwrite_without_force(self) -> None:
        self.make_repo("workspace/repoA")
        output = self.base / "repos.toml"
        output.write_text("existing content\n", encoding="utf-8")

        result = self.cli(str(self.base / "workspace"), "--output", str(output))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing to overwrite", result.stderr + result.stdout)
        self.assertEqual(output.read_text(encoding="utf-8"), "existing content\n")

    def test_force_overwrites_existing_output(self) -> None:
        repo = self.make_repo("workspace/repoA")
        output = self.base / "repos.toml"
        output.write_text("existing content\n", encoding="utf-8")

        result = self.cli(str(self.base / "workspace"), "--output", str(output), "--force")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(repo.as_posix(), output.read_text(encoding="utf-8"))

    def test_rejects_unsupported_output_extension(self) -> None:
        self.make_repo("workspace/repoA")
        output = self.base / "repos.json"

        result = self.cli(str(self.base / "workspace"), "--output", str(output))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported output extension", result.stderr + result.stdout)

    def test_rejects_nonexistent_root(self) -> None:
        output = self.base / "repos.toml"
        result = self.cli(str(self.base / "does-not-exist"), "--output", str(output))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())

    def test_errors_when_no_repos_found(self) -> None:
        (self.base / "workspace" / "not-a-repo").mkdir(parents=True)
        output = self.base / "repos.toml"

        result = self.cli(str(self.base / "workspace"), "--output", str(output))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No Git repositories found", result.stderr + result.stdout)
        self.assertFalse(output.exists())

    @unittest.skipUnless(sys.version_info >= (3, 11), "requires Python 3.11+ (stdlib tomllib)")
    def test_generated_toml_is_consumable_by_batch(self) -> None:
        self.make_repo("workspace/repoA")
        output = self.base / "repos.toml"
        gen_result = self.cli(str(self.base / "workspace"), "--output", str(output))
        self.assertEqual(gen_result.returncode, 0, gen_result.stderr + gen_result.stdout)

        apply_result = run(
            [
                sys.executable,
                str(ADOPT_SCRIPT),
                "--batch",
                str(output),
                "--profile",
                "codex",
                "--shared-url",
                str(ROOT),
                "--dry-run",
            ],
            ROOT,
        )
        self.assertEqual(apply_result.returncode, 0, apply_result.stderr + apply_result.stdout)
        self.assertIn("1 succeeded", apply_result.stdout)


if __name__ == "__main__":
    unittest.main()
