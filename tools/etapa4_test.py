"""Stage 4: the whole of "Țup, țup, iepuraș" through the automatic animation, end to end, checked.

    .venv\\Scripts\\python.exe tools\\etapa4_test.py [--fara-export]

Backs up the project, plans the animation in memory (the saved project is not changed), checks every scene for
characters meeting or leaving the frame, renders the 540p preview and the 1080p exports, verifies them, makes contact
sheets and reopens every saved project. Everything lands in output/teste animatie/etapa 4/.
"""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from baby_video_studio import director, library, projects, stage  # noqa: E402
from baby_video_studio.media import find_tool, probe_duration, verify_output  # noqa: E402
from baby_video_studio.models import AnimationSettings  # noqa: E402
from prototip_animatie import peak_mb  # noqa: E402

import ctypes  # noqa: E402

OUT = projects.ROOT / "output" / "teste animatie" / "etapa 4"
NAME = "Top, top"


def sync_report(timeline, total: float) -> dict:
    starts = [s.start for s in timeline]
    sung = [s for s in timeline if not s.text.startswith("🎵")]
    return {"randuri": len(timeline), "versuri": len(sung), "durata_s": round(total, 1),
            "in_ordine": starts == sorted(starts), "in_melodie": 0 <= starts[0] and starts[-1] < total,
            "incredere_mica": [s.text for s in sung if s.confidence < 0.5]}


def contact_sheet(video: Path, sheet: Path, seconds: float, tiles: int = 24) -> None:
    every = seconds / tiles
    subprocess.run([find_tool("ffmpeg"), "-v", "error", "-y", "-i", str(video), "-vf",
                    f"fps=1/{every:.3f},scale=480:-2,tile=6x{-(-tiles // 6)}", "-frames:v", "1", str(sheet)], check=True)


def export(scenes, settings, audio, logo, logo_file, fade, preview: bool, tag: str, total: float) -> dict:
    out = director.output_for(settings, preview)
    video = OUT / f"Tup etapa 4 {tag}{' previzualizare' if preview else ''}.mp4"
    began = time.perf_counter()
    info = director.export(scenes, settings, audio, video, preview, logo, logo_file, fade,
                           lambda f, m: print(f"\r  {video.name}: {m}   ", end="", flush=True))
    seconds = time.perf_counter() - began
    print()
    verify_output(video, *out.size, total, tolerance=0.5)
    contact_sheet(video, video.with_suffix(".jpg"), total)
    return {"fisier": video.name, "marime": out.size, "minute_randare": round(seconds / 60, 1),
            "ffmpeg_varf_mb": round(peak_mb(int(info["ffmpeg"]._handle))) if info.get("ffmpeg") else None}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {}
    backup = shutil.make_archive(str(OUT / f"copie de rezerva {NAME} {time.strftime('%Y-%m-%d %H-%M')}"), "zip",
                                 projects.project_dir(NAME))
    report["copie_de_rezerva"] = Path(backup).name

    p = projects.load(NAME)
    audio = projects.media_dir(p) / p.audio
    total = probe_duration(audio)
    report["sincronizare"] = sync_report(p.timeline, total)

    cast = library.characters()
    logo, logo_file = (p.logo, projects.media_dir(p) / p.logo.file) if p.logo.file and p.logo.enabled else (None, None)
    results = []
    for aspect in ("16:9", "9:16"):
        settings = AnimationSettings(characters=cast, decors=library.decors(), singer=cast[0], aspect=aspect)
        began = time.perf_counter()
        scenes = director.plan(p.timeline, total, settings)
        plan_s = time.perf_counter() - began
        size = director.output_for(settings, False).size
        checks = []
        for i, scene in enumerate(scenes):
            found = director.problems(scene, settings, size, before=scenes[i - 1] if i else None)
            checks.append({"scena": i + 1, "timp": f"{scene.start:.1f}-{scene.end:.1f}", "plan": director.describe(scene),
                           **{k: v for k, v in found.items() if v}})
        entry = {"format": aspect, "scene": len(scenes), "plan_secunde": round(plan_s, 2),
                 "acopera_melodia": scenes[0].start <= 0.05 and abs(scenes[-1].end - total) < 0.5,
                 "scene_cu_probleme": sum(1 for c in checks if len(c) > 3), "detalii": checks}
        if "--fara-export" not in sys.argv:
            tag = aspect.replace(":", "x")
            entry["exporturi"] = [export(scenes, settings, audio, logo, logo_file, p.fade_out, preview, tag, total)
                                  for preview in (True, False)]
        results.append(entry)
        print(f"{aspect}: {len(scenes)} scene, {entry['scene_cu_probleme']} cu probleme")
    report["animatie"] = results

    opened = {}
    for name in projects.list_projects():
        try:
            opened[name] = projects.load(name).kind
        except Exception as error:  # report it, keep checking the others
            opened[name] = f"EROARE: {error}"
    report["proiecte_vechi"] = opened
    report["python_varf_mb"] = round(peak_mb(ctypes.c_void_p(-1)))

    (OUT / "raport.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "animatie"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
