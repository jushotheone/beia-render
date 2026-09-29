# tower/render.py — render the exported BEIA Tower offline in Blender Cycles.
#
#   blender -b -P tower/render.py -- <shot-dir> [--samples 16] [--hdri <file.hdr>]
#       still:  writes <shot-dir>/blender.png from the exported camera
#       --clip <name> [--chunk i --of n] [--mp4]
#               renders a saved camera move from tower/shots.json into
#               <shot-dir>/<name>/frame_NNNN.png. With --chunk, only every n-th
#               frame starting at i (so n runners can share one clip); with
#               --mp4, assembles <shot-dir>/<name>.mp4 with ffmpeg afterwards.
#
# <shot-dir> holds tower/export-scene.mjs's output (tower.glb, camera.json),
# after tower/fix-glb.cjs. Lighting: the console's CC0 Canary Wharf HDRI (the
# live tower's own sky) plus one sun, so offline and live are lit alike.
# Uses the GPU when Blender finds one (Metal on a Mac) and the CPU otherwise.

import argparse
import json
import math
import os
import subprocess
import sys

import bmesh
import bpy
from mathutils import Quaternion, Vector

here = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("shot")
ap.add_argument("--samples", type=int, default=16)
ap.add_argument("--hdri", default=os.path.join(here, "canary_wharf.hdr"))
ap.add_argument("--clip")
ap.add_argument("--chunk", type=int, default=0)
ap.add_argument("--of", type=int, default=1)
ap.add_argument("--mp4", action="store_true")
args = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
shot = os.path.abspath(args.shot)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.join(shot, "tower.glb"))

# Lights from the browser (hemisphere/fill tuned for WebGL) don't translate;
# the HDRI and one sun below replace them.
for ob in list(bpy.data.objects):
    if ob.type == "LIGHT":
        bpy.data.objects.remove(ob, do_unlink=True)

# The browser draws flat ground layers (roads, water, parks) double-sided;
# some arrive with normals facing down, which Cycles shades black. Face them
# up and drop their custom normals.
for ob in bpy.data.objects:
    if ob.type != "MESH":
        continue
    me = ob.data
    zs = [v.co.z for v in me.vertices]
    if not zs or max(zs) - min(zs) > 1e-3:
        continue
    bm = bmesh.new()
    bm.from_mesh(me)
    for f in bm.faces:
        if (ob.matrix_world.to_3x3() @ f.normal).z < 0:
            f.normal_flip()
    bm.to_mesh(me)
    bm.free()
    for name in [a.name for a in me.attributes if "normal" in a.name.lower()]:
        try:
            me.attributes.remove(me.attributes[name])
        except (KeyError, RuntimeError):
            pass
    for p in me.polygons:
        p.use_smooth = False

cam_data = json.load(open(os.path.join(shot, "camera.json")))
x, y, z = cam_data["position"]
qx, qy, qz, qw = cam_data["quaternion"]
cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
bpy.context.scene.collection.objects.link(cam)
# three.js is Y-up, Blender Z-up: (x, y, z) -> (x, -z, y), and the same
# +90 degree turn about X applied to the camera's orientation.
cam.location = Vector((x, -z, y))
cam.rotation_mode = "QUATERNION"
cam.rotation_quaternion = Quaternion((1, 0, 0), math.radians(90)) @ Quaternion((qw, qx, qy, qz))
cam.data.sensor_fit = "VERTICAL"
cam.data.angle_y = math.radians(cam_data["fov"])
cam.data.clip_start = 0.05
cam.data.clip_end = 4000
scene = bpy.context.scene
scene.camera = cam

world = bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
nt = world.node_tree
env = nt.nodes.new("ShaderNodeTexEnvironment")
env.image = bpy.data.images.load(os.path.abspath(args.hdri))
nt.links.new(env.outputs["Color"], nt.nodes["Background"].inputs["Color"])
nt.nodes["Background"].inputs["Strength"].default_value = 0.7
# The HDRI lights the scene but is not seen: to the camera the sky is a plain
# London haze (the browser's sky colour), so the photographed skyline in the
# HDRI never hangs behind the model city.
lp = nt.nodes.new("ShaderNodeLightPath")
sky = nt.nodes.new("ShaderNodeBackground")
sky.inputs["Color"].default_value = (0.62, 0.72, 0.8, 1)
sky.inputs["Strength"].default_value = 1.0
mix = nt.nodes.new("ShaderNodeMixShader")
nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs["Fac"])
nt.links.new(nt.nodes["Background"].outputs["Background"], mix.inputs[1])
nt.links.new(sky.outputs["Background"], mix.inputs[2])
nt.links.new(mix.outputs["Shader"], nt.nodes["World Output"].inputs["Surface"])

sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
sun.data.energy = 2.2
sun.data.angle = math.radians(2)
sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(35))
scene.collection.objects.link(sun)

scene.render.engine = "CYCLES"
scene.cycles.samples = args.samples
scene.cycles.use_denoising = True
scene.render.use_persistent_data = True  # keep the BVH between frames
prefs = bpy.context.preferences.addons["cycles"].preferences
scene.cycles.device = "CPU"
for backend in ("METAL", "OPTIX", "CUDA"):
    try:
        prefs.compute_device_type = backend
        prefs.get_devices()
        gpus = [d for d in prefs.devices if d.type != "CPU"]
        if gpus:
            for d in prefs.devices:
                d.use = True
            scene.cycles.device = "GPU"
            break
    except (TypeError, ValueError):
        continue
print(f"cycles device: {scene.cycles.device}, samples {args.samples}")
scene.render.resolution_x = cam_data.get("width", 1280)
scene.render.resolution_y = cam_data.get("height", 720)
scene.render.resolution_percentage = 100
try:
    scene.view_settings.view_transform = "AgX"
except TypeError:
    scene.view_settings.view_transform = "Filmic"
scene.view_settings.exposure = -0.6


def z_up(p):
    # three.js (x, y, z), Y up  ->  Blender (x, -z, y), Z up
    return Vector((p[0], -p[2], p[1]))


def aim(ob, target):
    d = (target - ob.location).normalized()
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = d.to_track_quat("-Z", "Y")


if not args.clip:
    scene.render.filepath = os.path.join(shot, "blender.png")
    bpy.ops.render.render(write_still=True)
    print("wrote", scene.render.filepath)
    sys.exit(0)

spec = json.load(open(os.path.join(here, "shots.json")))["shots"][args.clip]
fps, n = spec["fps"], int(spec["fps"] * spec["seconds"])
scene.render.resolution_x, scene.render.resolution_y = 1280, 720  # clips are 16:9
scene.render.fps = fps
scene.render.image_settings.file_format = "PNG"
out_dir = os.path.join(shot, args.clip)
os.makedirs(out_dir, exist_ok=True)


def pose(f):
    t = f / max(1, n - 1)
    t = t * t * (3 - 2 * t)  # ease in and out, like a real camera move
    if "orbit" in spec:
        o = spec["orbit"]
        a = math.radians(o["fromDeg"] + (o["toDeg"] - o["fromDeg"]) * t)
        c = o["centre"]
        pos = [c[0] + math.sin(a) * o["radius"], c[1] + o["height"], c[2] + math.cos(a) * o["radius"]]
        look = c
    else:
        k0, k1 = spec["path"][0], spec["path"][-1]
        pos = [k0["pos"][i] + (k1["pos"][i] - k0["pos"][i]) * t for i in range(3)]
        look = [k0["look"][i] + (k1["look"][i] - k0["look"][i]) * t for i in range(3)]
    return pos, look


# Frames are numbered 1..n in the file names whichever runner draws them, so
# the chunks drop into one folder and assemble in order.
mine = [f for f in range(n) if f % args.of == args.chunk]
for f in mine:
    pos, look = pose(f)
    cam.location = z_up(pos)
    aim(cam, z_up(look))
    scene.render.filepath = os.path.join(out_dir, f"frame_{f + 1:04d}.png")
    bpy.ops.render.render(write_still=True)
    print(f"frame {f + 1}/{n} done", flush=True)

if args.mp4:
    mp4 = os.path.join(shot, args.clip + ".mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
                    "-i", os.path.join(out_dir, "frame_%04d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", mp4], check=True)
    print("wrote", mp4)
