import base64
import hashlib
import importlib
import json
import io
import shutil
import subprocess
import sys
from pathlib import Path

import streamlit as st
from PIL import Image, ImageDraw, ImageOps
from streamlit import runtime

from baby_video_studio import (actions, audio, autosync, director, library, pictures, planner, projects, render, rig,
                               talking, timeline)
from baby_video_studio.media import MissingToolError, RenderError, find_tool, probe_duration
from baby_video_studio.models import FPS, AnimationSettings, AnimScene, LogoSettings, Project, Scene, Segment

MOTIONS = {"zoom_in": "Apropiere lentă", "zoom_out": "Depărtare lentă", "pan_right": "Panoramare spre dreapta", "pan_left": "Panoramare spre stânga"}
MOTION_KEYS = {label: key for key, label in MOTIONS.items()}
LOGO_MODES = {"always": "Pe toată durata videoclipului", "start": "Doar la început"}
LOGO_POSITIONS = {"top-right": "Sus, dreapta", "top-left": "Sus, stânga", "bottom-right": "Jos, dreapta", "bottom-left": "Jos, stânga", "center": "Centru"}
IMAGE_TYPES = ["png", "jpg", "jpeg"]
AUDIO_TYPES = ["mp3", "wav"]
EXAMPLE = ("La început, o fetiță doarme liniștită îmbrățișându-și ursulețul. Apoi apare un băiețel blond care doarme "
           "pe un nor pufos. Mai târziu, o oiță drăgălașă doarme printre stele. Luna strălucește blând. "
           "Repetă scenele natural până la final.")
LYRICS_EXAMPLE = "[Strofa 1]\nLuna strălucește lin...\n\n[Refren]\nNani, nani, puișor...\n\n[Strofa 2]\n...\n\n[Strofa 3]\n...\n\n[Refren final]\n...\n\n[Outro]\n..."
TIME_MARKS = {"auto": "≈", "lyrics": "📌", "manual": "✍️"}
STYLES = {"natural": "🦴 Naturală: brațe și picioare care se îndoaie (schelet), pași, sărituri",
          "fara_deformare": "🖼️ Fără deformare: personajele rămân exact ca în imagine, gesturile vin din cadre"}
TIMINGS = {"auto": "✨ Sincronizare automată cu vocea (AI local)",
           "synced": "🎤 Sincronizat cu versurile (marchezi tu timpii, ascultând melodia)",
           "estimated": "≈ Estimat automat (fără ascultarea vocii)"}
NUDGES = "".join(f'<button data-d="{d}">{label}</button>' for d, label in ((-0.5, "−0,5"), (-0.1, "−0,1"), (0.1, "+0,1"), (0.5, "+0,5")))

st.set_page_config(page_title="Baby Video Studio", page_icon="🌙", layout="wide")
HERE = Path(__file__).parent / "baby_video_studio"
SYNC_PLAYER = st.components.v2.component(
    "baby_video_studio.sync_player",
    html='<div class="sync"><div class="now"><img class="preview" alt=""><div><div class="clock"></div><div class="lyric"></div>'
         '<div class="next"></div></div></div><audio controls preload="auto"></audio><div class="buttons">'
         '<button class="mark"></button><button class="undo">↩️ Anulează ultimul marcaj</button><button class="back">⏪ 3 s</button>'
         '<label>Viteză la ascultare <select class="rate"><option value="1">1×</option><option value="0.75">0,75×</option>'
         '<option value="0.5">0,5×</option></select></label></div><div class="hint"></div>'
         '<div class="edit"><div class="selected"></div><div class="buttons"><button class="play">▶️ Ascultă rândul</button>'
         f'<span class="nudge start">Început {NUDGES} s</span><span class="nudge end">Sfârșit {NUDGES} s</span></div>'
         '<div class="buttons"><label>Imagine <select class="image"></select></label><button class="ok">✔️ E corect</button>'
         '<button class="next-unsure">⏭️ Următorul rând de verificat</button></div></div><ol class="rows"></ol></div>',
    css=(HERE / "sync_player.css").read_text(encoding="utf-8"),
    js=(HERE / "sync_player.js").read_text(encoding="utf-8"))
SUBTITLE_PLAYER = st.components.v2.component(
    "baby_video_studio.subtitle_player",
    html='<div class="subs"><audio controls preload="auto"></audio><div class="screen"><div class="line"></div></div>'
         '<div class="clock"></div></div>',
    css=".subs audio{width:100%}.subs .screen{background:#0b1030;border-radius:8px;min-height:84px;display:flex;align-items:"
        "flex-end;justify-content:center;padding:12px}.subs .line{color:#fff;background:rgba(0,0,0,.55);padding:4px 10px;"
        "border-radius:4px;font-size:1.3rem;text-align:center}.subs .line:empty{display:none}.subs .line.unsure{outline:2px "
        "solid #f5b301}.subs .clock{font-family:monospace;opacity:.75;margin-top:4px}",
    js=(HERE / "subtitle_player.js").read_text(encoding="utf-8"))
RIG_EDITOR = st.components.v2.component(
    "baby_video_studio.rig_editor",
    html='<div class="rig"><div class="stage"><img alt=""><svg></svg></div><div class="hint">Trage punctele la locul '
         'lor. Ține mouse-ul pe un punct ca să vezi ce este.</div></div>',
    css=".rig .stage{position:relative;display:inline-block}.rig img{display:block;max-height:520px;max-width:100%}"
        ".rig svg{position:absolute;inset:0;width:100%;height:100%;touch-action:none}.rig line{stroke:#2f80ff;"
        "opacity:.75}.rig circle{fill:#ffd400;stroke:#222;stroke-width:2px;vector-effect:non-scaling-stroke;cursor:grab}"
        ".rig circle.active{fill:#ff5a00}.rig .hint{font-size:.85rem;opacity:.8;margin-top:4px}",
    js=(HERE / "rig_editor.js").read_text(encoding="utf-8"))


def open_project(project: Project) -> None:
    st.session_state.project = project
    st.session_state.plan_key = plan_key(project) if project.scenes else None
    st.session_state.pop("result", None)
    st.session_state.pop("logo_result", None)
    st.session_state.pop("warnings", None)
    st.session_state.pop("timeline_warnings", None)
    st.session_state.timeline_rev = st.session_state.get("timeline_rev", 0) + 1


def plan_key(p: Project) -> str:
    inputs = (p.audio, p.images, p.storyboard, p.lyrics, sorted(p.image_tags.items()), p.scene_seconds, p.sync_music)
    return hashlib.sha1(repr(inputs).encode()).hexdigest()[:12]


def sidebar() -> None:
    st.sidebar.title("🌙 Baby Video Studio")
    existing = projects.list_projects()
    if existing:
        choice = st.sidebar.selectbox("Proiecte salvate", existing)
        if st.sidebar.button("Deschide proiectul", width="stretch"):
            open_project(projects.load(choice))
            st.rerun()
    with st.sidebar.form("new_project", clear_on_submit=True):
        name = st.text_input("Numele unui proiect nou", placeholder="Ex.: Somn ușor, puișor")
        if st.form_submit_button("Creează proiectul", width="stretch"):
            if not projects.safe_name(name) or not name.strip():
                st.error("Scrie un nume pentru proiect.")
            elif projects.safe_name(name) in existing:
                st.error("Există deja un proiect cu acest nume. Deschide-l din listă.")
            else:
                project = Project(name=name.strip())
                projects.apply_logo_defaults(project)
                projects.save(project)
                open_project(project)
                st.rerun()
    st.sidebar.divider()
    clips = [*(render.CACHE_DIR / "clips").glob("*.mp4"), *(render.CACHE_DIR / "animatie").glob("*.mp4")]
    size = sum(c.stat().st_size for c in clips) / 1024 ** 2
    st.sidebar.caption(f"Scene pregătite pentru refolosire: {len(clips)} ({size:.0f} MB)")
    if clips and st.sidebar.button("Golește memoria de scene", width="stretch"):
        for folder in render.CACHE_DIR.iterdir():
            if folder not in (autosync.CACHE, pictures.CACHE):  # the voice and picture analyses are small and slow to redo
                shutil.rmtree(folder, ignore_errors=True)
        st.rerun()


def media_section(p: Project) -> None:
    st.subheader("1. Melodia și imaginile")
    if st.button("📂 Preia fișierele din folderul input/"):
        take_from_input(p)
        st.rerun()

    left, right = st.columns(2)
    with left:
        upload = st.file_uploader("Melodia (MP3 sau WAV)", type=AUDIO_TYPES, key=f"audio_{p.name}")
        if upload and projects.safe_name(upload.name) != p.audio:
            p.audio = projects.store_file(p, upload.name, upload.getvalue())
            projects.save(p)
        if p.audio:
            path = projects.media_dir(p) / p.audio
            st.caption(f"🎵 {p.audio} — durată {probe_duration(path):.1f} secunde")
            st.audio(str(path))
    with right:
        uploads = st.file_uploader("Imaginile (PNG sau JPG)", type=IMAGE_TYPES, accept_multiple_files=True, key=f"images_{p.name}")
        for item in uploads or []:
            if projects.safe_name(item.name) not in p.images:
                p.images.append(projects.store_file(p, item.name, item.getvalue()))
                projects.save(p)

    if p.images:
        columns = st.columns(5)
        for index, name in enumerate(p.images):
            with columns[index % 5]:
                st.image(str(projects.media_dir(p) / name), caption=name, width="stretch")
                if seen := pictures.describe(p.image_seen.get(name, {})):
                    st.caption(f"👁️ Se vede: {seen}")
                tags = st.text_input("Ce se vede în imagine", p.image_tags.get(name, ""), key=f"tags_{p.name}_{name}",
                                     placeholder="ex.: fetiță, ursuleț, lună",
                                     help="Scrie tu ce apare în imagine, ca să fie aleasă pentru versurile și povestea potrivite.")
                if tags.strip():
                    p.image_tags[name] = tags
                else:
                    p.image_tags.pop(name, None)
                if st.button("Scoate", key=f"remove_{name}"):
                    p.images.remove(name)
                    p.image_tags.pop(name, None)
                    projects.save(p)
                    st.rerun()


def take_from_input(p: Project) -> None:
    audio = sorted((f for f in (projects.INPUT_DIR / "audio").glob("*") if f.suffix[1:].lower() in AUDIO_TYPES),
                   key=lambda f: f.stat().st_mtime)
    if audio:
        p.audio = projects.store_file(p, audio[-1].name, audio[-1].read_bytes())
    for image in sorted(projects.INPUT_DIR.joinpath("images").glob("*")):
        if image.suffix[1:].lower() in IMAGE_TYPES and projects.safe_name(image.name) not in p.images:
            p.images.append(projects.store_file(p, image.name, image.read_bytes()))
    projects.save(p)


def story_section(p: Project) -> None:
    st.subheader("2. Povestea")
    p.storyboard = st.text_area(
        "Descrie ce se întâmplă în videoclip", p.storyboard, height=130, placeholder=EXAMPLE, key=f"story_{p.name}",
        help="Povestea alege imaginile, în ordine. Poți lega o propoziție de o secțiune: „Refren: mama îi dă un sărut”. "
             "Fără versuri pe secțiuni, fiecare propoziție devine o scenă și poți fixa momente: „1:15 oița printre stele”.")
    st.caption("Cu sincronizarea după versuri (pasul 5), storyboard-ul automat se uită la conținutul imaginilor cu un model "
               "vizual local și le potrivește cu ce se cântă. Numele fișierelor și descrierile tale de la fiecare imagine "
               "contează și ele. Modul „estimat” alege doar după nume și descrieri.")
    p.lyrics = st.text_area("Versurile melodiei", p.lyrics, height=220, placeholder=LYRICS_EXAMPLE, key=f"lyrics_{p.name}",
                            help="Împarte versurile cu titluri între paranteze: [Strofa 1], [Refren], [Strofa 2], [Strofa 3], "
                                 "[Refren final], [Outro]. Dacă un rând începe cu un timp, de exemplu [1:15.5] Somn ușor, "
                                 "secțiunea lui pornește exact atunci.")
    sections = planner.parse_sections(p.lyrics)
    if sections:
        st.caption(f"Am găsit {len(sections)} secțiuni: " + ", ".join(s.label for s in sections) + ".")
    elif p.lyrics.strip():
        timed = len(audio.lyric_times(p.lyrics))
        st.caption(f"{timed} rânduri cu timp sunt folosite la sincronizare." if timed
                   else "Versurile nu au titluri de secțiuni, așa că nu influențează planul.")


