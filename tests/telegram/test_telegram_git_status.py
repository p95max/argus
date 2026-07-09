import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from alerts.telegram import git_status


@pytest.mark.parametrize(
    ("git_output", "expected"),
    [
        ("0 0", "up to date"),
        ("0 3", "behind origin/master by 3 commit(s)"),
        ("2 0", "ahead of origin/master by 2 commit(s)"),
        ("2 5", "diverged: ahead 2, behind 5"),
        ("", "unknown"),
        ("bad", "unknown"),
        ("x y", "unknown"),
    ],
)
def test_build_git_relation_text(monkeypatch, git_output, expected):
    monkeypatch.setattr(git_status, "run_git", lambda args, git_root: git_output)

    assert git_status.build_git_relation_text(Path("/repo")) == expected


def test_build_git_deploy_status_text_when_repo_is_missing(monkeypatch):
    monkeypatch.setattr(git_status, "find_git_root", lambda: None)

    assert git_status.build_git_deploy_status_text() == (
        "🧬 Git deploy status\nStatus: git repo not found"
    )


def test_build_git_deploy_status_text_contains_successful_git_metadata(monkeypatch):
    git_root = Path("/repo")
    monkeypatch.setattr(git_status, "find_git_root", lambda: git_root)
    monkeypatch.setattr(git_status, "build_git_relation_text", lambda root: "up to date")

    def fake_run_git(args, root):
        assert root == git_root
        if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return "master"
        if args == ["rev-parse", "--short", "HEAD"]:
            return "abc1234"
        if args == ["log", "-1", "--pretty=%s"]:
            return "fix: deploy"
        if args == ["log", "-1", "--date=format:%d.%m.%Y %H:%M:%S", "--pretty=%cd"]:
            return "09.07.2026 12:30:00"
        if args == ["rev-parse", "--short", "origin/master"]:
            return "def5678"
        raise AssertionError(f"Unexpected git args: {args}")

    monkeypatch.setattr(git_status, "run_git", fake_run_git)

    text = git_status.build_git_deploy_status_text()

    assert f"Repo: {git_root}" in text
    assert "Branch: master" in text
    assert "Local HEAD: abc1234" in text
    assert "Commit: fix: deploy" in text
    assert "Date: 09.07.2026 12:30:00" in text
    assert "Origin/master: def5678" in text
    assert "Status: up to date" in text


def test_build_git_deploy_status_text_reports_command_failure(monkeypatch):
    git_root = Path("/repo")
    monkeypatch.setattr(git_status, "find_git_root", lambda: git_root)
    monkeypatch.setattr(git_status, "run_git", lambda args, root: "")
    monkeypatch.setattr(git_status, "build_git_relation_text", lambda root: "")

    text = git_status.build_git_deploy_status_text()

    assert f"Repo: {git_root}" in text
    assert "Status: git command failed" in text


def test_run_git_injects_safe_directory(monkeypatch):
    captured = {}

    def fake_run_raw_git(args, *, cwd, timeout=5):
        captured["args"] = args
        captured["cwd"] = cwd
        captured["timeout"] = timeout
        return "ok"

    monkeypatch.setattr(git_status, "run_raw_git", fake_run_raw_git)

    git_root = Path("/repo")
    result = git_status.run_git(["status", "--short"], git_root, timeout=9)

    assert result == "ok"
    assert captured == {
        "args": [
            "-c",
            f"safe.directory={git_root}",
            "-C",
            str(git_root),
            "status",
            "--short",
        ],
        "cwd": git_root,
        "timeout": 9,
    }


def test_run_raw_git_reports_missing_binary(monkeypatch):
    monkeypatch.setattr(git_status, "find_git_binary", lambda: "")

    assert git_status.run_raw_git(["status"], cwd=Path("repo")) == ""
    assert git_status.last_git_error == "git binary not found in /usr/bin/git, /bin/git or PATH"


def test_run_raw_git_reports_timeout(monkeypatch):
    monkeypatch.setattr(git_status, "find_git_binary", lambda: "git")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=5)

    monkeypatch.setattr(git_status.subprocess, "run", fake_run)

    assert git_status.run_raw_git(["status"], cwd=Path("repo")) == ""
    assert git_status.last_git_error == "git command timed out"


def test_run_raw_git_reports_nonzero_exit(monkeypatch):
    monkeypatch.setattr(git_status, "find_git_binary", lambda: "git")
    monkeypatch.setattr(
        git_status.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=128,
            stdout="",
            stderr="fatal: not a git repository",
        ),
    )

    assert git_status.run_raw_git(["status"], cwd=Path("repo")) == ""
    assert git_status.last_git_error == "fatal: not a git repository"


def test_run_raw_git_returns_stdout_and_clears_error(monkeypatch):
    git_status.last_git_error = "old error"
    monkeypatch.setattr(git_status, "find_git_binary", lambda: "git")
    monkeypatch.setattr(
        git_status.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=" master\n",
            stderr="",
        ),
    )

    assert git_status.run_raw_git(["branch", "--show-current"], cwd=Path("repo")) == "master"
    assert git_status.last_git_error == ""
