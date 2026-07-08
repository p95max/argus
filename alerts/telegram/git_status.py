import os
import subprocess

from pathlib import Path

from django.conf import settings


last_git_error = ""


def build_git_deploy_status_text() -> str:
    git_root = find_git_root()
    if git_root is None:
        return "🧬 Git deploy status\nStatus: git repo not found"

    branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], git_root)
    head_sha = run_git(["rev-parse", "--short", "HEAD"], git_root)
    head_subject = run_git(["log", "-1", "--pretty=%s"], git_root)
    head_date = run_git(
        ["log", "-1", "--date=format:%d.%m.%Y %H:%M:%S", "--pretty=%cd"],
        git_root,
    )
    origin_sha = run_git(["rev-parse", "--short", "origin/master"], git_root)
    relation = build_git_relation_text(git_root)

    lines = ["🧬 Git deploy status", f"Repo: {git_root}"]
    if branch:
        lines.append(f"Branch: {branch}")
    if head_sha:
        lines.append(f"Local HEAD: {head_sha}")
    if head_subject:
        lines.append(f"Commit: {head_subject}")
    if head_date:
        lines.append(f"Date: {head_date}")
    if origin_sha:
        lines.append(f"Origin/master: {origin_sha}")
    if relation:
        lines.append(f"Status: {relation}")

    if len(lines) == 2:
        lines.append("Status: git command failed")
    elif relation == "unknown" and last_git_error:
        lines.append(f"Git error: {last_git_error[:220]}")

    return "\n".join(lines)


def find_git_root() -> Path | None:
    base_dir = Path(settings.BASE_DIR).resolve()
    candidates = [base_dir, *base_dir.parents]

    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate

    discovered = run_raw_git(["rev-parse", "--show-toplevel"], cwd=base_dir)
    if discovered:
        return Path(discovered).resolve()

    return None


def build_git_relation_text(git_root: Path) -> str:
    relation = run_git(
        ["rev-list", "--left-right", "--count", "HEAD...origin/master"],
        git_root,
    )
    if not relation:
        return "unknown"

    parts = relation.split()
    if len(parts) != 2:
        return "unknown"

    try:
        ahead, behind = int(parts[0]), int(parts[1])
    except ValueError:
        return "unknown"

    if ahead == 0 and behind == 0:
        return "up to date"
    if ahead == 0:
        return f"behind origin/master by {behind} commit(s)"
    if behind == 0:
        return f"ahead of origin/master by {ahead} commit(s)"
    return f"diverged: ahead {ahead}, behind {behind}"


def run_git(args: list[str], git_root: Path, timeout: int = 5) -> str:
    return run_raw_git(
        [
            "-c",
            f"safe.directory={git_root}",
            "-C",
            str(git_root),
            *args,
        ],
        cwd=git_root,
        timeout=timeout,
    )


def run_raw_git(args: list[str], cwd: Path, timeout: int = 5) -> str:
    global last_git_error

    git_binary = find_git_binary()
    if not git_binary:
        last_git_error = "git binary not found in /usr/bin/git, /bin/git or PATH"
        return ""

    env = os.environ.copy()
    env.setdefault("HOME", str(cwd))
    env.setdefault("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
    env.setdefault("GIT_CONFIG_NOSYSTEM", "1")

    try:
        result = subprocess.run(
            [git_binary, *args],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        last_git_error = "git command timed out"
        return ""
    except OSError as exc:
        last_git_error = str(exc)
        return ""

    if result.returncode != 0:
        last_git_error = (result.stderr or result.stdout or "git command failed").strip()
        return ""

    last_git_error = ""
    return result.stdout.strip()


def find_git_binary() -> str:
    candidates = (
        "/usr/bin/git",
        "/bin/git",
        "/usr/local/bin/git",
        "git",
    )
    for candidate in candidates:
        if candidate == "git" or Path(candidate).exists():
            return candidate
    return ""