def settings_section(p: Project) -> None:
    st.subheader("3. Stilul animației")
    st.radio("Mod de animație", ["🎬 Cinematic (gratuit)"], index=0)
    st.caption("Mișcare lentă a camerei, stele care sclipesc, particule și lumină blândă. "
               "Modurile Hibrid și AI local vor fi adăugate în etapele următoare.")
    a, b, c = st.columns(3)
    p.scene_seconds = a.slider("Durata unei scene (secunde)", 8.0, 30.0, float(p.scene_seconds), 1.0, key=f"scene_{p.name}")
    p.crossfade_seconds = b.slider("Tranziția între scene (secunde)", 1.0, 4.0, float(p.crossfade_seconds), 0.5, key=f"xf_{p.name}")
    with c:
        st.write("")
        p.fade_out = st.checkbox("Estompează imaginea la final", p.fade_out, key=f"fade_{p.name}",
                                 help="Imaginea se stinge lin spre albastru închis. Sunetul rămâne neschimbat.")
        p.sparkles = st.checkbox("Stele sclipitoare și particule", p.sparkles, key=f"sparkles_{p.name}",
                                 help="Debifează pentru imagini curate, doar cu mișcarea camerei.")
        p.sync_music = st.checkbox("Sincronizează scenele cu muzica", p.sync_music, key=f"sync_{p.name}",
                                   help="Scenele se schimbă la începutul frazelor și la schimbările din melodie, nu la intervale egale.")


def logo_section(p: Project) -> None:
    st.subheader("4. Logo canal")
    logo = p.logo
    picture, options = st.columns([1, 3])
    with picture:
        upload = st.file_uploader("Logo (PNG sau JPG)", type=IMAGE_TYPES, key=f"logo_file_{p.name}")
        if upload and st.session_state.get("logo_upload") != upload.file_id:
            st.session_state.logo_upload = upload.file_id
            logo.file = projects.store_file(p, projects.LOGO_PREFIX + upload.name, upload.getvalue())
            st.session_state[f"logo_on_{p.name}"] = logo.enabled = True
            projects.save(p)
        if logo.file:
            st.image(str(projects.media_dir(p) / logo.file), width=150)
            if not render.has_transparency(projects.media_dir(p) / logo.file):
                st.warning("Imaginea nu are fundal transparent, așa că fundalul ei se va vedea peste video.")
    with options:
        logo.enabled = st.checkbox("Afișează logo-ul", logo.enabled, key=f"logo_on_{p.name}", disabled=not logo.file,
                                   help="Logo-ul se pune peste videoclip, după ce scenele și tranzițiile sunt gata, așa că "
                                        "nu se mișcă odată cu camera și nu clipește la schimbarea imaginilor. Melodia nu se schimbă.")
        if not logo.file:
            st.caption("Încarcă un logo ca să poți activa această opțiune.")
        logo.mode = st.radio("Când apare", list(LOGO_MODES), list(LOGO_MODES).index(logo.mode), format_func=LOGO_MODES.get,
                             horizontal=True, key=f"logo_mode_{p.name}", disabled=not logo.enabled)
        always = logo.mode == "always"
        if always:
            st.caption("Watermark: logo-ul rămâne în colț în toate scenele, de la intro la outro, inclusiv în tranziții. "
                       "Recomandat: mic (în jur de 8%), puțin transparent (65%), într-un colț de sus, ca să nu acopere personajele.")
        a, b, c = st.columns(3)
        logo.size_percent = a.slider("Mărimea (% din lățime)", 5.0, 40.0, float(logo.size_percent), 1.0, key=f"logo_w_{p.name}")
        logo.opacity = b.slider("Opacitatea (%)", 20, 100, int(logo.opacity), 5, key=f"logo_o_{p.name}")
        logo.position = c.selectbox("Poziția", list(LOGO_POSITIONS), list(LOGO_POSITIONS).index(logo.position),
                                    format_func=LOGO_POSITIONS.get, key=f"logo_p_{p.name}")
        a, b, c = st.columns(3)
        logo.fade_in = a.slider("Apariție lină (secunde)", 0.0, 2.0, float(logo.fade_in), 0.1, key=f"logo_in_{p.name}")
        if not always:
            logo.seconds = b.slider("Durata (secunde)", 1.0, 10.0, float(logo.seconds), 0.5, key=f"logo_s_{p.name}")
            logo.fade_out = c.slider("Dispariție lină (secunde)", 0.0, 2.0, float(logo.fade_out), 0.1, key=f"logo_out_{p.name}")
        if st.button("💾 Salvează logo-ul și setările pentru proiectele viitoare", disabled=not logo.file):
            projects.save_logo_defaults(p)
            st.success("Proiectele noi vor porni cu acest logo și cu aceste setări.")

    with st.expander("Adaugă logo-ul pe un videoclip deja generat"):
        add_logo_to_existing(p)


def add_logo_to_existing(p: Project) -> None:
    videos = sorted((v for v in projects.OUTPUT_DIR.glob("*.mp4") if not v.name.endswith(".part.mp4")),
                    key=lambda v: v.stat().st_mtime, reverse=True)
    if not videos:
        st.caption("Încă nu există videoclipuri în folderul output/.")
        return
    names = {v.name: v for v in videos}
    chosen = st.selectbox("Videoclipul", list(names), key=f"logo_video_{p.name}")
    st.caption("Animația nu se refă, iar sunetul se copiază identic. Imaginea se codifică din nou, la calitate mare, "
               "și se creează un fișier nou; cel original rămâne neschimbat.")
    if st.button("Adaugă logo-ul pe acest videoclip", disabled=not p.logo.file):
        output = projects.unique_output(f"{names[chosen].stem} - cu logo")
        bar = st.progress(0.0, "Încep…")
        try:
            render.add_logo_to_video(names[chosen], projects.media_dir(p) / p.logo.file, p.logo, output,
                                     lambda fraction, message: bar.progress(min(fraction, 1.0), message))
        except RenderError as error:
            bar.empty()
            st.error(str(error))
            return
        st.session_state.logo_result = str(output)
    if st.session_state.get("logo_result") and Path(st.session_state.logo_result).exists():
        show_video(Path(st.session_state.logo_result), "logo_download")


def generate_plan(p: Project) -> None:
    audio_path = projects.media_dir(p) / p.audio
    salience, notes = None, []
    if p.sync_music:
        try:
            with st.spinner("Ascult melodia…"):
                salience = audio.analyze(audio_path, p.lyrics)
        except RenderError:
            notes.append("Nu am putut analiza melodia, așa că scenele sunt distribuite uniform.")
    p.scenes, warnings = planner.plan(p.storyboard, p.images, probe_duration(audio_path), p.scene_seconds, p.crossfade_seconds,
                                      salience, p.lyrics, p.image_tags)
    st.session_state.warnings = notes + warnings
    st.session_state.plan_key = plan_key(p)
    st.session_state.plan_version = st.session_state.get("plan_version", 0) + 1
    projects.save(p)


def scenes_section(p: Project) -> list[Scene] | None:
    st.subheader("5. Când apare fiecare imagine")
    if not p.audio or not p.images:
        st.info("Adaugă melodia și cel puțin o imagine, iar planul va apărea aici.")
        return None
    p.timing = st.radio("Cum se stabilesc momentele în care se schimbă imaginile?", list(TIMINGS), list(TIMINGS).index(p.timing),
                        format_func=TIMINGS.get, key=f"timing_{p.name}")
    if p.timing in ("auto", "synced"):
        return timeline_section(p)
    return p.scenes if plan_section(p) else None


@st.cache_data(show_spinner=False, max_entries=300)
def thumbnail(path: str, changed: float, width: int) -> str:
    with Image.open(path) as source:
        picture = ImageOps.exif_transpose(source).convert("RGBA")
    image = Image.new("RGBA", picture.size, (235, 240, 245, 255))  # a transparent background shows light, not black
    image.alpha_composite(picture)
    image = image.convert("RGB")
    image.thumbnail((width, width))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def thumbnails(p: Project, width: int) -> dict[str, str]:
    folder = projects.media_dir(p)
    return {name: thumbnail(str(folder / name), (folder / name).stat().st_mtime, width) for name in p.images}


def audio_url(path: Path) -> str:
    # ponytail: the media server behind st.audio has no public URL API; switch if Streamlit adds one.
    kind = "audio/wav" if path.suffix.lower() == ".wav" else "audio/mpeg"
    return runtime.get_instance().media_file_mgr.add(str(path), kind, f"sync-player-{path.name}")


def take_marks(key: str) -> None:
    """Times, images and confirmations from the player; ignored when the rows changed after the player loaded them."""
    p = st.session_state.project
    marks = (st.session_state.get(key) or {}).get("marks") or {}
    times = marks.get("times") or []
    if marks.get("rev") != st.session_state.get("timeline_rev") or len(times) != len(p.timeline):
        return
    images, confirmed = marks.get("images") or [], set(marks.get("ok") or [])
    for i, segment in enumerate(p.timeline):
        start = None if times[i] is None else round(float(times[i]), 2)
        if (i and start != segment.start) or i in confirmed:
            segment.confidence = None  # timed or checked by the user
            if i:
                segment.start = start
        if i < len(images) and images[i] in p.images and images[i] != segment.image:
            segment.image, segment.locked = images[i], True
    projects.save(p)


def unsure(segment: Segment) -> bool:
    return segment.confidence is not None and segment.confidence < autosync.SURE


def install(package: str) -> None:
    with st.spinner(f"Instalez {package}. Poate dura câteva minute; lasă fereastra deschisă…"):
        done = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", package],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode:
        st.error(f"Instalarea nu a reușit. Verifică internetul și încearcă din nou.\n\n{done.stderr[-800:]}")
    else:
        importlib.invalidate_caches()
        st.rerun()


def auto_step(p: Project, total_seconds: float) -> None:
    st.markdown("**Pasul 1. Sincronizarea automată cu vocea**")
    st.caption("Un model de recunoaștere a vocii (faster-whisper) rulează pe calculatorul tău, fără cont și fără cloud, și "
               "ascultă când se cântă fiecare cuvânt. Textul vine mereu din versurile tale, cu toate refrenele repetate. Pentru "
               "un cântec de 3–4 minute durează 1–2 minute; prima dată se descarcă modelul (~1,6 GB). Rezultatul se păstrează, "
               "deci aceeași melodie nu se mai analizează a doua oară.")
    if not autosync.available():
        st.warning("Lipsește componenta de recunoaștere a vocii (faster-whisper).")
        if st.button("📦 Instalează componenta (o singură dată, ~100 MB)"):
            install("faster-whisper")
        return
    path = projects.media_dir(p) / p.audio
    can_separate = autosync.vocals_available()
    vocals = st.checkbox("Separă întâi vocea de muzică (Demucs, mai lent)", key=f"vocals_{p.name}", disabled=not can_separate,
                         help="Folosește doar dacă rezultatul fără separare are multe rânduri ⚠️. Adaugă 1–2 minute. La "
                              "melodiile încercate, recunoașterea a fost mai bună fără separare.")
    if not can_separate:
        with st.expander("Separarea vocii nu este instalată (opțional)"):
            st.caption("Necesară doar dacă muzica acoperă vocea. Ocupă aproximativ 1 GB pe disc.")
            if st.button("📦 Instalează separarea vocii (Demucs)"):
                install("demucs")
    # Only a complete, ordered timeline with times set by the user is worth a confirmation; an old or broken one is not.
    edited = (timeline.in_order(p.timeline, total_seconds)
              and any(s.start is not None and s.confidence is None for s in p.timeline[1:]))
    allowed = not edited or st.checkbox("Înlocuiește și timpii corectați de mine", key=f"auto_replace_{p.name}")
    ready = autosync.is_cached(path, vocals)
    left, right = st.columns([2, 1])
    run = left.button("✨ Sincronizează automat" + (" (melodia e deja analizată)" if ready else ""), type="primary",
                      disabled=not allowed or not p.lyrics.strip())
    again = right.button("🔄 Reanalizează melodia", disabled=not allowed or not p.lyrics.strip() or not ready,
                         help="Uită analiza păstrată și ascultă din nou toată melodia (1–2 minute). Folosește dacă timpii "
                              "găsiți sunt greșiți sau dacă ai înlocuit fișierul melodiei.")
    if run or again:
        if again:
            autosync.forget(path, vocals)
        bar = st.progress(0.0, "Încep…")
        try:
            words = autosync.hear(path, vocals, lambda fraction, message: bar.progress(min(max(fraction, 0.0), 1.0), message))
        except RenderError as error:
            bar.empty()
            st.error(str(error))
            return
        rows = autosync.align(timeline.rows_from_lyrics(p.lyrics), words, total_seconds)
        if not words or not rows:
            st.error("Nu am auzit niciun cuvânt cântat în melodie. Folosește sincronizarea manuală.")
            return
        if not timeline.in_order(rows, total_seconds):
            st.error("Sincronizarea automată a dat timpi care nu sunt în ordine, așa că nu am salvat-o. Dacă ai scris timpi în "
                     "versuri (de exemplu [1:05]), verifică-i, apoi apasă „🔄 Reanalizează melodia”.")
            return
        suggest(p, rows, total_seconds)
        st.rerun()
    if not p.lyrics.strip():
        st.info("Scrie versurile la pasul 2, exact cum se cântă, apoi apasă „Sincronizează automat”.")


