"""Coordonator: asamblează decorul + personajele și randează.

blender.exe -b --factory-startup --python scena.py -- --still output/static.png [--w 960 --h 540 --samples 16]
"""
import argparse
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import decor  # noqa: E402
import personaje  # noqa: E402


def clear():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def look_at(ch, world_target):
    """Mută controlul `privire` al personajului pe un punct din lume."""
    rig = ch["rig"]
    pb = rig.pose.bones["privire"]
    pb.matrix = rig.matrix_world.inverted() @ Matrix.Translation(world_target)
    bpy.context.view_layer.update()


def head_pos(ch):
    rig = ch["rig"]
    pb = rig.pose.bones["head"]
    return rig.matrix_world @ ((pb.head + pb.tail) / 2)


def build(w, h, samples):
    clear()
    room = decor.build_room()
    decor.setup_render(width=w, height=h, fps=30, samples=samples)
    mama = personaje.build_mama("Mama")
    fetita = personaje.build_fetita("Fetita")
    return room, mama, fetita


def pose_static(mama, fetita):
    """Poza pentru verificarea aspectului: amândouă spre cameră, întoarse ușor una spre alta."""
    mama["rig"].location = (0.45, 0.0, 0.0)
    mama["rig"].rotation_euler.z = math.radians(-25)   # spre stânga (spre fetiță)
    fetita["rig"].location = (-0.55, -0.1, 0.0)
    fetita["rig"].rotation_euler.z = math.radians(25)  # spre dreapta (spre mamă)
    bpy.context.view_layer.update()
    look_at(fetita, head_pos(mama))
    look_at(mama, head_pos(fetita))
    for ch in (mama, fetita):
        ch["mouth"].data.shape_keys.key_blocks["zambet"].value = 0.7


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--still", default=os.path.join(HERE, "output", "static.png"))
    ap.add_argument("--w", type=int, default=960)
    ap.add_argument("--h", type=int, default=540)
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--camera", default="Camera")
    a = ap.parse_args(argv)

    _, mama, fetita = build(a.w, a.h, a.samples)
    pose_static(mama, fetita)
    bpy.context.scene.camera = bpy.data.objects[a.camera]
    bpy.context.scene.render.filepath = os.path.abspath(a.still)
    bpy.ops.render.render(write_still=True)
    print("SCENA_OK", a.still)


if __name__ == "__main__":
    main()
