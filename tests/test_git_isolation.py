"""The suite must never touch a real repository, even when git has exported
GIT_DIR and friends (`git rebase --exec pytest`, a hook running pytest).

Every git call here runs with an explicit environment, so this test is safe
whatever the environment it was started from."""
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent

# The tests that make throwaway repos, or run code that calls git on one.
GIT_USING = [
    "test_add_run.py",
    "test_harness_provenance.py",
    "test_install.py::test_install_hooks_points_the_repo_at_the_tracked_hooks",
    "test_release.py",
]


def outside_env():
    """os.environ without any GIT_* variable that could point at a repository."""
    return {k: v for k, v in os.environ.items()
            if not k.startswith("GIT_") or re.match(r"GIT_(AUTHOR|COMMITTER)_", k)}


def sentinel_state(git_dir):
    def git(*args):
        return subprocess.run(["git", f"--git-dir={git_dir}", *args], env=outside_env(),
                              check=True, capture_output=True, text=True).stdout
    return {
        "config": (git_dir / "config").read_text(),
        "refs": git("for-each-ref", "--format=%(refname) %(objectname)"),
        "HEAD": (git_dir / "HEAD").read_text(),
    }


def test_inherited_git_dir_never_reaches_the_tests_repos(tmp_path):
    sentinel = tmp_path / "sentinel"
    subprocess.run(["git", "init", "-q", str(sentinel)], env=outside_env(), check=True)
    subprocess.run(["git", "-C", str(sentinel), "-c", "user.name=s", "-c", "user.email=s@s",
                    "commit", "-q", "--allow-empty", "-m", "sentinel"], env=outside_env(), check=True)
    git_dir = sentinel / ".git"
    before = sentinel_state(git_dir)

    # What `git rebase --exec` or a hook hands its child process.
    env = {**outside_env(), "GIT_DIR": str(git_dir), "GIT_WORK_TREE": str(sentinel),
           "GIT_INDEX_FILE": str(git_dir / "index")}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *GIT_USING],
        cwd=HERE, env=env, capture_output=True, text=True,
    )

    assert sentinel_state(git_dir) == before
    assert result.returncode == 0, result.stdout + result.stderr
