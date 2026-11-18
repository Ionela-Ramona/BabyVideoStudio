"""What each picture shows, so the storyboard can pick pictures that match what is sung.

A small local vision model (SigLIP 2, Google, free; ONNX on the CPU, ~370 MB, downloaded once) compares each
picture with a fixed list of things children's songs talk about. Only the picture side runs on the user's
computer: the descriptions of the concepts were computed once and ship with the app (concepts.npz).
Without the model, the words in the file names and in the user's descriptions are used instead.
"""
import hashlib
import importlib.util
from pathlib import Path
from typing import Callable

import numpy as np

from .planner import _is, _tokens
from .render import CACHE_DIR

REPO, FILE = "onnx-community/siglip2-base-patch16-224-ONNX", "onnx/vision_model.onnx"
SIZE = 224
CACHE = CACHE_DIR / "imagini"
BANK = Path(__file__).with_name("concepts.npz")  # concept vectors and how strongly reference pictures match them
SPREAD = 5 / 112.67  # at least this far above "absent" (5 logits of SigLIP 2) before a concept counts as fully visible
VISIBLE = 0.5  # from here a concept is named in the picture's description

# label (Romanian, shown to the user), what the model is asked (English), word stems in lyrics, file names and descriptions
CONCEPTS: list[tuple[str, str, tuple[str, ...]]] = [
    ("iepuraș", "a bunny", ("iepur", "bunny", "rabbit")),
    ("puișor", "a baby chick", ("pui", "puis", "puisor", "puiu", "gaina", "chick")),
    ("miel", "a lamb", ("miel", "mielu", "oaie", "oita", "oite", "lamb", "sheep")),
    ("ursuleț", "a teddy bear", ("urs", "ursul", "ursulet", "bear", "teddy")),
    ("mama", "a mother hugging her baby", ("mama", "mami", "mamei", "mother", "mom", "mommy")),
    ("bebeluș", "a baby", ("bebe", "bebel", "baby", "prunc")),
    ("fetiță", "a little girl", ("fetit", "copila", "girl")),
    ("băiețel", "a little boy", ("baiat", "baiet", "boy")),
    ("pisicuță", "a kitten", ("pisic", "kitten", "cat")),
    ("cățeluș", "a puppy", ("catel", "caine", "puppy", "dog")),
    ("rățușcă", "a duckling", ("rata", "ratus", "duck")),
    ("fluturi", "butterflies", ("flutur", "butterf")),
    ("buburuză", "a ladybug", ("buburuz", "ladybug")),
    ("albinuță", "a bee", ("albin", "bee")),
    ("păsărele", "a little bird", ("pasar", "pasare", "bird")),
    ("arici", "a hedgehog", ("arici", "hedgehog")),
    ("veveriță", "a squirrel", ("veverit", "squirrel")),
    ("broscuță", "a frog", ("brosc", "frog")),
    ("peștișor", "a fish", ("pesti", "pestis", "fish")),  # not "peste": it also means "over"
    ("morcov", "a carrot", ("morcov", "carrot")),
    ("flori", "flowers", ("floare", "flori", "floric", "flower")),
    ("gard", "a wooden fence", ("gard", "gardul", "fence")),
    ("căsuță", "a little cottage", ("casa", "casut", "cottage", "house")),
    ("cuib", "a bird nest", ("cuib", "nest")),
    ("pătuț", "a cozy bed", ("pat", "patut", "bed", "pillow", "perna")),
    ("jucării", "toys", ("jucari", "toy", "toys")),
    ("minge", "a ball", ("minge", "mingi", "ball")),
    ("copac", "a big tree", ("copac", "copaci", "tree")),
    ("lună", "the moon", ("luna", "lunii", "moon", "moonlit")),
    ("stele", "stars in the sky", ("stea", "stele", "stelut", "star", "stars", "starry")),
    ("soare", "the sun", ("soare", "soarel", "sun", "sunny", "sunlit", "sunshine")),
    ("nori", "fluffy clouds", ("nor", "nori", "norul", "norii", "noris", "norul", "cloud")),
    ("curcubeu", "a rainbow", ("curcubeu", "rainbow")),
    ("ploaie", "rain", ("ploai", "ploua", "rain")),
    ("zăpadă", "snow", ("zapad", "ninge", "fulg", "snow")),
    ("lac", "a pond", ("lac", "lacul", "balta", "pond", "lake")),
    ("grădină", "a garden", ("gradin", "garden")),
    ("pajiște", "a green meadow", ("pajist", "iarba", "camp", "meadow", "field")),
    ("pădure", "a forest", ("padur", "forest")),
    ("cameră", "a bedroom", ("camer", "dormitor", "bedroom")),
    ("noapte", "a night sky", ("noapt", "seara", "noaptea", "night", "bedtime", "goodnight")),
    ("apus", "a sunset", ("apus", "asfint", "coboar", "sunset")),
    ("răsărit", "a sunrise", ("rasar", "dimineat", "zori", "sunrise", "morning")),
    ("somn", "a sleeping animal", ("doarm", "dorm", "somn", "adorm", "nani", "odihn", "obosit", "sleep", "slumber", "nap")),
    ("mâncare", "an animal eating", ("manan", "mananc", "mancat", "manca", "ront", "papa", "eat", "eating")),
    ("sărituri", "a jumping bunny", ("sar", "sare", "sarim", "sarit", "topa", "topai", "tup", "hop", "jump")),
    ("joacă", "animals playing together", ("joac", "juca", "distrez", "play")),
    ("dans", "dancing", ("dans", "danc")),
    ("îmbrățișare", "a goodnight kiss and hug", ("pup", "pupic", "sarut", "imbratis", "kiss", "hug", "cuddle")),
    ("zbor", "flying", ("zbor", "zboar", "fly", "flying")),
]
LABELS = [label for label, _, _ in CONCEPTS]
Progress = Callable[[float, str], None]


