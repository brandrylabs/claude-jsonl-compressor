#!/usr/bin/env python3
"""Release-package checks for the npm thin wrappers and allowlist."""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
NPM = shutil.which("npm")

PUBLIC_ROOT_FILES = {
    ".gitignore", "CHANGELOG.md", "LICENSE", "NOTICE", "README.md", "SKILL.md", "package.json",
}
PUBLIC_DIR_SUFFIXES = {
    "agents": {".yaml"},
    "bin": {".cjs"},
    "config": {".json"},
    "references": {".md"},
    "scripts": {".py"},
    "templates": {".md"},
    "tests": {".md", ".py"},
}
IGNORED_REPOSITORY_PARTS = {".git"}
GENERATED_PARTS = {"__pycache__", ".pytest_cache", ".npm", "node_modules"}
GENERATED_SUFFIXES = {".pyc", ".pyo", ".tgz"}


def run(*args: str, cwd: pathlib.Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args), cwd=str(cwd), text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )


def public_repository_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in IGNORED_REPOSITORY_PARTS for part in relative.parts):
            continue
        if any(part in GENERATED_PARTS for part in relative.parts) or path.suffix.lower() in GENERATED_SUFFIXES:
            continue
        files.append(path)
    return files


def generated_repository_artifacts() -> list[str]:
    artifacts: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if any(part in IGNORED_REPOSITORY_PARTS for part in relative.parts):
            continue
        if any(part in GENERATED_PARTS for part in relative.parts):
            artifacts.append(relative.as_posix())
        elif path.is_file() and path.suffix.lower() in GENERATED_SUFFIXES:
            artifacts.append(relative.as_posix())
    return artifacts