def suggest(p: Project, rows: list[Segment], total_seconds: float, keep_mine: bool = False) -> None:
    """Pictures for the rows: the automatic storyboard once the rows are timed, otherwise by section, as before."""
    notes = []
    if p.kind == "animation":  # the animation chooses its own decors and characters: only the times are kept
        p.timeline, st.session_state.timeline_warnings = rows, []
        st.session_state.timeline_rev = st.session_state.get("timeline_rev", 0) + 1
        projects.save(p)
        return
    if timeline.in_order(rows, total_seconds):
        bar = st.progress(0.0, "Mă uit la imagini…")
        files = {name: projects.media_dir(p) / name for name in p.images}
        p.image_seen, note = pictures.evidence(files, p.image_tags, lambda f, m: bar.progress(min(max(f, 0.0), 1.0), m))
        bar.empty()
        try:
            rows, notes = timeline.storyboard(rows, p.images, p.image_seen, p.image_tags, total_seconds,
                                              p.crossfade_seconds, keep_mine)
        except ValueError as error:
            st.session_state.timeline_warnings = [str(error)]
            return
        notes = [note, *notes] if note else notes
    else:
        rows, notes = timeline.suggest_images(rows, p.images, p.storyboard, p.image_tags, total_seconds, p.scene_seconds)
    p.timeline, st.session_state.timeline_warnings = rows, notes
    st.session_state.timeline_rev = st.session_state.get("timeline_rev", 0) + 1
    projects.save(p)


def timeline_section(p: Project) -> list[Scene] | None:
    total_seconds = probe_duration(projects.media_dir(p) / p.audio)
    total = round(total_seconds * FPS)
    if p.timing == "auto":
        auto_step(p, total_seconds)
        rebuild = "Sincronizează automat"
    else:
        st.markdown("**Pasul 1. Rândurile din versuri**")
        marked = any(s.start is not None for s in p.timeline[1:])
        allowed = not marked or st.checkbox("Înlocuiește și timpii pe care i-am marcat", key=f"rebuild_{p.name}")
        if st.button("📝 Creează rândurile din versuri", disabled=not allowed or not p.lyrics.strip()):
            suggest(p, timeline.rows_from_lyrics(p.lyrics), total_seconds)
            st.rerun()
        rebuild = "Creează rândurile din versuri"
        if not p.timeline:
            st.info("Scrie versurile la pasul 2, cu titluri ca [Strofa 1] și [Refren], apoi apasă „Creează rândurile din versuri”. "
                    "Fiecare rând cântat devine un rând în cronologie, inclusiv refrenele repetate.")
    if not p.timeline:
        return None
    if timeline.lyric_lines(timeline.rows_from_lyrics(p.lyrics)) != timeline.lyric_lines(p.timeline):
        st.warning(f"Rândurile de mai jos nu mai corespund versurilor de la pasul 2. Dacă ai schimbat versurile, apasă „{rebuild}”.")
    for warning in st.session_state.get("timeline_warnings", []):
        st.warning(warning)

    if p.timing == "auto":
        st.markdown("**Pasul 2. Verifică doar rândurile marcate cu ⚠️**")
        flagged = [i + 1 for i, s in enumerate(p.timeline) if unsure(s)]
        if all(s.confidence is None for s in p.timeline):
            st.warning("Rândurile de mai jos nu sunt sincronizate cu vocea: timpii lor sunt vechi sau lipsesc. Apasă "
                       "„✨ Sincronizează automat” mai sus.")
        elif flagged:
            st.warning(f"{len(flagged)} din {len(p.timeline)} rânduri sunt nesigure (⚠️): {timeline._rows(flagged)}. "
                       "Apasă „⏭️ Următorul rând de verificat”, ascultă și corectează cu butoanele −/+, sau apasă „✔️ E corect”.")
        elif timeline.in_order(p.timeline, total_seconds):
            st.success("Niciun rând nesigur. Ascultă totuși o dată melodia de mai jos: imaginea se schimbă la timpii găsiți.")
        st.caption("Timpii sunt găsiți ascultând vocea și pot fi decalați cu câteva zecimi de secundă. Apasă pe un rând: se aude "
                   "bucata lui și îi poți muta începutul sau sfârșitul cu −/+ (sfârșitul unui rând este începutul următorului) "
                   "sau îi poți schimba imaginea. Tasta **M** marchează în continuare începutul rândului ales, ca în modul manual. "
                   "Rândurile 🎤 sunt cântate în melodie, dar lipsesc din versurile tale.")
    else:
        st.markdown("**Pasul 2. Marchează timpii ascultând melodia**")
        st.caption("Pornește melodia. Când începe rândul încadrat, apasă tasta **M** sau butonul roșu: rândul anterior se termină în "
                   "același moment. Bara de spațiu pornește și oprește melodia. Ai greșit? „Anulează ultimul marcaj”, sau apasă "
                   "pe rând ca să-l marchezi din nou (se aude bucata lui, de la o secundă înainte). Viteza mai mică ajută doar la "
                   "ascultare; videoclipul păstrează melodia neschimbată.")
    key = f"player_{p.name}"
    SYNC_PLAYER(key=key, on_marks_change=lambda: take_marks(key), data={
        "audio": audio_url(projects.media_dir(p) / p.audio), "rev": st.session_state.setdefault("timeline_rev", 0),
        "total": total / FPS, "thumbs": thumbnails(p, 400), "images": p.images,
        "rows": [{"text": s.text, "section": s.section, "start": s.start, "image": s.image, "unsure": unsure(s),
                  "confidence": s.confidence} for s in p.timeline]})

    if storyboard_step(p, total_seconds):
        st.rerun()
    with st.expander("Toate rândurile: timpi, imagini și efecte, rând cu rând"):
        st.caption("Rândurile consecutive cu aceeași imagine formează o singură scenă, fără tranziție. Poți scrie un timp "
                   "(de exemplu 1:15.5), adăuga un rând (de exemplu o pauză instrumentală) sau șterge unul.")
        if timeline_table(p, total):
            st.rerun()

    errors = timeline.problems(p.timeline, p.images, total_seconds, p.crossfade_seconds)
    for error in errors:
        st.error(error)
    if errors:
        return None
    scenes = timeline.to_scenes(p.timeline, total, planner.even_crossfade_frames(p.crossfade_seconds), p.image_tags,
                                p.sparkles)
    st.success(f"Cronologia este completă: {len(p.timeline)} rânduri și {len(scenes)} scene acoperă toată melodia, "
               f"de la 0:00.0 la {planner.stamp(total)}, în ordine și fără suprapuneri. Fiecare tranziție începe exact la "
               "timpul marcat, deci nicio imagine nu apare înaintea versului ei.")
    return scenes


def storyboard_step(p: Project, total_seconds: float) -> bool:
    """The automatic storyboard and its scenes; True when something changed (saved, needs a rerun)."""
    st.markdown("**Pasul 3. Storyboard: imaginea fiecărei scene**")
    timed = timeline.in_order(p.timeline, total_seconds)
    st.caption("Un model vizual mic rulează pe calculatorul tău (gratuit, fără cont) și vede ce e în fiecare imagine: personaje, "
               "obiecte, decor, momentul zilei. Versurile la rând care vorbesc despre același lucru devin o scenă de "
               "aproximativ 5–12 secunde, cu imaginea care se potrivește cel mai bine. Timpii melodiei nu se schimbă. "
               "Prima dată se descarcă modelul (~370 MB)." if timed else
               "Imaginile sunt sugerate pe secțiuni. După ce toate rândurile au timp, storyboard-ul automat le grupează în "
               "scene și alege imaginile după conținut.")
    mine = any(s.locked for s in p.timeline)
    replace = mine and st.checkbox("Înlocuiește și imaginile alese de mine", key=f"replace_mine_{p.name}",
                                   help="Altfel, imaginile pe care le-ai schimbat tu rămân la locul lor.")
    if st.button("✨ Creează storyboard automat", type="primary", disabled=not p.images,
                 help="Alege imaginile pentru toate scenele. Poți apăsa din nou oricând: imaginile alese de tine rămân."):
        suggest(p, p.timeline, total_seconds, keep_mine=not replace)
        return True
    if not timed or not p.image_seen:
        return False

    scenes = timeline.scene_list(p.timeline, p.images, p.image_seen, p.image_tags, total_seconds)
    unsure_scenes = sum(s["check"] for s in scenes)
    if unsure_scenes:
        st.warning(f"{unsure_scenes} din {len(scenes)} scene au o imagine nepotrivită (⚠️). Alege altă imagine sau adaugă "
                   "una cum sugerează coloana „Sugestie”.")
    else:
        st.success(f"Storyboard: {len(scenes)} scene, toate cu o imagine potrivită. Verifică totuși previzualizarea.")
    only = st.checkbox("Arată doar scenele care necesită verificare", key=f"only_unsure_{p.name}")
    small = thumbnails(p, 160)
    shown = [(n, s) for n, s in enumerate(scenes) if s["check"] or not only]
    rows = [{"Scena": n + 1, "Verifică": "⚠️" if s["check"] else "✅", "Potrivire": round(s["match"] * 100),
             "Timp": f"{planner.stamp(round(s['start'] * FPS))} – {planner.stamp(round(s['end'] * FPS))}",
             "Versuri": s["text"], "Imagine": s["image"] or None, "Previzualizare": small.get(s["image"]),
             "Sugestie": " · ".join(x for x in (s["hint"], "aleasă de tine" if s["mine"] else "") if x)} for n, s in shown]
    version = hashlib.sha1(p.model_dump_json(include={"timeline", "image_seen"}).encode()).hexdigest()[:10]
    edited = st.data_editor(
        rows, key=f"scenes_{p.name}_{version}_{only}", hide_index=True, width="stretch",
        disabled=["Scena", "Verifică", "Potrivire", "Timp", "Versuri", "Previzualizare", "Sugestie"],
        column_config={
            "Scena": st.column_config.NumberColumn(width="small"),
            "Verifică": st.column_config.TextColumn(width="small"),
            "Potrivire": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d%%", width="small",
                                                         help="Cât de bine se potrivește imaginea cu ce se cântă în scenă."),
            "Versuri": st.column_config.TextColumn(width="large"),
            "Imagine": st.column_config.SelectboxColumn(options=p.images, help="Alege altă imagine pentru toată scena."),
            "Previzualizare": st.column_config.ImageColumn(width="small"),
        })
    changed = False
    for row in edited:
        scene = scenes[row["Scena"] - 1]
        if row.get("Imagine") in p.images and row["Imagine"] != scene["image"]:
            for r in scene["rows"]:
                p.timeline[r] = p.timeline[r].model_copy(update={"image": row["Imagine"], "locked": True})
            changed = True
    if changed:
        st.session_state.timeline_rev = st.session_state.get("timeline_rev", 0) + 1
        projects.save(p)
    return changed