def concepts_in(text: str) -> set[int]:
    """The concepts a text talks about, by word stems (Romanian inflections and English names both count)."""
    words = _tokens(text)
    return {k for k, (_, _, stems) in enumerate(CONCEPTS) if any(_is(w, s) for w in words for s in stems)}


def available() -> bool:
    return importlib.util.find_spec("onnxruntime") is not None and BANK.exists()


def _vector_file(path: Path) -> Path:
    return CACHE / f"{hashlib.sha1(path.read_bytes()).hexdigest()[:20]}.npy"


def _pixels(path: Path) -> np.ndarray:
    from PIL import Image, ImageOps
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB").resize((SIZE, SIZE), Image.BILINEAR)
    return ((np.asarray(image, np.float32) / 255 - 0.5) / 0.5).transpose(2, 0, 1)


def _session():
    import onnxruntime
    from huggingface_hub import hf_hub_download
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 4
    return onnxruntime.InferenceSession(hf_hub_download(REPO, FILE), options, providers=["CPUExecutionProvider"])


def vectors(paths: list[Path], progress: Progress) -> dict[Path, np.ndarray]:
    """One vector per picture; kept in the cache by file content, so a picture is analysed once for all projects."""
    result, todo = {}, []
    for path in paths:
        kept = _vector_file(path)
        if kept.exists():
            result[path] = np.load(kept)
        else:
            todo.append(path)
    if todo:
        progress(0.0, "Pregătesc modelul care „vede” imaginile. Prima dată se descarcă (~370 MB), apoi rămâne pe calculator.")
        session = _session()
        CACHE.mkdir(parents=True, exist_ok=True)
        for done, path in enumerate(todo, 1):
            vector = session.run(["pooler_output"], {"pixel_values": _pixels(path)[None]})[0][0]
            vector = vector / np.linalg.norm(vector)
            np.save(_vector_file(path), vector)
            result[path] = vector
            progress(done / len(todo), f"Mă uit la imagini: {done} din {len(todo)}")
    return result


def seen(vector: np.ndarray) -> list[float]:
    """0..1 per concept: 0 = like a picture without it, 1 = as clear as the best reference picture."""
    bank = np.load(BANK)
    scale = np.maximum(bank["best"] - bank["absent"], SPREAD)
    return [round(float(v), 2) for v in np.clip((bank["text"] @ vector - bank["absent"]) / scale, 0, 1)]


def from_words(image: str, tags: dict[str, str]) -> list[float]:
    """1 for what the file name or the user's description names, 0 otherwise."""
    named = concepts_in(f"{Path(image).stem} {tags.get(image, '')}")
    return [1.0 if k in named else 0.0 for k in range(len(CONCEPTS))]


def describe(found: dict[str, float], limit: int = 6) -> str:
    """The clearest concepts, in Romanian, for showing under the picture."""
    return ", ".join(sorted((c for c in found if found[c] >= VISIBLE), key=lambda c: -found[c])[:limit])


def evidence(files: dict[str, Path], tags: dict[str, str], progress: Progress) -> tuple[dict[str, dict[str, float]], str]:
    """What each picture shows, {image: {concept: 0..1}}, and a note for the user when the vision model could not run.

    The picture itself, its file name and the user's description all count; the clearest of them wins.
    """
    found = {name: from_words(name, tags) for name in files}
    note = ""
    if not available():
        note = "Modelul vizual nu este disponibil, așa că imaginile sunt alese după numele lor și descrierile tale."
    else:
        try:
            looked = vectors(list(files.values()), progress)
            for name, path in files.items():
                found[name] = [max(a, b) for a, b in zip(found[name], seen(looked[path]))]
        except Exception as error:  # no internet the first time, too little memory…: the words still work
            note = ("Nu am putut porni modelul care „vede” imaginile, așa că le-am ales după numele lor și descrierile tale. "
                    f"Prima dată e nevoie de internet. Detalii: {error}")
    return {name: {LABELS[k]: v for k, v in enumerate(values) if v >= 0.05} for name, values in found.items()}, note
