import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def checked(command, *, cwd, env=None):
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_built_wheel_installed_outside_source_finds_templates_suites_and_cli(tmp_path):
    # Copy only distribution inputs: never client DBs, credentials, tests or demos.
    source = tmp_path / "source"
    source.mkdir()
    for name in ("pyproject.toml", "LICENSE"):
        shutil.copy2(ROOT / name, source / name)
    for name in ("chatcheck", "suites"):
        shutil.copytree(ROOT / name, source / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (source / "docs").mkdir()
    shutil.copy2(ROOT / "docs/chatcheck-package.md", source / "docs/chatcheck-package.md")
    distribution = tmp_path / "dist"
    checked([sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(distribution)], cwd=source)
    wheel = next(distribution.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        assert {"chatcheck/report_templates/report.html", "chatcheck/report_templates/sections.html",
                "chatcheck/report_templates/styles.css", "chatcheck/report_templates/fixes.json",
                "chatcheck/suites/clothing_store.json", "chatcheck/suites/clothing_store_heldout.json",
                "chatcheck/suites/starter.json", "chatcheck/workspace_templates/.env.example"} <= names
        assert not any(name.endswith((".db", ".env")) for name in names)
    installed = tmp_path / "installed"
    outside = tmp_path / "outside"
    outside.mkdir()
    checked([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps", "--no-compile", "--target", str(installed), str(wheel)], cwd=outside)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(installed)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    program = '''
import json
from pathlib import Path
from importlib.metadata import distribution
import chatcheck
from chatcheck.models import load_suite, RunOptions, TestCase
from chatcheck.storage import Storage
from chatcheck.judge import judge
from chatcheck.report import render_report, load_catalog
from chatcheck.workspace import library_directory
assert Path(chatcheck.__file__).resolve().is_relative_to(Path(INSTALLED).resolve())
assert len(load_suite(library_directory().joinpath('clothing_store.json'))) == 76
assert len(load_suite(library_directory().joinpath('clothing_store_heldout.json'))) == 20
assert load_catalog()['reviewed']
with Storage(':memory:') as db:
    case = TestCase('fixture', 'hello', [{'type': 'contains', 'value': 'hello'}])
    run_id, ids = db.start_run([case], 'Installed wheel', 'suite.json', RunOptions())
    db.record_attempt(ids[0], 1, 'hello', 0, None)
    db.record_verdict(ids[0], judge('hello', case.checks))
    db.finish_run(run_id)
    html = render_report(db.results(run_id))
    assert 'Installed wheel' in html and '100.0%' in html
assert any(e.name == 'chatcheck' and e.value == 'chatcheck.cli:main' for e in distribution('chatcheck').entry_points)
print('Installed wheel resources and entry point verified')
'''
    program = "INSTALLED = " + repr(str(installed)) + "\n" + program
    checked([sys.executable, "-c", program], cwd=outside, env=environment)
    checked([sys.executable, "-m", "chatcheck", "init", "client"], cwd=outside, env=environment)
    assert json.loads((outside / "client/suite.json").read_text(encoding="utf-8"))["tests"] == []
    # pip --target uses bin on some Windows pip versions, unlike a venv install.
    filename = "chatcheck.exe" if os.name == "nt" else "chatcheck"
    console = next(path for path in (installed / "bin" / filename, installed / "Scripts" / filename) if path.exists())
    assert console.exists()
    assert "usage: chatcheck" in checked([str(console), "--help"], cwd=outside, env=environment).stdout