def powershell_blocks(text: str) -> list[str]:
    return re.findall(r"```powershell\s*\n(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)


class TestNpmPackage(unittest.TestCase):
    def assert_private_markers_absent(self, label: str, content: bytes) -> None:
        lowered = content.lower()
        dynamic_roots = {
            str(pathlib.Path.home()).encode("utf-8", errors="ignore").lower(),
            str(ROOT.parent).encode("utf-8", errors="ignore").lower(),
        }
        fixed_roots = {
            (b"c:" + b"\\users\\").lower(),
            (b"c:" + b"\\codex\\").lower(),
            (b"/" + b"users/").lower(),
            (b"/" + b"home/").lower(),
        }
        for marker in dynamic_roots | fixed_roots:
            if len(marker) >= 5:
                self.assertNotIn(marker, lowered, label)

        text = content.decode("utf-8", errors="replace")
        self.assertEqual(
            re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text),
            [],
            label,
        )
        secret_patterns = [
            rb"AKIA[0-9A-Z]{16}",
            rb"(?:sk|ghp)[-_][A-Za-z0-9_-]{16,}",
            rb"github_pat_[A-Za-z0-9_]{20,}",
            rb"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        ]
        for pattern in secret_patterns:
            self.assertIsNone(re.search(pattern, content), label)

        allowed_windows_roots = (
            "c:\\data\\", "c:\\path\\", "c:\\synthetic\\", "c:\\w\\", "c:\\work\\",
        )
        for match in re.finditer(r"(?i)\b[A-Z]:\\+(?:[^\s\"'<>|]+)", text):
            normalized = re.sub(r"\\+", r"\\", match.group(0)).lower()
            self.assertTrue(normalized.startswith(allowed_windows_roots), f"{label}: {normalized}")

    def test_public_tree_is_clean_allowlisted_and_private_markers_are_absent(self):
        self.assertEqual(generated_repository_artifacts(), [])
        for path in public_repository_files():
            relative = path.relative_to(ROOT)
            if len(relative.parts) == 1:
                self.assertIn(relative.as_posix(), PUBLIC_ROOT_FILES)
            else:
                top = relative.parts[0]
                self.assertIn(top, PUBLIC_DIR_SUFFIXES, relative.as_posix())
                self.assertIn(path.suffix.lower(), PUBLIC_DIR_SUFFIXES[top], relative.as_posix())
            lowered_name = path.name.lower()
            self.assertFalse(lowered_name.endswith((".jsonl", ".backup", ".pyc", ".tgz")), relative.as_posix())
            self.assertNotIn("model-pack", lowered_name, relative.as_posix())
            self.assertNotIn("model-summary", lowered_name, relative.as_posix())
            self.assert_private_markers_absent(relative.as_posix(), path.read_bytes())

    def test_manifest_has_no_runtime_dependencies_or_install_hooks(self):
        manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "@brandry/claude-jsonl-compressor")
        self.assertEqual(manifest["version"], "1.0.0-rc.1")
        self.assertEqual(manifest["license"], "GPL-3.0-only")
        self.assertEqual(manifest["engines"]["node"], ">=22")
        self.assertEqual(
            manifest["author"],
            {"name": "Brandry Labs", "url": "https://github.com/brandrylabs"},
        )
        keywords = manifest["keywords"]
        self.assertEqual(keywords, list(dict.fromkeys(keywords)))
        self.assertTrue(
            {
                "claude-code", "jsonl", "context-compression", "conversation-memory",
                "session-transcript", "summarization", "rewind",
            }.issubset(set(keywords))
        )
        self.assertIn("CHANGELOG.md", manifest["files"])
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [1.0.0-rc.1] - 2026-07-28", changelog)
        self.assertEqual(
            manifest["repository"]["url"],
            "git+https://github.com/brandrylabs/claude-jsonl-compressor.git",
        )
        self.assertEqual(
            manifest["homepage"],
            "https://github.com/brandrylabs/claude-jsonl-compressor#readme",
        )
        self.assertEqual(
            manifest["bugs"]["url"],
            "https://github.com/brandrylabs/claude-jsonl-compressor/issues",
        )
        for key in ("dependencies", "optionalDependencies", "peerDependencies"):
            self.assertFalse(manifest.get(key), key)
        scripts = manifest.get("scripts") or {}
        for hook in ("preinstall", "install", "postinstall", "prepare", "prepack", "postpack"):
            self.assertNotIn(hook, scripts)

    def test_public_guidance_uses_current_model_pack_schema(self):
        for relative in (
            "README.md",
            "SKILL.md",
            "references/claude-jsonl-compression-format.md",
            "tests/README.md",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("v11", text, relative)
            self.assertNotIn("v9", text, relative)
        for relative in (
            "README.md",
            "SKILL.md",
            "references/claude-jsonl-compression-format.md",
            "tests/README.md",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("model-pack-estimated-token-budget", text, relative)

    def test_public_two_pass_examples_bind_the_candidate_token_target(self):
        for relative in ("README.md", "SKILL.md"):
            blocks = powershell_blocks((ROOT / relative).read_text(encoding="utf-8"))
            model_passes = [
                block for block in blocks
                if "compress_claude_jsonl.py" in block
                and ("--write-model-pack" in block or "--model-summary" in block)
            ]
            self.assertGreaterEqual(len(model_passes), 2, relative)
            for block in model_passes:
                self.assertIn("--target-estimated-tokens 150000", block, relative)

    def test_release_guidance_separates_local_publish_from_ci_provenance(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("npm publish --access public --tag rc", readme)
        self.assertIn("npm publish --dry-run --access public --tag rc", readme)
        self.assertNotIn("npm publish --access public --tag rc --provenance", readme)
        self.assertIn("supported cloud CI", readme)
        self.assertIn("id-token: write", readme)
        self.assertIn("$env:CODEX_HOME", readme)
        self.assertIn("New-Item -ItemType Directory -Force", readme)

    def test_agent_prompt_is_concise_and_defers_detail_to_the_skill(self):
        metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        match = re.search(r'^\s*default_prompt:\s*(".*")\s*$', metadata, flags=re.MULTILINE)
        self.assertIsNotNone(match)
        prompt = json.loads(match.group(1))
        self.assertLessEqual(len(prompt), 800)
        for marker in (
            "$claude-jsonl-compressor", "one Claude Code JSONL", "model-assisted",
            "rewound", "last-prompt", "validate",
        ):
            self.assertIn(marker, prompt)

    def test_public_test_modules_use_behavior_names(self):
        current = {path.name for path in (ROOT / "tests").glob("test_*.py")}
        self.assertEqual(
            current,
            {
                "test_compressor.py",
                "test_package.py",
                "test_protocol_contracts.py",
                "test_repair.py",
                "test_transaction_races.py",
                "test_semantic_evidence_contracts.py",
                "test_structural_safety_contracts.py",
            },
        )

    def test_node_wrappers_parse_and_match_python_version_output(self):
        wrappers = [
            ROOT / "bin" / "claude-jsonl-compressor.cjs",
            ROOT / "bin" / "claude-jsonl-repair-read-pages.cjs",
            ROOT / "bin" / "run-python.cjs",
        ]
        for wrapper in wrappers:
            checked = run("node", "--check", str(wrapper))
            self.assertEqual(checked.returncode, 0, checked.stderr)
        python_version = run(
            sys.executable, "-B", str(ROOT / "scripts" / "compress_claude_jsonl.py"), "--version"
        )
        node_version = run("node", str(wrappers[0]), "--version")
        repair_version = run("node", str(wrappers[1]), "--version")
        self.assertEqual(node_version.returncode, 0, node_version.stderr)
        self.assertEqual(repair_version.returncode, 0, repair_version.stderr)
        self.assertEqual(json.loads(node_version.stdout), json.loads(python_version.stdout))
        self.assertEqual(json.loads(python_version.stdout)["defaultModelPackEstimatedTokenBudget"], 150000)
        repair_data = json.loads(repair_version.stdout)
        self.assertEqual(repair_data["packageVersion"], "1.0.0-rc.1")
        self.assertEqual(repair_data["engineVersion"], "v10")
        self.assertEqual(repair_data["reportSchemaVersion"], 1)

    def test_python_clis_start_under_isolated_no_site_mode(self):
        for script in ("compress_claude_jsonl.py", "repair_claude_jsonl.py"):
            result = run(sys.executable, "-B", "-I", "-S", str(ROOT / "scripts" / script), "--version")
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["packageVersion"], "1.0.0-rc.1")
            self.assertEqual(data["engineVersion"], "v10")

    def test_real_npm_tarball_matches_public_allowlist_and_installs_offline(self):
        self.assertIsNotNone(NPM, "npm must be available for release-package tests")
        with tempfile.TemporaryDirectory(prefix="cjc_npm_") as tmp_name:
            tmp = pathlib.Path(tmp_name)
            packed = run(str(NPM), "pack", "--json", "--pack-destination", str(tmp))
            self.assertEqual(packed.returncode, 0, packed.stderr)
            metadata = json.loads(packed.stdout)
            self.assertEqual(len(metadata), 1)
            self.assertEqual(metadata[0]["name"], "@brandry/claude-jsonl-compressor")
            tarball = tmp / metadata[0]["filename"]
            self.assertTrue(tarball.exists())
            with tarfile.open(tarball, "r:gz") as archive:
                names = sorted(member.name for member in archive.getmembers() if member.isfile())
                allowed_prefixes = (
                    "package/agents/", "package/bin/", "package/config/", "package/references/",
                    "package/scripts/", "package/templates/",
                )
                allowed_exact = {
                    "package/package.json", "package/README.md", "package/SKILL.md",
                    "package/CHANGELOG.md", "package/LICENSE", "package/NOTICE",
                }
                for name in names:
                    self.assertTrue(name in allowed_exact or name.startswith(allowed_prefixes), name)
                    lowered = name.lower()
                    self.assertFalse(lowered.endswith((".jsonl", ".backup", ".pyc", ".tgz")), name)
                    self.assertNotIn("test", lowered, name)
                    self.assertNotIn("report", lowered, name)
                for member in archive.getmembers():
                    if not member.isfile():
                        continue
                    file_obj = archive.extractfile(member)
                    content = file_obj.read() if file_obj else b""
                    self.assert_private_markers_absent(member.name, content)
                self.assertTrue(
                    {
                        "package/SKILL.md",
                        "package/CHANGELOG.md",
                        "package/NOTICE",
                        "package/agents/openai.yaml",
                        "package/references/claude-jsonl-compression-format.md",
                    }.issubset(set(names))
                )

            install = tmp / "install"
            installed = run(
                str(NPM), "install", "--offline", "--ignore-scripts", "--no-audit", "--no-fund",
                "--prefix", str(install), str(tarball), cwd=tmp,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            installed_package = install / "node_modules" / "@brandry" / "claude-jsonl-compressor"
            self.assertTrue((installed_package / "SKILL.md").is_file())
            self.assertTrue((installed_package / "references" / "claude-jsonl-compression-format.md").is_file())
            bin_dir = install / "node_modules" / ".bin"
            for command in ("claude-jsonl-compressor", "claude-jsonl-repair-read-pages"):
                executable = bin_dir / (command + ".cmd" if os.name == "nt" else command)
                self.assertTrue(executable.exists(), str(executable))
                if os.name == "nt":
                    invoked = run("cmd.exe", "/d", "/c", str(executable), "--version", cwd=tmp)
                else:
                    invoked = run(str(executable), "--version", cwd=tmp)
                self.assertEqual(invoked.returncode, 0, invoked.stderr)
                self.assertEqual(json.loads(invoked.stdout)["packageVersion"], "1.0.0-rc.1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