def timeline_table(p: Project, total: int) -> bool:
    """The editable timeline; True when the user changed something (saved, needs a rerun)."""
    shown = [planner.stamp(round(t * FPS)) if t is not None else "" for t in timeline.starts(p.timeline)]
    small = thumbnails(p, 160)
    rows = [{"Nr": i + 1, "Sigur": "" if s.confidence is None else f"{'⚠️' if unsure(s) else '✅'} {s.confidence:.0%}",
             "Secțiune": s.section, "Versuri": s.text, "Început": shown[i],
             "Sfârșit": shown[i + 1] if i + 1 < len(shown) else planner.stamp(total),
             "Imagine": s.image or None, "Previzualizare": small.get(s.image), "Efect animație": MOTIONS[s.motion],
             } for i, s in enumerate(p.timeline)]
    version = hashlib.sha1(p.model_dump_json(include={"timeline"}).encode()).hexdigest()[:10]
    edited = st.data_editor(
        rows, key=f"timeline_{p.name}_{version}", hide_index=True, num_rows="dynamic", width="stretch",
        disabled=["Nr", "Sigur", "Sfârșit", "Previzualizare"],
        column_config={
            "Nr": st.column_config.NumberColumn(width="small"),
            "Sigur": st.column_config.TextColumn(width="small", help="Cât de sigură e sincronizarea automată. ⚠️ = verifică "
                                                                     "rândul. Gol = timp pus de tine."),
            "Versuri": st.column_config.TextColumn(width="large"),
            "Început": st.column_config.TextColumn(width="small", help="Ex.: 1:15.5. Sfârșitul unui rând este începutul următorului."),
            "Sfârșit": st.column_config.TextColumn(width="small"),
            "Imagine": st.column_config.SelectboxColumn(options=p.images),
            "Previzualizare": st.column_config.ImageColumn(width="small"),
            "Efect animație": st.column_config.SelectboxColumn(options=list(MOTION_KEYS)),
        })
    updated = []
    for position, row in enumerate(edited):
        number = row.get("Nr")
        old = p.timeline[number - 1] if number else Segment()
        text = (row.get("Început") or "").strip()
        if position == 0:
            start = 0.0
        elif number and text == shown[number - 1]:
            start = old.start
        elif not text:
            start = None
        elif (frames := planner.parse_stamp(text)) is None:
            st.error(f"Nu înțeleg timpul „{text}” de la rândul {position + 1}. Scrie-l așa: 1:15.5")
            return False
        else:
            start = frames / FPS
        image = row.get("Imagine") or ""
        updated.append(Segment(text=row.get("Versuri") or "", section=row.get("Secțiune") or "", start=start, image=image,
                               motion=MOTION_KEYS.get(row.get("Efect animație"), old.motion),
                               confidence=old.confidence if number and start == old.start else None,
                               locked=old.locked or bool(number and image != old.image)))
    if any(not row.get("Nr") for row in edited) and all(s.start is not None for s in updated):
        updated = [updated[0], *sorted(updated[1:], key=lambda s: s.start)]  # a new row goes where its time says
    if updated == p.timeline:
        return False
    p.timeline = updated
    st.session_state.timeline_rev = st.session_state.get("timeline_rev", 0) + 1
    projects.save(p)
    return True


