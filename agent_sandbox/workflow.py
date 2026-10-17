"""Read and execute the approval workflow's own scripts; do not copy its policy."""

import ast
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import textwrap

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/linkedin_approve.yml"


def step_script(name):
    source = WORKFLOW.read_text(encoding="utf-8")
    step = source.split(f"      - name: {name}\n", 1)[1].split("\n      - name:", 1)[0]
    return textwrap.dedent(step.split("        run: |\n", 1)[1])


def check_approval(directory, comment, association, pending=True):
    source = WORKFLOW.read_text(encoding="utf-8")
    # Fail closed if orchestration changes, rather than silently testing stale policy.
    if "if: contains(github.event.issue.labels.*.name, 'linkedin-pending')" not in source:
        raise ValueError("Approval workflow job guard changed; review the sandbox adapter")
    if not pending:
        return "ignore"
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    bash = str(git_bash) if git_bash.exists() else shutil.which("bash")
    if not bash:
        raise ValueError("Bash is required to test the actual approval workflow")
    output = Path(directory) / "approval-output"
    output.write_text("", encoding="utf-8")
    env = dict(os.environ, COMMENT_BODY=comment, AUTHOR_ASSOC=association, GITHUB_OUTPUT=output.as_posix())
    result = subprocess.run([bash, "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", step_script("Check comment")],
                            cwd=directory, env=env, capture_output=True, timeout=10)
    if result.returncode:
        return "invalid_comment"
    return output.read_text(encoding="utf-8").strip().removeprefix("action=")


def publish_script():
    source = WORKFLOW.read_text(encoding="utf-8")
    step = source.split("      - name: Post to LinkedIn\n", 1)[1].split("\n      - name:", 1)[0]
    if "if: steps.check.outputs.action == 'approve' && steps.secrets.outputs.mode == 'auto'" not in step:
        raise ValueError("Publishing workflow guard changed; review the sandbox adapter")
    script = step_script("Post to LinkedIn").strip()
    if not script.startswith('python -c "') or not script.endswith('"'):
        raise ValueError("Publishing script layout changed; review the sandbox adapter")
    python = script[len('python -c "'):-1]
    ast.parse(python)
    return python


def fingerprint():
    return hashlib.sha256(WORKFLOW.read_bytes()).hexdigest()
