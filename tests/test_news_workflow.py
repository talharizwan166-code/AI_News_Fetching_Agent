"""Run the workflow's actual Bash guards with Git replaced by a local stub."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/news_agent.yml"
GIT_BASH = Path("C:/Program Files/Git/bin/bash.exe")
BASH = str(GIT_BASH) if GIT_BASH.is_file() else shutil.which("bash")


def step_script(name):
    step = WORKFLOW.read_text(encoding="utf-8").split(f"      - name: {name}\n", 1)[1]
    step = step.split("\n      - name:", 1)[0]
    return textwrap.dedent(step.split("        run: |\n", 1)[1])


def run_step(tmp_path, script, **variables):
    if BASH is None:
        pytest.fail("Bash is required to exercise the GitHub Actions workflow guards")
    environment = dict(os.environ)
    environment.update(variables)
    return subprocess.run(
        [BASH, "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=10,
    )


@pytest.mark.parametrize("missing", ["", " \t\n "])
def test_required_secrets_reports_all_missing_names_without_values(tmp_path, missing):
    result = run_step(
        tmp_path, step_script("Validate required secrets"), GEMINI_API_KEY=missing,
        EMAIL_SENDER=missing, EMAIL_PASSWORD="private-valid-password", EMAIL_RECIPIENT=missing,
    )
    assert result.returncode == 1, result.stderr
    assert result.stdout.splitlines() == [
        "::error::Missing required secret: GEMINI_API_KEY",
        "::error::Missing required secret: EMAIL_SENDER",
        "::error::Missing required secret: EMAIL_RECIPIENT",
    ]
    assert "private-valid-password" not in result.stdout + result.stderr


def test_valid_required_secrets_do_not_print_credentials(tmp_path):
    result = run_step(tmp_path, step_script("Validate required secrets"), **{
        name: "private-test-value"
        for name in ("GEMINI_API_KEY", "EMAIL_SENDER", "EMAIL_PASSWORD", "EMAIL_RECIPIENT")
    })
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""


GIT_STUB = r'''
git() {
  printf '%s\n' "$*" >> ../git-commands.txt
  if [ "$1" = "diff" ]; then
    return "$DIFF_STATUS"
  fi
  if [ "$1" = "$FAIL_COMMAND" ]; then
    return 1
  fi
}
'''


@pytest.mark.parametrize("outcome, has_db, diff_status, message, should_push", [
    ("failure", True, "1", "Agent did not succeed", False),
    ("cancelled", True, "1", "Agent did not succeed", False),
    ("skipped", True, "1", "Agent did not succeed", False),
    ("", True, "1", "Agent did not succeed", False),
    ("success", False, "1", "No database file", False),
    ("success", True, "0", "Database has no changes", False),
    ("success", True, "1", "", True),
])
def test_commit_step_guards_and_noninteractive_amend(tmp_path, outcome, has_db, diff_status, message, should_push):
    data = tmp_path / "data-branch"
    data.mkdir()
    if has_db:
        (data / "news_agent.db").write_bytes(b"test database")
    result = run_step(
        tmp_path, GIT_STUB + step_script("Commit and push DB to data branch"),
        AGENT_OUTCOME=outcome, DIFF_STATUS=diff_status, FAIL_COMMAND="",
    )
    assert result.returncode == 0, result.stderr
    assert message in result.stdout
    log = tmp_path / "git-commands.txt"
    commands = log.read_text().splitlines() if log.exists() else []
    if outcome != "success" or not has_db:
        assert commands == []
    else:
        assert "config --local user.name github-actions[bot]" in commands
        assert "config --local user.email github-actions[bot]@users.noreply.github.com" in commands
        assert "add -f news_agent.db" in commands
        assert "diff --cached --quiet -- news_agent.db" in commands
    assert ("commit --amend --no-edit" in commands) is should_push
    assert ("push --force origin HEAD:refs/heads/data" in commands) is should_push


@pytest.mark.parametrize("command", ["add", "commit", "push"])
def test_git_errors_fail_commit_step_instead_of_silently_succeeding(tmp_path, command):
    data = tmp_path / "data-branch"
    data.mkdir()
    (data / "news_agent.db").write_bytes(b"test database")
    result = run_step(
        tmp_path, GIT_STUB + step_script("Commit and push DB to data branch"),
        AGENT_OUTCOME="success", DIFF_STATUS="1", FAIL_COMMAND=command,
    )
    assert result.returncode == 1, result.stderr
    commands = (tmp_path / "git-commands.txt").read_text().splitlines()
    if command != "push":
        assert not any(item.startswith("push ") for item in commands)


@pytest.mark.parametrize("remote_status, expected_output, expected_code", [
    ("0", "exists=true\n", 0), ("2", "exists=false\n", 0), ("128", "", 128),
])
def test_data_branch_detection_distinguishes_missing_branch_from_git_failure(
    tmp_path, remote_status, expected_output, expected_code,
):
    output = tmp_path / "outputs.txt"
    output.touch()
    result = run_step(
        tmp_path, 'git() { return "$REMOTE_STATUS"; }\n' + step_script("Check data branch"),
        REMOTE_STATUS=remote_status, GITHUB_OUTPUT=output.as_posix(),
    )
    assert result.returncode == expected_code, result.stderr
    assert output.read_text() == expected_output


def test_workflow_timeouts_credentials_and_agent_outcome_are_wired():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "    timeout-minutes: 20\n" in workflow
    assert '      GIT_TERMINAL_PROMPT: "0"\n' in workflow
    assert '      GIT_EDITOR: "true"\n' in workflow
    assert '      GIT_SEQUENCE_EDITOR: "true"\n' in workflow
    assert '      GCM_INTERACTIVE: "Never"\n' in workflow
    checkouts = re.findall(r"        uses: actions/checkout@[^\n]+\n(.*?)(?=\n      - name:)", workflow, re.S)
    assert len(checkouts) == 2
    for checkout in checkouts:
        assert "          persist-credentials: true\n" in checkout
        assert "          token: ${{ github.token }}\n" in checkout
    assert "          path: data-branch\n" in checkouts[1]
    assert "      - name: Run AI News Agent\n        id: agent\n" in workflow
    commit = workflow.split("      - name: Commit and push DB to data branch\n", 1)[1]
    assert "        timeout-minutes: 5\n" in commit
    assert "          AGENT_OUTCOME: ${{ steps.agent.outcome }}\n" in commit
    assert "        if: always() && steps.check.outputs.skip != 'true'\n" in commit