def plan_section(p: Project) -> bool:
    corrected = any(s.time_source == "manual" for s in p.scenes)
    allowed = not corrected or st.checkbox("Înlocuiește și timpii corectați de mine", key=f"replace_{p.name}")
    if st.button("🎬 Generează planul scenelor", disabled=not allowed):
        generate_plan(p)
        st.rerun()
    if not p.scenes:
        st.info("Apasă „Generează planul scenelor”. Vei putea verifica și corecta planul înainte de randare.")
        return False

    total = round(probe_duration(projects.media_dir(p) / p.audio) * FPS)
    if p.scenes[-1].end_frame != total:
        st.error("Melodia s-a schimbat și planul nu i se mai potrivește. Generează din nou planul scenelor.")
        return False
    absent = sorted({s.image for s in p.scenes} - set(p.images))
    if absent:
        st.error(f"Planul folosește imagini scoase din proiect ({', '.join(absent)}). Generează din nou planul scenelor.")
        return False
    if st.session_state.get("plan_key") != plan_key(p):
        st.warning("Ai schimbat povestea, versurile, imaginile sau setările după acest plan. "
                   "Apasă „Generează planul scenelor” ca să le folosești; altfel se randează planul de mai jos.")
    for warning in st.session_state.get("warnings", []):
        st.warning(warning)

    xf = planner.even_crossfade_frames(p.crossfade_seconds)
    if planner.crossfade_of(p.scenes) not in (None, xf):
        try:
            p.scenes = planner.retime(p.scenes, planner.scene_cuts(p.scenes), xf, total)
        except ValueError as error:
            st.error(f"{error} Micșorează tranziția sau corectează timpii.")
            return False

    rows = [{"Verifică": "⚠️" if s.auto_matched else "", "Secțiune": s.lyric_section, "Imagine": s.image,
             "Început": planner.stamp(s.start_frame + xf // 2 if i else 0),
             "Sfârșit": planner.stamp(s.end_frame - xf // 2 if i < len(p.scenes) - 1 else total),
             "Timp": TIME_MARKS[s.time_source], "Efect animație": MOTIONS[s.motion], "Muzică": "🎵" if s.music_cut else "",
             "Particule": s.particles, "Nori": s.clouds, "Scenă": s.description or "(imagine fără descriere)",
             } for i, s in enumerate(p.scenes)]
    edited = st.data_editor(
        rows, key=f"plan_{p.name}_{st.session_state.get('plan_version', 0)}", hide_index=True, num_rows="fixed", width="stretch",
        disabled=["Verifică", "Timp", "Muzică", "Scenă"],
        column_config={
            "Verifică": st.column_config.TextColumn(width="small"),
            "Timp": st.column_config.TextColumn(width="small"),
            "Muzică": st.column_config.TextColumn(width="small"),
            "Început": st.column_config.TextColumn(width="small", required=True),
            "Sfârșit": st.column_config.TextColumn(width="small", required=True),
            "Scenă": st.column_config.TextColumn(width="medium"),
            "Imagine": st.column_config.SelectboxColumn(options=p.images, required=True),
            "Efect animație": st.column_config.SelectboxColumn(options=list(MOTION_KEYS), required=True),
        })
    for scene, row in zip(p.scenes, edited):
        scene.image, scene.motion = row["Imagine"], MOTION_KEYS[row["Efect animație"]]
        scene.lyric_section, scene.particles, scene.clouds = row["Secțiune"] or "", row["Particule"], row["Nori"]
    try:
        retimed = planner.apply_time_edits(p.scenes, [r["Început"] for r in edited], [r["Sfârșit"] for r in edited], xf, total)
    except ValueError as error:
        st.error(f"{error} Videoclipul se poate genera după ce corectezi timpul.")
        return False
    if retimed:
        p.scenes = retimed
        st.session_state.plan_version = st.session_state.get("plan_version", 0) + 1
        projects.save(p)
        st.rerun()

    st.caption(f"{len(p.scenes)} scene. ≈ înseamnă timp estimat din cantitatea de text și din schimbările muzicii: aplicația "
               "nu aliniază versurile cu vocea, așa că ascultă melodia și corectează timpii direct în tabel (de exemplu 1:15.5). "
               "✍️ = corectat de tine, 📌 = scris în versuri. 🎵 = scena începe la o schimbare clară din melodie. "
               "⚠️ = nicio potrivire clară cu povestea sau versurile: alege imaginea din tabel.")
    return True


def seconds_text(seconds: float | None) -> str:
    return "" if seconds is None else f"{int(seconds // 60)}:{seconds % 60:05.2f}"


def subtitles_section(p: Project) -> None:
    """Subtitles for YouTube from the synced lyrics: no new audio analysis, the timeline's own times."""
    if p.timing not in ("auto", "synced") or not p.audio or not p.timeline:
        return
    st.subheader("📝 Subtitrări YouTube")
    st.caption("Fiecare vers din cronologie devine o subtitrare, cu textul tău exact (cu diacritice) și cu timpii sincronizați, "
               "inclusiv refrenele repetate. Pauzele instrumentale și rândurile 🎤 nu primesc subtitrare. Fișierul .srt se "
               "încarcă în YouTube Studio → Subtitrări → Încarcă fișierul → Cu sincronizare.")
    total_seconds = probe_duration(projects.media_dir(p) / p.audio)
    if st.button("📝 Generează subtitrarea", help="Preia versurile și timpii din cronologie. Înlocuiește corecturile "
                                                  "făcute mai jos în tabelul subtitrărilor."):
        p.subtitles = timeline.subtitles(p.timeline, total_seconds, autosync.SURE)
        st.session_state.subtitles_rev = st.session_state.get("subtitles_rev", 0) + 1
        projects.save(p)
    if not p.subtitles:
        st.info("Apasă „Generează subtitrarea” după ce versurile sunt sincronizate.")
        return
    if timeline.lyric_lines(p.timeline) != [s.text for s in p.subtitles]:
        st.caption("ℹ️ Textul subtitrărilor diferă de cronologie (l-ai corectat sau ai schimbat versurile). Apasă din nou "
                   "„Generează subtitrarea” dacă vrei să le refaci din cronologie.")

    unsure_lines = [n for n, s in enumerate(p.subtitles, 1) if s.unsure]
    if unsure_lines:
        st.warning(f"Sincronizare nesigură la subtitrările {timeline._rows(unsure_lines)} (⚠️). Ascultă-le mai jos și "
                   "corectează timpii în tabel dacă e nevoie.")
    SUBTITLE_PLAYER(key=f"subs_player_{p.name}", data={
        "audio": audio_url(projects.media_dir(p) / p.audio), "total": total_seconds,
        "cues": [{"n": n, "text": s.text, "start": s.start, "end": s.end, "unsure": s.unsure}
                 for n, s in enumerate(p.subtitles, 1) if s.start is not None and s.end is not None]})

    rows = [{"Nr": n, "Verifică": "⚠️" if s.unsure else "", "Început": seconds_text(s.start), "Sfârșit": seconds_text(s.end),
             "Text": s.text} for n, s in enumerate(p.subtitles, 1)]
    edited = st.data_editor(
        rows, key=f"subtitles_{p.name}_{st.session_state.get('subtitles_rev', 0)}", hide_index=True, width="stretch",
        disabled=["Nr", "Verifică"],
        column_config={"Nr": st.column_config.NumberColumn(width="small"), "Verifică": st.column_config.TextColumn(width="small"),
                       "Început": st.column_config.TextColumn(width="small", help="Ex.: 1:15.50"),
                       "Sfârșit": st.column_config.TextColumn(width="small"), "Text": st.column_config.TextColumn(width="large")})
    changed = []
    for row, old in zip(edited, p.subtitles):
        times = []
        for column, value in (("Început", old.start), ("Sfârșit", old.end)):
            text = (row.get(column) or "").strip()
            if text == seconds_text(value):
                times.append(value)
            elif not text:
                times.append(None)
            elif planner.parse_stamp(text) is None:
                st.error(f"Nu înțeleg timpul „{text}” de la subtitrarea {row['Nr']}. Scrie-l așa: 1:15.50")
                return
            else:
                times.append(round(planner.parse_seconds(text), 3))
        update = {"text": row.get("Text") or "", "start": times[0], "end": times[1]}
        changed.append(old.model_copy(update={**update, "unsure": old.unsure and (times[0], times[1]) == (old.start, old.end)}))
    if changed != p.subtitles:
        p.subtitles = changed
        projects.save(p)
        st.session_state.subtitles_rev = st.session_state.get("subtitles_rev", 0) + 1
        st.rerun()

    errors = timeline.subtitle_problems(p.subtitles, total_seconds)
    for error in errors[:8]:
        st.error(error)
    if len(errors) > 8:
        st.error(f"… și încă {len(errors) - 8} probleme.")
    name = timeline.srt_name(p.name)
    st.download_button("⬇️ Descarcă subtitrarea .srt", ("" if errors else timeline.to_srt(p.subtitles)).encode("utf-8"),
                       file_name=name, mime="application/x-subrip", disabled=bool(errors), type="primary",
                       help="Se descarcă doar când toate subtitrările au timpi valizi, fără suprapuneri.")
    if not errors:
        st.caption(f"{len(p.subtitles)} subtitrări, fișier {name}, UTF-8.")


def show_video(path: Path, key: str) -> None:
    st.success(f"Videoclipul este gata și verificat: {path}")
    st.video(str(path))
    with path.open("rb") as handle:
        st.download_button("⬇️ Descarcă MP4", handle, file_name=path.name, mime="video/mp4", key=key)


def render_section(p: Project, scenes: list[Scene]) -> None:
    st.subheader("6. Videoclipul")
    if p.logo.file and not p.logo.enabled:
        st.info("Logo-ul canalului este oprit pentru acest proiect, așa că nu va apărea în videoclip. Bifează "
                "„Afișează logo-ul” la secțiunea 4.")
    elif p.logo.file:
        st.caption(f"Logo: {LOGO_MODES[p.logo.mode].lower()}, {LOGO_POSITIONS[p.logo.position].lower()}, "
                   f"{p.logo.size_percent:.0f}% din lățime, opacitate {p.logo.opacity}%.")
    preview, full = st.columns(2)
    want_preview = preview.button(f"👀 Previzualizare rapidă ({render.PREVIEW_SECONDS} secunde)", width="stretch")
    want_full = full.button("✨ Generează videoclipul complet", type="primary", width="stretch")
    if want_preview or want_full:
        projects.save(p)
        output = projects.unique_output(p.name) if want_full else projects.project_dir(p.name) / "previzualizare.mp4"
        bar = st.progress(0.0, "Încep…")
        try:
            render.render_video(
                scenes, projects.media_dir(p), projects.media_dir(p) / p.audio, output,
                render.FULL if want_full else render.PREVIEW,
                planner.even_crossfade_frames(p.crossfade_seconds), p.fade_out,
                None if want_full else render.PREVIEW_SECONDS * FPS,
                lambda fraction, message: bar.progress(min(fraction, 1.0), message),
                logo_file=projects.media_dir(p) / p.logo.file if p.logo.enabled and p.logo.file else None, logo=p.logo)
        except RenderError as error:
            bar.empty()
            st.error(str(error))
            return
        st.session_state.result = str(output)

    result = st.session_state.get("result")
    if result and Path(result).exists():
        show_video(Path(result), "video_download")


KINDS = {"music": "🎵 Videoclip muzical", "talking": "🌟 Personaj vorbitor – Lip Sync",
         "animation": "🎬 Animație automată – Personaje multiple"}
FEATURES = ("Gura", "Ochiul din stânga", "Ochiul din dreapta")


def marked(picture: Image.Image, face: talking.Face | None, width: int = 520) -> Image.Image:
    """The character on a checkerboard-free plain backdrop, with the found mouth (red) and eyes (green)."""
    scale = width / picture.width
    shown = Image.new("RGBA", picture.size, (88, 92, 140, 255))
    shown.alpha_composite(picture.convert("RGBA"))
    shown = shown.convert("RGB").resize((width, round(picture.height * scale)))
    if face:
        draw = ImageDraw.Draw(shown)
        for box, colour in ((face.mouth, (255, 40, 40)), *((e, (40, 230, 60)) for e in face.eyes)):
            draw.rectangle([round(v * scale) for v in box], outline=colour, width=3)
    return shown


def expressions(picture: Image.Image, face: talking.Face, variants: dict[str, Path]) -> Image.Image:
    """The face in every shape, small, to check the mouth and eyes were found right."""
    scale = min(1.0, 500 / picture.width)
    small = picture.convert("RGBA").resize((round(picture.width * scale), round(picture.height * scale)), Image.LANCZOS)
    resize = lambda box: tuple(round(v * scale) for v in box)  # noqa: E731
    shapes = {}
    for shape, path in variants.items():
        with Image.open(path) as source:
            shapes[shape] = source.convert("RGBA").resize(small.size, Image.LANCZOS)
    puppet = talking.Puppet(small, talking.Face(resize(face.mouth), [resize(e) for e in face.eyes]), shapes)
    left = max(0, min(e[0] for e in face.eyes) * scale - 20)
    top = max(0, min(e[1] for e in face.eyes) * scale - 20)
    right = min(small.width, max(e[2] for e in face.eyes) * scale + 20)
    bottom = min(small.height, face.mouth[3] * scale + 25)
    tiles = [puppet.frame(o, r, b).crop((round(left), round(top), round(right), round(bottom)))
             for o, r, b in ((0, 0, 0), (0.3, 0, 0), (0.7, 0, 0), (1, 0, 0), (0.6, 0.9, 0), (0, 0, 1))]
    sheet = Image.new("RGBA", (sum(t.width for t in tiles) + 8 * len(tiles), tiles[0].height), (255, 255, 255, 0))
    for n, tile in enumerate(tiles):
        backdrop = Image.new("RGBA", tile.size, (88, 92, 140, 255))
        backdrop.alpha_composite(tile)
        sheet.paste(backdrop, (n * (tile.width + 8), 0))
    return sheet


def box_sliders(label: str, box: tuple, size: tuple[int, int], key: str) -> tuple:
    """Centre and size of one feature, set with sliders."""
    width, height = size
    st.markdown(f"**{label}**")
    a, b, c, d = st.columns(4)
    x = a.slider("Centru, orizontal", 0, width, (box[0] + box[2]) // 2, key=f"{key}_x")
    y = b.slider("Centru, vertical", 0, height, (box[1] + box[3]) // 2, key=f"{key}_y")
    w = c.slider("Lățime", 10, width // 2, box[2] - box[0], key=f"{key}_w")
    h = d.slider("Înălțime", 10, height // 2, box[3] - box[1], key=f"{key}_h")
    return (x - w // 2, y - h // 2, x + w - w // 2, y + h - h // 2)


def character_section(p: Project) -> talking.Profile | None:
    st.subheader("1. Personajul")
    st.caption("Un personaj se pregătește o singură dată: imaginea lui (PNG cu fundal transparent), unde are gura și ochii "
               "și, opțional, variantele cu gura în alte poziții. Apoi îl alegi în orice proiect nou.")
    names = talking.list_profiles()
    with st.expander("➕ Creează un personaj nou", expanded=not names):
        name = st.text_input("Numele personajului", placeholder="Ex.: Steluța Muzicală", key="new_character_name")
        upload = st.file_uploader("Imaginea principală (PNG cu fundal transparent, gura ușor deschisă)", type=IMAGE_TYPES,
                                  key="new_character_image")
        if st.button("Creează personajul", disabled=not (name.strip() and upload)):
            profile = talking.Profile(name=projects.safe_name(name.strip()))
            profile.image = talking.store(profile, upload.name, upload.getvalue())
            if face := talking.detect_face(Image.open(io.BytesIO(upload.getvalue()))):
                profile.mouth, profile.eyes = list(face.mouth), [list(e) for e in face.eyes]
            talking.save_profile(profile)
            p.talk.character = profile.name
            projects.save(p)
            st.rerun()
    if not names:
        st.info("Creează mai întâi personajul.")
        return None
    index = names.index(p.talk.character) if p.talk.character in names else 0
    p.talk.character = st.selectbox("Personajul folosit", names, index=index, key=f"character_{p.name}")
    profile = talking.load_profile(p.talk.character)
    folder = talking.profile_dir(profile.name)
    with Image.open(folder / profile.image) as source:
        picture = ImageOps.exif_transpose(source).convert("RGBA")
    variants = talking.variant_files(profile)

    left, right = st.columns([2, 3])
    left.image(marked(picture, profile.face), caption="Roșu: gura. Verde: ochii.")
    with right:
        if profile.face is None:
            st.warning("Nu am găsit singur gura și ochii. Pune-i la locul lor din „Corectează pozițiile”.")
        else:
            st.image(expressions(picture, profile.face, variants),
                     caption="Închisă · puțin deschisă · deschisă · larg deschisă · rotunjită · clipit")
        if st.button("🔍 Găsește din nou gura și ochii", key=f"detect_{profile.name}"):
            if face := talking.detect_face(picture):
                profile.mouth, profile.eyes = list(face.mouth), [list(e) for e in face.eyes]
                talking.save_profile(profile)
                st.rerun()
            st.warning("Nu le-am găsit. Pune-le la locul lor cu glisoarele.")
    with st.expander("✏️ Corectează pozițiile gurii și ochilor"):
        w, h = picture.size
        face = profile.face or talking.Face((int(w * .48), int(h * .55), int(w * .62), int(h * .66)),
                                            [(int(w * .3), int(h * .4), int(w * .46), int(h * .55)),
                                             (int(w * .6), int(h * .37), int(w * .76), int(h * .52))])
        boxes = [box_sliders(label, box, picture.size, f"{profile.name}_{n}")
                 for n, (label, box) in enumerate(zip(FEATURES, [face.mouth, *face.eyes[:2]]))]
        if [list(b) for b in boxes] != [profile.mouth, *profile.eyes]:
            profile.mouth, profile.eyes = list(boxes[0]), [list(b) for b in boxes[1:]]
            talking.save_profile(profile)
            st.rerun()
    with st.expander(f"🎭 Variante pentru cel mai bun rezultat (opțional) · {len(variants)} încărcate"):
        st.caption("Fă cu programul tău de imagini variante ale aceleiași imagini, cu același personaj în aceeași poziție, "
                   "doar cu gura (sau ochii) altfel. Aplicația ia din ele numai zona gurii sau a ochilor, o aliniază și o "
                   "îmbină peste imaginea principală. Pentru formele fără variantă, gura se face din imaginea principală.")
        columns = st.columns(3)
        for n, (shape, label) in enumerate(talking.SHAPES.items()):
            with columns[n % 3]:
                if shape in variants:
                    st.image(str(variants[shape]), caption=label, width=150)
                    if st.button("Scoate", key=f"drop_{profile.name}_{shape}"):
                        profile.variants.pop(shape)
                        talking.save_profile(profile)
                        st.rerun()
                upload = st.file_uploader(label, type=IMAGE_TYPES, key=f"variant_{profile.name}_{shape}")
                if upload and st.session_state.get(f"variant_done_{shape}") != upload.file_id:
                    st.session_state[f"variant_done_{shape}"] = upload.file_id
                    profile.variants[shape] = talking.store(profile, f"{shape} - {upload.name}", upload.getvalue())
                    talking.save_profile(profile)
                    st.rerun()
    return profile


def voice_section(p: Project) -> float | None:
    st.subheader("2. Vocea")
    upload = st.file_uploader("Vocea (MP3 sau WAV)", type=AUDIO_TYPES, key=f"voice_{p.name}")
    if upload and projects.safe_name(upload.name) != p.talk.voice:
        p.talk.voice = projects.store_file(p, upload.name, upload.getvalue())
        projects.save(p)
    if not p.talk.voice:
        st.info("Încarcă vocea. Aplicația recunoaște singură cuvintele (local, fără internet după prima descărcare a "
                "modelului) și mișcă gura pe silabele lor; muzica de fundal nu mișcă gura.")
        return None
    path = projects.media_dir(p) / p.talk.voice
    seconds = probe_duration(path)
    st.caption(f"🎤 {p.talk.voice} — {seconds:.1f} secunde")
    st.audio(str(path))
    return seconds


def decor_section(p: Project) -> None:
    st.subheader("3. Decorurile")
    uploads = st.file_uploader("Decoruri (PNG sau JPG, fără personaj)", type=IMAGE_TYPES, accept_multiple_files=True,
                               key=f"decor_{p.name}")
    for item in uploads or []:
        name = projects.safe_name(item.name)
        if name not in p.images:
            p.images.append(projects.store_file(p, item.name, item.getvalue()))
            p.talk.decors.append(name)
            projects.save(p)
    if not p.images:
        st.caption("Fără decor, personajul apare pe un cer de seară, în degrade.")
        return
    p.talk.decors = st.multiselect("Decorurile folosite, în ordinea în care apar", p.images,
                                   [d for d in p.talk.decors if d in p.images], key=f"decors_{p.name}",
                                   help="Vocea se împarte cam egal între decoruri; fiecare schimbare cade în pauza dintre "
                                        "cuvinte cea mai apropiată, cu o trecere lină. Decorul se poate tăia pe margini ca să "
                                        "umple ecranul vertical; personajul niciodată.")
    if p.talk.decors:
        columns = st.columns(min(5, len(p.talk.decors)))
        for n, name in enumerate(p.talk.decors):
            columns[n % len(columns)].image(str(projects.media_dir(p) / name), caption=f"{n + 1}. {name}", width="stretch")


def talk_settings_section(p: Project) -> None:
    st.subheader("4. Mișcarea")
    t = p.talk
    a, b, c = st.columns(3)
    t.mouth = a.slider("Cât de mult se deschide gura", 0.5, 1.5, float(t.mouth), 0.1, key=f"t_mouth_{p.name}")
    t.sway = b.slider("Legănarea personajului", 0.0, 2.0, float(t.sway), 0.1, key=f"t_sway_{p.name}",
                      help="0 = nemișcat, 1 = blând, 2 = mai vioi. Personajul nu iese niciodată din cadru.")
    t.blink = c.checkbox("Clipește", t.blink, key=f"t_blink_{p.name}")
    a, b, c = st.columns(3)
    t.blink_every = a.slider("Clipește cam o dată la (secunde)", 2.0, 10.0, float(t.blink_every), 0.5,
                             key=f"t_every_{p.name}", disabled=not t.blink)
    t.blink_speed = b.select_slider("Viteza clipitului", ["rapid", "normal", "lent"], t.blink_speed,
                                    key=f"t_speed_{p.name}", disabled=not t.blink)
    t.scene_seconds = c.slider("Cel mai scurt timp pe un decor (secunde)", 3.0, 30.0, float(t.scene_seconds), 1.0,
                               key=f"t_scene_{p.name}")


def talking_render_section(p: Project, profile: talking.Profile | None, seconds: float | None) -> None:
    st.subheader("5. Animația")
    ready = bool(profile and profile.face and seconds)
    if not ready:
        st.info("Alege personajul (cu gura și ochii găsiți) și încarcă vocea.")
    longest = max(0.0, (seconds or 5) - 5)
    p.talk.preview_start = st.slider("Previzualizarea începe la (secunde)", 0.0, max(longest, 0.1),
                                     min(float(p.talk.preview_start), longest), 0.5, key=f"t_start_{p.name}")
    a, b = st.columns(2)
    preview = a.button("👀 Previzualizare 5 secunde", width="stretch", disabled=not ready)
    full = b.button("✨ Generează animația", type="primary", width="stretch", disabled=not ready)
    if preview or full:
        projects.save(p)
        output = (projects.project_dir(p.name) / "previzualizare-personaj.mp4" if preview
                  else projects.unique_output(f"{p.name} - personaj vorbitor"))
        t = p.talk
        style = talking.Style(mouth=t.mouth, blink=t.blink, blink_every=t.blink_every, blink_speed=t.blink_speed,
                              sway=t.sway, scene_seconds=t.scene_seconds, crossfade=t.crossfade)
        bar = st.progress(0.0, "Încep…")
        try:
            info = talking.render(talking.profile_dir(profile.name) / profile.image, profile.face, projects.media_dir(p) / t.voice,
                           output, [projects.media_dir(p) / d for d in t.decors], talking.variant_files(profile),
                           t.preview_start if preview else 0.0, 5.0 if preview else None, style,
                           lambda fraction, message: bar.progress(min(max(fraction, 0.0), 1.0), message))
        except RenderError as error:
            bar.empty()
            st.error(str(error))
            return
        st.session_state.talk_result = str(output)
        used = len(info["backdrops"])
        if len(t.decors) > used and not preview:
            st.warning(f"Au încăput {used} din {len(t.decors)} decoruri: fiecare stă cel puțin {t.scene_seconds:.0f} secunde și "
                       "se schimbă doar într-o pauză a vorbirii. Pentru mai multe decoruri, micșorează „Cel mai scurt timp pe "
                       "un decor” la pasul 4.")
        elif len(t.decors) > 1 and not preview:
            changes = ", ".join(f"{s:.1f} s" for s in info["backdrops"][1:])
            st.caption(f"Decorurile se schimbă la: {changes}.")
    result = st.session_state.get("talk_result")
    if result and Path(result).exists():
        show_video(Path(result), "talk_download")


def talking_page(p: Project) -> None:
    profile = character_section(p)
    seconds = voice_section(p)
    decor_section(p)
    talk_settings_section(p)
    talking_render_section(p, profile, seconds)


ASPECTS = {"16:9": "16:9 – YouTube", "9:16": "9:16 – Shorts, Instagram, TikTok"}
NOBODY = "— nimeni —"


def anim_song_section(p: Project) -> float | None:
    st.subheader("1. Melodia și versurile")
    left, right = st.columns(2)
    with left:
        upload = st.file_uploader("Melodia (MP3 sau WAV)", type=AUDIO_TYPES, key=f"anim_audio_{p.name}")
        if upload and projects.safe_name(upload.name) != p.audio:
            p.audio = projects.store_file(p, upload.name, upload.getvalue())
            projects.save(p)
        if not p.audio:
            st.info("Încarcă melodia.")
            return None
        path = projects.media_dir(p) / p.audio
        seconds = probe_duration(path)
        st.caption(f"🎵 {p.audio} — {seconds:.1f} secunde")
        st.audio(str(path))
    with right:
        p.lyrics = st.text_area("Versurile, cu titluri ca [Strofa 1] și [Refren]", p.lyrics, height=220,
                                placeholder=LYRICS_EXAMPLE, key=f"lyrics_{p.name}",
                                help="Versurile aleg personajele și ce fac: „Iepurașul sare” face iepurașul să sară, "
                                     "„Fluturașii iar apar” aduce fluturii în cadru.")
    return seconds


def anim_sync_section(p: Project, total_seconds: float) -> bool:
    st.subheader("2. Sincronizarea cu vocea")
    auto_step(p, total_seconds)
    ready = timeline.in_order(p.timeline, total_seconds) and any(s.confidence is not None for s in p.timeline)
    if not ready:
        if p.timeline:
            st.warning("Rândurile nu sunt încă sincronizate cu vocea. Apasă „✨ Sincronizează automat”.")
        return False
    flagged = [i + 1 for i, s in enumerate(p.timeline) if unsure(s)]
    st.success(f"Versurile sunt sincronizate: {len(p.timeline)} rânduri." +
               (f" {len(flagged)} sunt nesigure (⚠️); le poți verifica mai jos." if flagged else ""))
    with st.expander("Ascultă și corectează timpii (opțional)"):
        st.caption("Apasă pe un rând: se aude bucata lui și îi poți muta începutul cu −/+. Animația folosește acești timpi.")
        key = f"player_{p.name}"
        SYNC_PLAYER(key=key, on_marks_change=lambda: take_marks(key), data={
            "audio": audio_url(projects.media_dir(p) / p.audio), "rev": st.session_state.setdefault("timeline_rev", 0),
            "total": total_seconds, "thumbs": {}, "images": [],
            "rows": [{"text": s.text, "section": s.section, "start": s.start, "image": s.image, "unsure": unsure(s),
                      "confidence": s.confidence} for s in p.timeline]})
    return True


def profile_settings(name: str) -> None:
    """What the animation needs to know about one saved character, prefilled and saved at once."""
    profile = talking.load_profile(name)
    st.markdown(f"**{name}**")
    a, b, c, d = st.columns([2, 1, 3, 2])
    kind = a.selectbox("Ce este", list(library.KINDS), list(library.KINDS).index(profile.kind)
                       if profile.kind in library.KINDS else 0, format_func=library.KINDS.get, key=f"kind_{name}")
    flying = b.checkbox("Zboară", profile.flying, key=f"fly_{name}")
    names = c.text_input("Cum îl numesc versurile (începuturi de cuvinte)", ", ".join(profile.names or actions.names_for(name)),
                         key=f"names_{name}", help="Ex.: iepuras, iepure. „iepuras” găsește și „iepurașul”, „iepurașii”.")
    size = d.slider("Mărimea", 0.5, 1.5, float(profile.size), 0.05, key=f"size_{name}")
    st.caption("Opțional, **cadre**: același personaj, aceeași imagine și mărime, doar în altă poză. Pe ritm, "
               "aplicația trece lin de la imaginea principală la cadru și înapoi, fără să deformeze nimic; un cadru "
               "puțin mutat se aliniază singur.")
    frames = st.columns(len(library.FRAMES))
    added = False
    for column, (frame, label) in zip(frames, library.FRAMES.items()):
        with column:
            if frame in profile.looks and (talking.profile_dir(name) / profile.looks[frame]).exists():
                st.image(str(talking.profile_dir(name) / profile.looks[frame]), caption=label, width=110)
                if st.button("Scoate", key=f"frame_drop_{name}_{frame}"):
                    profile.looks.pop(frame)
                    talking.save_profile(profile)
                    st.rerun()
            upload = st.file_uploader(label, type=IMAGE_TYPES, key=f"frame_{name}_{frame}")
            if upload and st.session_state.get(f"frame_done_{name}_{frame}") != upload.file_id:
                st.session_state[f"frame_done_{name}_{frame}"] = upload.file_id
                profile.looks[frame] = talking.store(profile, f"{frame} - {upload.name}", upload.getvalue())
                added = True
    stems = [w.strip() for w in names.split(",") if w.strip()]
    if (kind, flying, stems, size) != (profile.kind, profile.flying, profile.names, profile.size) or added:
        profile.kind, profile.flying, profile.names, profile.size = kind, flying, stems, size
        talking.save_profile(profile)


def rig_stamp(points: dict) -> str:
    return hashlib.sha1(json.dumps(points, sort_keys=True).encode()).hexdigest()[:12]


def take_rig(key: str, name: str) -> None:
    """The points from the skeleton editor; ignored if the skeleton changed meanwhile (a new proposal)."""
    marks = (st.session_state.get(key) or {}).get("points") or {}
    profile = talking.load_profile(name)
    if marks.get("rev") == rig_stamp(profile.rig) and set(marks.get("points") or {}) == set(profile.rig):
        profile.rig = {k: [round(float(v[0]), 4), round(float(v[1]), 4)] for k, v in marks["points"].items()}
        talking.save_profile(profile)


@st.cache_data(show_spinner=False, max_entries=20)
def pose_picture(name: str, changed: float) -> bytes:
    buffer = io.BytesIO()
    director.pose_sheet(name).save(buffer, "JPEG", quality=88)
    return buffer.getvalue()


def skeleton_section(characters: list[str]) -> None:
    """Arms and legs that bend: the joints proposed from the picture, corrected by dragging them, seen at once."""
    with st.expander("🦴 Scheletul personajelor: brațe și picioare care se mișcă (o singură dată)"):
        if not rig.available():
            st.warning("Placa video nu poate desena scheletul (trebuie OpenGL 3.3), așa că personajele se mișcă întregi.")
            return
        st.caption("Pentru personaje desenate din față, în picioare. Un copil (tipul „Copil sau om”): cu brațele puțin "
                   "depărtate de corp și picioarele vizibile; pășește cu adevărat, bate din palme, dansează cu brațele, "
                   "salută cu mâna. Un animal (tipul „Animal”): capul se înclină, urechile și coada se mișcă, aripioarele "
                   "bat, tălpile pășesc; lăbuțele pictate pe burtică rămân pe loc. Fără schelet se mișcă întreg.")
        name = st.selectbox("Personajul", characters, key="rig_who")
        profile = talking.load_profile(name)
        path = talking.profile_dir(name) / profile.image
        propose, drop = st.columns(2)
        if propose.button("✨ Propune scheletul automat", width="stretch", key=f"rig_guess_{name}",
                          help="Din forma personajului: picioarele, unde se despart, mâinile. Corectezi apoi punctele."):
            propose_for = rig.guess_animal if profile.kind == "animal" else rig.guess
            with Image.open(path) as source:
                profile.rig = {k: list(v) for k, v in propose_for(ImageOps.exif_transpose(source).convert("RGBA")).items()}
            talking.save_profile(profile)
            st.rerun()
        if profile.rig and drop.button("Scoate scheletul (se mișcă întreg)", width="stretch", key=f"rig_drop_{name}"):
            profile.rig = {}
            talking.save_profile(profile)
            st.rerun()
        if not rig.usable(profile.rig):
            st.info("Alege întâi ce fel de personaj este (în „⚙️ Pregătește personajele”), apoi apasă „✨ Propune "
                    "scheletul automat”.")
            return
        with Image.open(path) as source:
            width, height = source.size
        key = f"rig_editor_{name}"
        editor, poses = st.columns([2, 3])
        with editor:
            RIG_EDITOR(key=key, on_points_change=lambda: take_rig(key, name), data={
                "image": thumbnail(str(path), path.stat().st_mtime, 520), "width": width, "height": height,
                "points": profile.rig, "labels": rig.labels(profile.rig),
                "bones": [[a, b] for _, a, b, _ in rig.skeleton(profile.rig)],
                "rev": rig_stamp(profile.rig)})
        with poses:
            st.image(pose_picture(name, library._changed(name)), width="stretch",
                     caption="Repaus · pas · palme · în aer · dans · salut. Dacă ceva se rupe sau trage după el "
                             "părul ori haina, mută puțin punctul de lângă.")
            st.caption("Umerii: unde începe brațul, sub mânecă. Șoldurile: unde ies picioarele de sub haină. "
                       "Mâinile și gleznele: la încheietură." if rig.is_human(profile.rig) else
                       "Urechile: de la bază la vârf. Coada: de la unde iese din corp la vârf. Gâtul: unde capul se "
                       "unește cu corpul. Dacă lipsește o parte pe care animalul o are, mută punctele sau propune din nou.")


def anim_library_section(p: Project) -> None:
    st.subheader("3. Personajele și decorurile")
    a = p.anim
    available = library.characters()
    left, right = st.columns(2)
    with left:
        chosen = [c for c in a.characters if c in available]
        if not chosen:
            chosen = [c for c in available if c not in library.BUILT_IN][:2] + ["Fluturaș galben"]
        a.characters = st.multiselect("Personajele din videoclip (primul e personajul principal)", available, chosen,
                                      key=f"anim_cast_{p.name}",
                                      help="Aplicația pune în fiecare scenă personajele despre care se cântă, pe cel care "
                                           "cântă și încă un prieten. Cele cu 🦋 sunt desenate de program.")
        talkers = [c for c in a.characters if c not in library.BUILT_IN and talking.load_profile(c).face]
        options = [NOBODY, *talkers]
        current = a.singer if a.singer in talkers else (talkers[0] if talkers else NOBODY)
        singer = st.selectbox("Cine cântă (îi mișcă gura după voce)", options, options.index(current),
                              key=f"anim_singer_{p.name}")
        a.singer = "" if singer == NOBODY else singer
        with st.expander("➕ Adaugă un personaj în bibliotecă"):
            name = st.text_input("Numele", placeholder="Ex.: Iepurașul", key="anim_new_name")
            upload = st.file_uploader("Imaginea (PNG cu fundal transparent, personajul întreg, din față)", type=IMAGE_TYPES,
                                      key="anim_new_image")
            if upload:
                _, transparent = library.picture_for_library(upload.getvalue())
                if not transparent:
                    st.warning("Imaginea nu are fundal transparent, așa că fundalul ei se va vedea în animație. Generează "
                               "personajul cu fundal transparent (decuparea automată poate fi adăugată mai târziu).")
            if st.button("Adaugă personajul", disabled=not (name.strip() and upload)):
                profile = library.create_character(name, upload.name, upload.getvalue())
                a.characters.append(profile.name)
                projects.save(p)
                st.rerun()
        mine = [c for c in a.characters if c not in library.BUILT_IN]
        if mine:
            with st.expander("⚙️ Pregătește personajele pentru animație (o singură dată)"):
                st.caption("Gura și ochii se găsesc și se corectează în modul „🌟 Personaj vorbitor”. Aici spui ce fel de "
                           "personaj este și cum îl numesc versurile.")
                for name in mine:
                    profile_settings(name)
            skeleton_section(mine)
    with right:
        decors = library.decors()
        chosen = [d for d in a.decors if d in decors] or decors[:1]
        a.decors = st.multiselect("Decorurile din care alege aplicația", decors, chosen, key=f"anim_decors_{p.name}",
                                  help="Fiecare strofă primește decorul potrivit versurilor ei (zi sau noapte, grădină…), "
                                       "iar refrenele îl păstrează pe al lor. Cele cu 🎨 sunt desenate de program.")
        uploads = st.file_uploader("Adaugă decoruri în bibliotecă (fără personaje în ele)", type=IMAGE_TYPES,
                                   accept_multiple_files=True, key=f"anim_decor_upload_{p.name}")
        for item in uploads or []:
            if st.session_state.get(f"decor_done_{item.file_id}"):
                continue
            st.session_state[f"decor_done_{item.file_id}"] = True
            with st.spinner(f"Mă uit la {item.name}…"):
                added = library.add_decor(item.name, item.getvalue())
            a.decors.append(added.name)
            projects.save(p)
            st.rerun()
        shown = [d for d in a.decors if library.decor(d).file]
        if shown:
            columns = st.columns(min(4, len(shown)))
            for n, name in enumerate(shown):
                item = library.decor(name)
                marks = ("🌙" if item.night else "☀️") + ("" if item.zone else " ⚠️ fără zonă") + \
                        (" ⚠️ mic" if library.picture_size(name)[0] < 1280 else "")
                columns[n % len(columns)].image(str(library.DECORS / item.file), width="stretch",
                                                caption=f"{marks} {name}")
    decor_zone_editor(p)


def decor_zone_editor(p: Project) -> None:
    """Where characters may stand in each decor: set once, seen at once, kept for every project."""
    own = [d for d in library.decors() if library.decor(d).file]
    if not own:
        return
    with st.expander("📐 Unde stau personajele în decor (o singură dată pe decor)"):
        st.caption("Albastru: locul unde pot sta picioarele personajelor. Roșu: obiectele pe care nu au voie să calce și în "
                   "spatele cărora nu au voie să stea (mingea, tufele, florile din față); în fața lor pot sta. Numerele "
                   "de pe margini sunt procente din imagine. Personajele arată unde le-ar pune o scenă. Un decor fără "
                   "zonă păstrează linia fixă de până acum.")
        chosen = [d for d in p.anim.decors if d in own]
        name = st.selectbox("Decorul", own, own.index(chosen[0]) if chosen else 0, key="zone_decor")
        item = library.decor(name)
        width, height = library.picture_size(name)
        if width < 1280:
            st.warning(f"Imaginea are doar {width}×{height} px, așa că la 1080p va fi neclară. Pentru calitate, folosește "
                       "un decor de cel puțin 1920×1080.")
        analyse, analyse_all = st.columns(2)
        unseen = [d for d in own if not library.decor(d).depth]
        todo = [name] if analyse.button("🔍 Analizează decorul automat", width="stretch", key=f"zone_auto_{name}",
                                        help="Un model local găsește solul, perspectiva și obiectele (o dată, cam o "
                                             "secundă). Zona de acum e înlocuită cu propunerea lui, pe care o poți "
                                             "corecta. Prima dată descarcă modelul (~95 MB).") else []
        if unseen and analyse_all.button(f"🔍 Analizează toate decorurile neanalizate ({len(unseen)})", width="stretch",
                                         key="zone_auto_all"):
            todo = unseen
        if todo:
            with st.spinner("Mă uit la decor: ce e aproape și ce e departe…"):
                for one in todo:
                    library.analyse_decor(one)
                    for suffix in ("x", "y", "far", "objects"):  # the sliders show the proposal
                        st.session_state.pop(f"zone_{one}_{suffix}", None)
            st.rerun()
        if item.depth:
            st.caption("✅ Decor analizat: personajele pot sta și în spatele obiectelor din față (florile, pietrele se "
                       "desenează peste ele), cât timp li se ascund doar picioarele.")
        zone = item.zone or (0.05, 0.62, 0.95, 0.97)
        key = f"zone_{name}"
        left, right = st.columns(2)
        across = left.slider("Zona: de la stânga la dreapta (%)", 0, 100, (round(zone[0] * 100), round(zone[2] * 100)),
                             key=f"{key}_x")
        depth = right.slider("Zona: de unde începe solul (sus) până jos (%)", 0, 100,
                             (round(zone[1] * 100), round(zone[3] * 100)), key=f"{key}_y")
        far_size = st.slider("Perspectiva: cât de mari sunt personajele în spatele zonei, față de cele din față (%)", 40,
                             100, round(item.far_size * 100), key=f"{key}_far",
                             help="100%: toți la fel de mari. Mai puțin: cine stă mai în spate e mai mic, ca în realitate.")
        st.markdown("**Obiectele din decor** (câte un rând pe obiect; numărul rândului apare pe imagine)")
        table = st.data_editor([{"Stânga %": round(o[0] * 100), "Sus %": round(o[1] * 100), "Dreapta %": round(o[2] * 100),
                                 "Jos %": round(o[3] * 100)} for o in item.obstacles] or
                               [{"Stânga %": None, "Sus %": None, "Dreapta %": None, "Jos %": None}],
                               num_rows="dynamic", width="stretch", key=f"{key}_objects",
                               column_config={c: st.column_config.NumberColumn(c, min_value=0, max_value=100, step=1)
                                              for c in ("Stânga %", "Sus %", "Dreapta %", "Jos %")})
        rows = table.to_dict("records") if hasattr(table, "to_dict") else table
        obstacles = [(r["Stânga %"] / 100, r["Sus %"] / 100, r["Dreapta %"] / 100, r["Jos %"] / 100) for r in rows
                     if all(isinstance(r.get(c), (int, float)) and r.get(c) == r.get(c)
                            for c in ("Stânga %", "Sus %", "Dreapta %", "Jos %"))
                     and r["Stânga %"] < r["Dreapta %"] and r["Sus %"] < r["Jos %"]]
        new_zone = (across[0] / 100, depth[0] / 100, across[1] / 100, depth[1] / 100)
        available = library.characters()
        cast = [c for c in p.anim.characters if c in available] or available[:1]
        wide, tall = st.columns([3, 1])
        wide.image(director.zone_preview(name, (960, 540), cast, new_zone, far_size / 100, obstacles), width="stretch",
                   caption="16:9 (YouTube)")
        tall.image(director.zone_preview(name, (304, 540), cast, new_zone, far_size / 100, obstacles), width="stretch",
                   caption="9:16 (Shorts)")
        save, reset = st.columns(2)
        if save.button("💾 Salvează zona decorului", type="primary", width="stretch", key=f"{key}_save"):
            library.save_zone(name, new_zone, far_size / 100, obstacles)
            st.success("Salvat. Scenele cu acest decor se vor desena din nou cu noua zonă.")
        if item.zone and reset.button("Șterge zona (înapoi la linia fixă)", width="stretch", key=f"{key}_reset"):
            library.save_zone(name, None)
            st.rerun()


@st.cache_data(show_spinner=False, max_entries=300)
def anim_thumbnail(scene: str, settings: str, stamps: str) -> bytes:
    picture = director.thumbnail(AnimScene.model_validate_json(scene), AnimationSettings.model_validate_json(settings))
    buffer = io.BytesIO()
    picture.save(buffer, "JPEG", quality=85)
    return buffer.getvalue()


def scene_title(n: int, scene: AnimScene) -> str:
    words = scene.lines[0] if scene.lines else "🎵 muzică"
    return f"{n + 1}. {planner.stamp(round(scene.start * FPS))}–{planner.stamp(round(scene.end * FPS))} · {words}"


def anim_logo(p: Project) -> tuple[LogoSettings | None, Path | None]:
    if p.logo.file and p.logo.enabled:
        return p.logo, projects.media_dir(p) / p.logo.file
    return None, None


def run_with_progress(job) -> bool:
    bar = st.progress(0.0, "Încep…")
    try:
        job(lambda fraction, message: bar.progress(min(max(fraction, 0.0), 1.0), message))
    except RenderError as error:
        bar.empty()
        st.error(str(error))
        return False
    bar.empty()
    return True


def preview_selected(p: Project, index: int) -> None:
    output = projects.project_dir(p.name) / "previzualizare-scena.mp4"
    logo, logo_file = anim_logo(p)
    if run_with_progress(lambda progress: director.preview_scene(p.anim.scenes, index, p.anim, projects.media_dir(p) / p.audio,
                                                                 output, logo, logo_file, progress)):
        st.session_state.anim_scene_preview = (str(output), index)


def scene_editor(p: Project, total_seconds: float) -> None:
    a = p.anim
    titles = [scene_title(n, s) for n, s in enumerate(a.scenes)]
    index = st.selectbox("Scena pe care vrei s-o schimbi", range(len(a.scenes)), format_func=titles.__getitem__,
                         key=f"anim_pick_{p.name}")
    scene = a.scenes[index]
    picture, info = st.columns([2, 3])
    stamps = repr(director.changed_files(a, scene))
    picture.image(anim_thumbnail(scene.model_dump_json(), a.model_dump_json(exclude={"scenes"}), stamps), width="stretch")
    with info:
        st.caption(f"**{scene.section or 'Muzică'}** · decor: {scene.decor} · efecte: "
                   + (", ".join(director.EFFECT_NAMES.get(e, e) for e in scene.effects) or "fără"))
        if scene.lines:
            st.caption(" / ".join(scene.lines))
        st.caption(director.describe(scene))
    changed = False
    b1, b2, b3 = st.columns(3)
    if b1.button("🔄 Regenerează scena", width="stretch", help="Alte alegeri pentru aceleași versuri: alți prieteni, alte "
                                                               "mișcări, altă cameră. Timpii și restul videoclipului rămân."):
        a.scenes[index] = director.regenerate(p.timeline, total_seconds, a, index)
        changed = True
    if b2.button("🎲 Surprinde-mă", width="stretch", help="Aceleași personaje și aceleași acțiuni, în alt aranjament: "
                                                          "alte locuri, alt decor desenat, alte efecte. Sincronizarea rămâne."):
        scene.look += 1
        scene.edited = changed = True
    if b3.button("👀 Previzualizează scena", width="stretch"):
        preview_selected(p, index)

    cast = [r.character for r in scene.roles]
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**🎭 Schimbă personajul**")
        who = st.selectbox("Pe cine", cast, key=f"swap_who_{p.name}_{index}") if cast else None
        others = [c for c in a.characters if c not in cast]
        new = st.selectbox("Cu cine", others, key=f"swap_new_{p.name}_{index}") if others else None
        if st.button("Schimbă", key=f"swap_{p.name}_{index}", disabled=not (who and new)):
            director.swap_character(scene, who, new)
            changed = True
    with c2:
        st.markdown("**🎬 Schimbă animația**")
        who2 = st.selectbox("Cine", cast, key=f"act_who_{p.name}_{index}") if cast else None
        labels = {"": "✨ Automat, după versuri", **director.ACTION_NAMES}
        action = st.selectbox("Ce face toată scena", list(labels), format_func=labels.get, key=f"act_{p.name}_{index}")
        if st.button("Aplică", key=f"act_go_{p.name}_{index}", disabled=not who2):
            director.set_action(scene, who2, action)
            changed = True
    with c3:
        st.markdown("**🏞️ Schimbă decorul**")
        pool = list(dict.fromkeys([*a.decors, *library.decors()]))
        decor = st.selectbox("Decorul", pool, pool.index(scene.decor) if scene.decor in pool else 0,
                             key=f"decor_{p.name}_{index}")
        if st.button("Schimbă decorul", key=f"decor_go_{p.name}_{index}", disabled=decor == scene.decor):
            scene.decor, scene.edited, changed = decor, True, True

    with st.expander("⚙️ Mod avansat"):
        advanced_editor(p, scene, index)

    if changed:
        projects.save(p)
        preview_selected(p, index)
        st.rerun()
    shown = st.session_state.get("anim_scene_preview")
    if shown and shown[1] == index and Path(shown[0]).exists():
        st.video(shown[0])


def advanced_editor(p: Project, scene: AnimScene, index: int) -> None:
    a = p.anim
    a.energy = st.slider("Cât de ample sunt mișcările (tot videoclipul)", 0.5, 1.5, float(a.energy), 0.1,
                         key=f"anim_energy_{p.name}", help="Pentru bebeluși, 1 sau mai puțin.")
    cameras = {"apropiere": "Apropiere lentă", "departare": "Depărtare lentă", "fix": "Fixă",
               "prim-plan": "Prim-plan lent (pe primul personaj)", "aproape": "Cadru apropiat (pe fețe)",
               "panoramare": "Panoramare lentă (stânga → dreapta)"}
    left, right = st.columns(2)
    camera = left.selectbox("Camera în această scenă", list(cameras), list(cameras).index(scene.camera),
                            format_func=cameras.get, key=f"cam_{p.name}_{index}")
    effects_chosen = right.multiselect("Efectele din decor", list(director.EFFECT_NAMES), scene.effects,
                                       format_func=director.EFFECT_NAMES.get, max_selections=director.MAX_EFFECTS,
                                       key=f"fx_{p.name}_{index}")
    title = st.text_input("Text pe ecran în această scenă (opțional)", scene.title, key=f"title_{p.name}_{index}",
                          placeholder="Ex.: Are mama o fetiță",
                          help="Apare lin, sus la mijloc, după prima secundă a scenei, și rămâne până la final.")
    if camera != scene.camera or effects_chosen != scene.effects or title.strip() != scene.title:
        scene.camera, scene.effects, scene.title, scene.edited = camera, effects_chosen, title.strip(), True
        projects.save(p)
    st.markdown("**Personajele din scenă**")
    for role in list(scene.roles):
        cols = st.columns([3, 3, 3, 1])
        cols[0].write(role.character)
        partners = [r.character for r in scene.roles if r.character != role.character]
        kind = cols[1].selectbox("Interacțiune", list(director.INTERACTION_NAMES), list(director.INTERACTION_NAMES).index(role.interaction),
                                 format_func=director.INTERACTION_NAMES.get, key=f"int_{p.name}_{index}_{role.character}",
                                 label_visibility="collapsed")
        partner = cols[2].selectbox("Cu cine", partners or [""], partners.index(role.partner) if role.partner in partners else 0,
                                    key=f"par_{p.name}_{index}_{role.character}", label_visibility="collapsed",
                                    disabled=not kind or not partners)
        if (kind, partner if kind else "") != (role.interaction, role.partner):
            role.interaction, role.partner = (kind, partner) if kind and partner else ("", "")
            role.at = scene.start + 1.0 if role.interaction else None
            scene.edited = True
            projects.save(p)
        if cols[3].button("✖", key=f"rm_{p.name}_{index}_{role.character}", help="Scoate personajul din scenă"):
            director.remove_character(scene, role.character)
            projects.save(p)
            st.rerun()
        role_place(p, scene, index, role)
    missing = [c for c in dict.fromkeys([*a.characters, *library.characters()])
               if c not in [r.character for r in scene.roles]]  # any character of the library, by hand
    if missing:
        cols = st.columns([3, 1])
        extra = cols[0].selectbox("Adaugă în scenă", missing, key=f"add_{p.name}_{index}")
        if cols[1].button("Adaugă", key=f"add_go_{p.name}_{index}"):
            director.add_character(scene, extra)
            projects.save(p)
            st.rerun()
    st.markdown("**Șabloane de scene**")
    cols = st.columns(2)
    with cols[0]:
        name = st.text_input("Numele șablonului", placeholder="Ex.: Grădina cu fluturi", key=f"tpl_name_{p.name}")
        if st.button("💾 Salvează scena ca șablon", disabled=not name.strip()):
            library.save_template(name, scene)
            st.success("Șablonul e salvat și poate fi folosit în orice proiect.")
    with cols[1]:
        saved = library.templates()
        chosen = st.selectbox("Șablon salvat", saved, key=f"tpl_pick_{p.name}") if saved else None
        if st.button("📋 Aplică șablonul pe această scenă", disabled=not chosen):
            director.apply_template(scene, library.load_template(chosen))
            projects.save(p)
            st.rerun()


def role_place(p: Project, scene: AnimScene, index: int, role) -> None:
    """Where one character stands in this scene and how big it is, chosen by hand."""
    key = f"{p.name}_{index}_{role.character}"
    flying = library.character(role.character).flying
    cols = st.columns([2, 3, 3, 3])
    by_hand = cols[0].checkbox("Loc ales de mine", role.place is not None, key=f"own_{key}", disabled=flying,
                               help="Bifat: stă exact unde alegi, pe podea. Nebifat: aplicația îl așază singură, lângă "
                                    "ceilalți, ferit de mobilă.")
    across = cols[1].slider("Stânga ↔ dreapta", 0.0, 1.0, float(role.place[0]) if role.place else 0.5, 0.01,
                            key=f"across_{key}", disabled=not by_hand or flying, help="În zona sigură a decorului.")
    depth = cols[2].slider("În față ↔ în spate", 0.0, 1.0, float(role.place[1]) if role.place else 0.0, 0.01,
                           key=f"depth_{key}", disabled=not by_hand or flying, help="În spate pare mai mic, ca în realitate.")
    size = cols[3].slider("Mărime", 0.3, 2.0, float(role.size), 0.05, key=f"size_{key}")
    place = (across, depth) if by_hand and not flying else None
    if place != (tuple(role.place) if role.place else None) or size != role.size:
        role.place, role.size, scene.edited = place, size, True
        projects.save(p)


def anim_render_section(p: Project, total_seconds: float) -> None:
    st.subheader("5. Animația")
    a = p.anim
    a.aspect = st.radio("Formatul", list(ASPECTS), list(ASPECTS).index(a.aspect), format_func=ASPECTS.get,
                        horizontal=True, key=f"anim_aspect_{p.name}")
    a.style = st.radio("Mișcarea personajelor", list(STYLES), list(STYLES).index(a.style), format_func=STYLES.get,
                       key=f"anim_style_{p.name}",
                       help="Fără deformare: fiecare personaj rămâne exact ca în imaginea lui; se leagănă ușor, cu "
                            "picioarele pe podea, apare lin, iar palmele, săriturile și salutul vin din cadrele încărcate "
                            "la pasul 3. Fără cadre, gestul devine o legănare sau o înclinare veselă.")
    ready = bool(a.characters)
    if not ready:
        st.info("Alege cel puțin un personaj la pasul 3.")
    keep = any(s.edited for s in a.scenes) and st.checkbox("Păstrează scenele pe care le-am schimbat eu", True,
                                                         key=f"anim_keep_{p.name}")
    logo, logo_file = anim_logo(p)
    if st.button("✨ Generează animația automat", type="primary", width="stretch", disabled=not ready):
        a.scenes = director.plan(p.timeline, total_seconds, a, a.scenes if keep else None)
        projects.save(p)
        output = projects.project_dir(p.name) / "previzualizare-animatie.mp4"
        if run_with_progress(lambda progress: director.export(a.scenes, a, projects.media_dir(p) / p.audio, output, True,
                                                              logo, logo_file, p.fade_out, progress)):
            st.session_state.anim_result = str(output)
        st.rerun()
    if not a.scenes:
        st.caption("Aplicația împarte cântecul în scene, alege decorul, personajele și mișcările după versuri și face o "
                   "previzualizare la rezoluție mică. Apoi schimbi doar scenele care nu îți plac și exporți la 1080p.")
        return
    if any(abs(s.end - s.start) < 0.1 for s in a.scenes) or a.scenes[-1].end < total_seconds - 0.5:
        st.warning("Scenele nu mai corespund melodiei. Apasă din nou „✨ Generează animația automat”.")
    st.markdown(f"**{len(a.scenes)} scene** · {sum(s.edited for s in a.scenes)} schimbate de tine")
    settings_json = a.model_dump_json(exclude={"scenes"})
    columns = st.columns(4 if a.aspect == "16:9" else 6)
    for n, scene in enumerate(a.scenes):
        with columns[n % len(columns)]:
            st.image(anim_thumbnail(scene.model_dump_json(), settings_json, repr(director.changed_files(a, scene))),
                     width="stretch")
            st.caption(("✏️ " if scene.edited else "") + scene_title(n, scene))
    st.divider()
    scene_editor(p, total_seconds)
    st.divider()
    p.fade_out = st.checkbox("Estompează imaginea și sunetul la final", p.fade_out, key=f"anim_fade_{p.name}")
    left, right = st.columns(2)
    preview = left.button("👀 Previzualizare rapidă (toată melodia, rezoluție mică)", width="stretch")
    full = right.button("⬇️ Exportă MP4 la 1080p", type="primary", width="stretch")
    if preview or full:
        projects.save(p)
        output = (projects.project_dir(p.name) / "previzualizare-animatie.mp4" if preview
                  else projects.unique_output(f"{p.name} - animatie {a.aspect.replace(':', 'x')}"))
        if run_with_progress(lambda progress: director.export(a.scenes, a, projects.media_dir(p) / p.audio, output, preview,
                                                              logo, logo_file, p.fade_out, progress)):
            st.session_state.anim_result = str(output)
    result = st.session_state.get("anim_result")
    if result and Path(result).exists():
        show_video(Path(result), "anim_download")
        st.caption("Scenele deja desenate se păstrează: după o schimbare, doar scena schimbată (și tranzițiile ei) se "
                   "desenează din nou.")


def animation_page(p: Project) -> None:
    total = anim_song_section(p)
    if total is None:
        return
    synced = anim_sync_section(p, total)
    anim_library_section(p)
    logo_section(p)
    if synced:
        anim_render_section(p, total)
    else:
        st.subheader("5. Animația")
        st.info("Sincronizează întâi versurile cu vocea (pasul 2).")


sidebar()
try:
    tools = find_tool("ffmpeg"), find_tool("ffprobe")
except MissingToolError as error:
    st.error(str(error))
    st.stop()

project = st.session_state.get("project")
if project is None:
    st.title("🌙 Baby Video Studio")
    st.write("Creează cântece de leagăn animate din melodia și imaginile tale.")
    st.info("👈 Pentru a începe, creează un proiect nou sau deschide unul salvat din meniul din stânga.")
    st.stop()

st.title(project.name)
project.kind = st.radio("Ce fel de videoclip faci?", list(KINDS), list(KINDS).index(project.kind), format_func=KINDS.get,
                        horizontal=True, key=f"kind_{project.name}")
try:
    if project.kind == "talking":
        talking_page(project)
    elif project.kind == "animation":
        animation_page(project)
    else:
        media_section(project)
        story_section(project)
        settings_section(project)
        logo_section(project)
        if (scenes := scenes_section(project)) is not None:
            render_section(project, scenes)
        subtitles_section(project)
    projects.save(project)
except RenderError as error:
    st.error(str(error))
