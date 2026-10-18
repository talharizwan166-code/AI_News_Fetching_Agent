"""Explicit clean-environment launcher for the retrospective v2 comparison."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile


if __name__ == "__main__":
    names = ("SystemRoot", "SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "LANG", "LC_ALL")
    environment = {name: os.environ[name] for name in names if name in os.environ}
    environment.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", PYTHON_DOTENV_DISABLED="1")
    with tempfile.TemporaryDirectory(prefix="v2-empty-home-") as directory:
        environment.update(HOME=directory, USERPROFILE=directory)
        process = subprocess.run([sys.executable, "-m", "agent_sandbox.compare_v2", *sys.argv[1:]],
                                 cwd=Path(__file__).resolve().parents[1], env=environment)
    raise SystemExit(process.returncode)
