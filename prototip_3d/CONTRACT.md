# Prototip 3D – contract comun (coordonator)

Prototip separat. NU se modifică nimic în afara folderului `prototip_3d/` (app.py, baby_video_studio/ etc. rămân neatinse).

## Blender
- Versiune: **Blender 4.5.16 LTS portabil**, `D:\Tools\Blender\blender-4.5.16-windows-x64\blender.exe` (Python 3.11 intern).
- Rulare: `blender.exe -b --factory-startup --python <script.py> -- <argumente>`.
- Motor: EEVEE. ID motor în 4.5 = `'BLENDER_EEVEE_NEXT'` (în 5.x = `'BLENDER_EEVEE'`); folosiți
  `ENGINE = 'BLENDER_EEVEE_NEXT' if bpy.app.version < (5, 0, 0) else 'BLENDER_EEVEE'`.
- Rezoluție test: 960×540, 30 fps.
- Fără add-on-uri externe, fără descărcări de asset-uri. Totul se construiește din cod.

## Fișiere și proprietari (fiecare agent scrie DOAR fișierele lui)
| Fișier | Proprietar |
|---|---|
| `masoara.ps1`, `INFO_BLENDER.md` | Agent 1 – Blender |
| `personaje.py` | Agent 2 – Personaje |
| `ANIMATIE_PLAN.md` (acum doar plan, fără cod) | Agent 3 – Animații |
| `decor.py` | Agent 4 – Decor |
| `scena.py`, `CONTRACT.md` | Coordonator |
| `output/<agent>_*.png` | imagini de test ale fiecărui agent |

Modulele se importă din `scena.py` (care pune folderul în `sys.path`). Nu rulează nimic la import; doar funcții.

## Axe și unități
- Metri, Z în sus, podeaua la z = 0.
- Camera privește dinspre **−Y spre +Y**. „Fața” unui personaj, la rotație 0, este spre **−Y** (spre cameră).
- Acțiunea are loc pe axa X: mama stă la aproximativ x = +0.5, y = 0; fetița vine din stânga (x ≈ −2.2) spre mamă (x ≈ −0.1).
- Zona vizibilă necesară: x ∈ [−2.8, 1.6], y ∈ [−0.5, 1.0], înălțime 0..1.9 m.

## personaje.py (Agent 2)
```python
build_mama(name="Mama") -> dict
build_fetita(name="Fetita") -> dict
# dict: {"rig": Object(ARMATURE), "mouth": Object (shape key "zambet" 0..1),
#        "eyelids": [Object,...] (shape key "clipire" 0..1), "height": float}
```
- Originea rig-ului = între tălpi, pe podea. Așezate prin `rig.location` / `rig.rotation_euler.z`.
- Figurine stilizate (cap mare, ochi mari albaștri), **piese rigide** parentate pe oase (parent_type BONE), fără skinning → fără deformări. Articulații ascunse cu sfere/forme rotunjite.
- Nume oase obligatorii (deform/FK): `root`, `hips`, `spine`, `chest`, `neck`, `head`,
  `upper_arm.L/R`, `forearm.L/R`, `hand.L/R`, `thigh.L/R`, `shin.L/R`, `foot.L/R`, `eye.L/R`.
- Controale: `hand_ik.L/R` (IK pe forearm, chain 2, influență implicită 0), `foot_ik.L/R` (IK pe shin, chain 2, influență 1, tălpile stau pe podea), `privire` (țintă în fața feței; `eye.L/R` au Damped Track spre ea). Pole-uri dacă e nevoie, cu nume `*_pole.L/R`.
- `.L` = partea stângă a personajului (x pozitiv când personajul privește spre −Y).
- Dimensiuni: mama ≈ 1.65 m, fetița ≈ 0.95 m (toddler, cap mare).
- Aspect:
  - Mama: păr șaten închis lung, ochi albaștri, rochie roz.
  - Fetița: păr șaten, ochi albaștri, fundiță roz cu buline, rochiță roz cu floricele.

## decor.py (Agent 4)
```python
build_room() -> dict        # {"camera": Object, "lights": [...], "root": Collection}
setup_render(width=960, height=540, fps=30, samples=16) -> None
```
- Cameră de joacă pastelată, camera „Camera” setată ca scene.camera și încadrând zona vizibilă de mai sus.
- `setup_render` setează motorul EEVEE, rezoluția, color management, ieșire PNG.
