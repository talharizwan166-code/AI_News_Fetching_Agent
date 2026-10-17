"""Explicit clean-environment launcher; never import the target in this process.

Use when the interactive shell has unrelated credentials. The child receives only
the named OS variables, then independently enforces the sandbox credential guard.
No secret values are copied, printed, or persisted by this launcher.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    names = ("SystemRoot", "SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "LANG", "LC_ALL")
    environment = {name: os.environ[name] for name in names if name in os.environ}
    environment.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", PYTHON_DOTENV_DISABLED="1")
    with tempfile.TemporaryDirectory(prefix="sandbox-home-") as directory:
        # Node/Chromium require a resolvable home on Windows. Use an empty home,
        # never the caller's provider/CLI configuration or browser profile.
        environment.update(HOME=directory, USERPROFILE=directory)
        result = subprocess.run([sys.executable, "-m", "agent_sandbox", *sys.argv[1:]], cwd=root, env=environment)
    raise SystemExit(result.returncode)
