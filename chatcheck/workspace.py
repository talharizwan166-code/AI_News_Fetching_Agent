"""Create starter files from installed resources, without overwriting user files."""

from importlib.resources import files
from pathlib import Path


def library_directory():
    installed = files("chatcheck").joinpath("suites")
    if installed.is_dir():
        return installed
    # The source tree maps the canonical top-level suite library into the wheel.
    return Path(__file__).resolve().parents[1] / "suites"


def init_workspace(directory="."):
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    templates = files("chatcheck").joinpath("workspace_templates")
    sources = {name: templates.joinpath(name) for name in ("target.json", ".env.example", "README.md")}
    sources["suite.json"] = library_directory().joinpath("starter.json")
    created, skipped = [], []
    for name, source in sources.items():
        path = destination / name
        if path.exists() or path.is_symlink():
            skipped.append(name)
            continue
        content = source.read_text(encoding="utf-8")
        try:
            # Exclusive creation protects existing files, directories and symlinks.
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
        except FileExistsError:
            skipped.append(name)
        else:
            created.append(name)
    return {"directory": str(destination), "created": created, "skipped": skipped}
