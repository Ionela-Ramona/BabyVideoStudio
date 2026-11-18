import re
from pathlib import Path

from .models import LogoSettings, Project

LOGO_PREFIX = "logo - "
ROOT = Path(__file__).resolve().parents[1]
DEFAULTS_DIR = ROOT / "defaults"
PROJECTS_DIR = ROOT / "projects"
OUTPUT_DIR = ROOT / "output"
INPUT_DIR = ROOT / "input"
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_name(name: str) -> str:
    """Keep Unicode, drop only what Windows forbids (also blocks path traversal)."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not cleaned:
        return "proiect"
    return f"_{cleaned}" if cleaned.split(".")[0].upper() in RESERVED else cleaned


def project_dir(name: str) -> Path:
    return PROJECTS_DIR / safe_name(name)


def save(project: Project) -> None:
    folder = project_dir(project.name)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "project.json").write_text(project.model_dump_json(indent=2), encoding="utf-8")


def load(name: str) -> Project:
    return Project.model_validate_json((project_dir(name) / "project.json").read_text(encoding="utf-8"))


def list_projects() -> list[str]:
    return sorted(p.parent.name for p in PROJECTS_DIR.glob("*/project.json"))


def media_dir(project: Project) -> Path:
    return project_dir(project.name) / "media"


def store_file(project: Project, filename: str, data: bytes) -> str:
    name = safe_name(Path(filename).name)
    media_dir(project).mkdir(parents=True, exist_ok=True)
    (media_dir(project) / name).write_bytes(data)
    return name


def save_logo_defaults(project: Project) -> None:
    DEFAULTS_DIR.mkdir(exist_ok=True)
    for old in DEFAULTS_DIR.glob(f"{LOGO_PREFIX}*"):
        if old.name != project.logo.file:
            old.unlink()
    (DEFAULTS_DIR / project.logo.file).write_bytes((media_dir(project) / project.logo.file).read_bytes())
    (DEFAULTS_DIR / "logo.json").write_text(project.logo.model_dump_json(indent=2), encoding="utf-8")


def apply_logo_defaults(project: Project) -> None:
    settings = DEFAULTS_DIR / "logo.json"
    if settings.exists():
        project.logo = LogoSettings.model_validate_json(settings.read_text(encoding="utf-8"))
        store_file(project, project.logo.file, (DEFAULTS_DIR / project.logo.file).read_bytes())


def unique_output(project_name: str) -> Path:
    """Never overwrite an earlier export."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    stem, n = safe_name(project_name), 1
    candidate = OUTPUT_DIR / f"{stem}.mp4"
    while candidate.exists():
        n += 1
        candidate = OUTPUT_DIR / f"{stem} ({n}).mp4"
    return candidate
