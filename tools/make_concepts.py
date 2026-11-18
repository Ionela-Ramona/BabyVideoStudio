"""Rebuild baby_video_studio/concepts.npz after changing pictures.CONCEPTS (developer tool, run once).

Embeds every concept with SigLIP 2's text model (1.1 GB, not needed by the app itself) and measures how strongly
the reference pictures match each concept, so pictures.seen() can tell a clear match from an absent one.
Use varied children's-book pictures: a concept missing from all of them cannot be calibrated.

    .venv\Scripts\python.exe tools\make_concepts.py <folder with reference pictures>
"""
import sys
from pathlib import Path

import numpy as np
import onnxruntime
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from baby_video_studio import pictures  # noqa: E402

LENGTH = 64  # SigLIP 2 was trained on lowercase text padded to 64 tokens

tokenizer = Tokenizer.from_file(hf_hub_download(pictures.REPO, "tokenizer.json"))
text_model = onnxruntime.InferenceSession(hf_hub_download(pictures.REPO, "onnx/text_model.onnx"), providers=["CPUExecutionProvider"])
ids = [tokenizer.encode(f"a picture of {prompt}.".lower()).ids[:LENGTH] for _, prompt, _ in pictures.CONCEPTS]
ids = np.array([i + [0] * (LENGTH - len(i)) for i in ids], np.int64)
text = text_model.run(["pooler_output"], {"input_ids": ids})[0]
text /= np.linalg.norm(text, axis=1, keepdims=True)

folder = Path(sys.argv[1])
paths = sorted(p for p in folder.rglob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
images = np.stack(list(pictures.vectors(paths, lambda f, m: print(m)).values()))
unique = np.unique(images.round(5), axis=0)
scores = text @ unique.T
# absent: what a picture without the concept typically scores; best: the clearest reference picture
np.savez(pictures.BANK, text=text.astype(np.float32), absent=np.percentile(scores, 25, axis=1).astype(np.float32),
         best=scores.max(1).astype(np.float32), pictures=np.array(len(unique)))
print(f"{len(pictures.CONCEPTS)} concepts, {len(unique)} reference pictures -> {pictures.BANK}")
