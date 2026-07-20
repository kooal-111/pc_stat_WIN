from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class ReleaseV130Tests(unittest.TestCase):
    def test_application_has_no_network_or_telemetry_imports(self) -> None:
        blocked_roots = {
            "aiohttp",
            "amplitude",
            "ftplib",
            "http",
            "httpx",
            "mixpanel",
            "opentelemetry",
            "posthog",
            "requests",
            "sentry_sdk",
            "smtplib",
            "socket",
            "ssl",
            "telnetlib",
            "urllib",
            "websockets",
        }
        violations: list[str] = []
        for path in sorted((ROOT / "pc_stat_win").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module]
                for module in modules:
                    if module.split(".", 1)[0] in blocked_roots:
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {module}")
        self.assertEqual(violations, [], "Network/telemetry imports found:\n" + "\n".join(violations))

    def test_runtime_dependencies_are_exactly_pinned(self) -> None:
        self.assertEqual(
            read("requirements.txt").splitlines(),
            ["PySide6==6.11.0", "pywin32==311", "psutil==7.2.2"],
        )
        self.assertEqual(
            read("requirements-build.txt").splitlines(),
            ["PyInstaller==6.19.0", "pip-audit==2.10.1"],
        )
        lock = read("requirements-lock.txt")
        self.assertIn("--hash=sha256:", lock)
        for requirement in ("pyside6==6.11.0", "pyinstaller==6.19.0", "pip-audit==2.10.1"):
            self.assertIn(requirement, lock)

    def test_application_version_is_131(self) -> None:
        self.assertRegex(
            read("pc_stat_win/version.py"),
            r'(?m)^APP_VERSION\s*=\s*"1\.3\.1"$',
        )

    def test_build_is_clean_scoped_and_does_not_regenerate_icons(self) -> None:
        script = read("scripts/build_windows.ps1")
        self.assertIn("Get-RepoTarget", script)
        self.assertIn("Refusing to use a path outside the repository", script)
        self.assertIn('Remove-RepoTarget "dist\\PCStat.exe"', script)
        self.assertIn('Remove-RepoTarget "dist\\PCStat"', script)
        self.assertIn('Remove-RepoTarget "dist\\SHA256SUMS.txt"', script)
        self.assertIn('Remove-RepoTarget "build\\pc_stat_win_onefile"', script)
        self.assertIn("--clean", script)
        self.assertIn("--distpath", script)
        self.assertIn("--workpath", script)
        self.assertIn("--require-hashes -r requirements-lock.txt", script)
        self.assertNotIn("write_packaged_icon_assets", script)
        self.assertNotIn("render_app_icon", script)

    def test_publish_script_contains_all_release_gates(self) -> None:
        script = read("scripts/publish_release.ps1")
        required_fragments = (
            '"status", "--porcelain", "--untracked-files=normal"',
            '"auth", "status", "--hostname", "github.com"',
            '"unittest", "discover", "-s", "tests"',
            '"scripts\\smoke_ui_qt.py"',
            '"run", "download"',
            '"attestation", "verify"',
            '"--workflow", "Windows CI"',
            '"ls-remote", "--exit-code", "--heads"',
            'ArgumentList "--smoke-test"',
            ".WaitForExit(120000)",
            "Stop-Process -Id $process.Id -Force",
            '$expectedSchemaVersion = "7"',
            "PRAGMA quick_check",
            ".FileVersion",
            ".ProductVersion",
            '"tag", "-a", $tag, $headSha',
            'show-ref --verify --quiet "refs/tags/$tag"',
            '"push", $Remote, "refs/tags/${tag}:refs/tags/${tag}"',
            '"ls-remote", "--exit-code", "--tags"',
            '"--verify-tag"',
            '"--target", $headSha',
            '"--repo", $Repo',
            'Join-Path $releaseRoot "PCStat.exe"',
            'Join-Path $releaseRoot "SHA256SUMS.txt"',
            r'Join-Path $root "output\release-staging"',
            'Join-Path $releaseRoot "smoke"',
            "Release staging directory escaped the repository output directory.",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)
        self.assertNotIn("[System.IO.Path]::GetTempPath()", script)

    def test_ci_covers_scales_tests_build_and_packaged_database(self) -> None:
        workflow = read(".github/workflows/ci.yml")
        for fragment in (
            "runs-on: windows-latest",
            'python-version: "3.11.9"',
            'qt_scale: ["1", "1.5", "2"]',
            "python -m pip check",
            "python -X utf8 -m pip_audit --strict --disable-pip -r requirements-lock.txt",
            "python -m pip install --require-hashes -r requirements-lock.txt",
            "Run release and privacy static checks",
            "python -m unittest discover -s tests -p test_release_v130.py",
            "steps.version.outputs.version",
            "python -m unittest discover -s tests",
            "python scripts/smoke_ui_qt.py",
            ".\\scripts\\build_windows.ps1 -OneFile",
            'ArgumentList "--smoke-test"',
            ".WaitForExit(120000)",
            "Stop-Process -Id $process.Id -Force",
            '$expectedSchemaVersion = "7"',
            "PRAGMA quick_check",
            ".FileVersion",
            ".ProductVersion",
            "actions/attest@f7c74d28b9d84cb8768d0b8ca14a4bac6ef463e6",
            "subject-checksums: dist/SHA256SUMS.txt",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, workflow)
        self.assertNotRegex(workflow, r"uses:\s+[^\s]+@v\d+")

    def test_readme_matches_release_version_and_single_command_flow(self) -> None:
        readme = read("README.md")
        self.assertTrue(readme.startswith("# PC Stat 1.3.1"))
        release_section = readme.split("## Версия и выпуск", 1)[1].split("## Настройки", 1)[0]
        self.assertIn(".\\scripts\\publish_release.ps1", release_section)
        self.assertIn("schema 7", release_section)
        self.assertIn("--verify-tag --target <HEAD> --repo <owner/name>", release_section)
        self.assertIsNotNone(re.search(r"чистого Git checkout", release_section, re.IGNORECASE))
        privacy_section = readme.split("## Конфиденциальность", 1)[1].split("**Имена и иконки", 1)[0]
        for statement in (
            "не использует сеть, телеметрию",
            "%LOCALAPPDATA%\\pc_stat_win\\data.sqlite",
            "%LOCALAPPDATA%\\pc_stat_win\\logs\\pc_stat.log",
            "заголовков окон по умолчанию выключено",
            "CSV создаётся только после явного нажатия",
        ):
            self.assertIn(statement, privacy_section)


if __name__ == "__main__":
    unittest.main()
