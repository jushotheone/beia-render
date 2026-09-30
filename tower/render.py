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
ap.add_argument("--look", choices=("day", "dusk"), default="day")
ap.add_argument("--percent", type=int, default=100)
ap.add_argument("--height", type=int, default=720, help="clip height; width follows at 16:9")
ap.add_argument("--check", action="store_true")
ap.add_argument("--frames", help="comma-separated 1-based frames to render (previews)")
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


def apply_dusk():
    """London at dusk: the grade that stops the city reading as a pale model.

    Judged on stills against the day look (2026-09-30): by day a flat white
    ground, a flat haze sky and a high sun make every neighbour a grey box.
    At dusk the ground drops away, the glass and the river reflect a real sky,
    and the city is lit from inside — the same exported scene, no new assets.
    """
    # One sky for every ray: the camera sees it, and the glass and the water
    # reflect it, which is most of what makes glass read as glass.
    for n in list(nt.nodes):
        if n.type not in ("OUTPUT_WORLD",):
            nt.nodes.remove(n)
    out = nt.nodes["World Output"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    rng = nt.nodes.new("ShaderNodeMapRange")
    rng.inputs["From Min"].default_value = -0.04
    rng.inputs["From Max"].default_value = 0.55
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    els = ramp.color_ramp.elements
    els[0].position, els[0].color = 0.0, (0.95, 0.52, 0.30, 1)  # horizon glow
    els[1].position, els[1].color = 1.0, (0.012, 0.03, 0.09, 1)  # zenith
    mid = els.new(0.12)
    mid.color = (0.34, 0.22, 0.34, 1)
    high = els.new(0.4)
    high.color = (0.05, 0.08, 0.18, 1)
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = 0.9
    nt.links.new(tc.outputs["Generated"], sep.inputs["Vector"])
    nt.links.new(sep.outputs["Z"], rng.inputs["Value"])
    nt.links.new(rng.outputs["Result"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])

    # A low sun behind the city rakes the tops of the towers warm and leaves
    # the streets in shadow.
    sun.data.energy = 2.4
    sun.data.color = (1.0, 0.55, 0.3)
    sun.data.angle = math.radians(1.5)
    sun.rotation_euler = (math.radians(84), 0, math.radians(215))

    lit = mathutils_noise_window_light
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        zs = [v.co.z for v in ob.data.vertices]
        flat = bool(zs) and max(zs) - min(zs) <= 1e-3
        for m in ob.data.materials:
            if not m or not m.use_nodes or m.get("_dusk"):
                continue
            m["_dusk"] = True
            b = m.node_tree.nodes.get("Principled BSDF")
            if not b:
                continue
            if flat:
                c = b.inputs["Base Color"].default_value
                if c[2] > c[0] * 1.8 and c[2] > 0.3:
                    # Water: dark and glossy, so it carries the sky and the
                    # lit city instead of a flat blue.
                    b.inputs["Base Color"].default_value = (0.01, 0.025, 0.035, 1)
                    b.inputs["Roughness"].default_value = 0.04
                else:
                    b.inputs["Base Color"].default_value = (c[0] * 0.28, c[1] * 0.28, c[2] * 0.28, 1)
                    b.inputs["Roughness"].default_value = 0.85
                continue
            es = b.inputs["Emission Strength"].default_value
            if es > 0 and footprint(ob) <= 300:
                # The tower's own light: lit ceilings, lamps and the BEIA
                # mark. At dusk they carry the frame, so warm and lift them.
                has_tex = any(n.type == "TEX_IMAGE" for n in m.node_tree.nodes)
                ec = b.inputs["Emission Color"].default_value
                # Only the near-white ceiling light is warmed. A district's
                # coloured wall and a working screen keep their own colour —
                # they are what say whose floor it is and that someone is on it.
                near_white = max(ec[:3]) > 0 and (max(ec[:3]) - min(ec[:3])) / max(ec[:3]) < 0.3
                if not has_tex and near_white:
                    b.inputs["Emission Color"].default_value = (1.0, 0.76, 0.5, 1)
                b.inputs["Emission Strength"].default_value = es * (2.5 if has_tex else 1.6)
                continue
            if footprint(ob) > 300:
                # Only the merged city meshes: BEIA's own tower shows its real
                # floors (live occupants, lit lenses), never a random pattern.
                lit(m, b)


def footprint(ob):
    cs = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
    return max(max(c.x for c in cs) - min(c.x for c in cs), max(c.y for c in cs) - min(c.y for c in cs))


def mathutils_noise_window_light(m, b):
    """Light the city's windows from its own facade textures.

    The textures are one storey tall and one bay wide, glass dark and wall
    light, so the glass is found from the texture's own darkness. How a
    building lights up depends on what it is, read from the same texture:
    a curtain wall (mostly glass) is an office, lit in floor bands a few bays
    wide; a punched facade is housing, lit window by window. Brightness is
    graded, never on/off, and always below the hero tower.
    """
    t = m.node_tree
    tex = next((n for n in t.nodes if n.type == "TEX_IMAGE" and n.image), None)
    if tex is None or not any(l.to_node.type == "MIX" for l in tex.outputs["Color"].links):
        return  # the facade pattern is mixed with the building's tint; a logo is not
    uv = tex.inputs["Vector"].links[0].from_socket if tex.inputs["Vector"].links else None
    if uv is None:
        return
    px = list(tex.image.pixels)
    lum = [0.3 * px[i] + 0.59 * px[i + 1] + 0.11 * px[i + 2] for i in range(0, len(px), 4)]
    # A punched facade is mostly light wall; a curtain wall has almost none.
    wall = sum(1 for v in lum if v > 0.72) / max(1, len(lum))
    office = wall < 0.12
    # Offices: one cell = five bays of one floor. Housing: one window.
    scale = t.nodes.new("ShaderNodeVectorMath")
    scale.operation = "MULTIPLY"
    scale.inputs[1].default_value = (0.2, 1.0, 1.0) if office else (1.0, 1.0, 1.0)
    t.links.new(uv, scale.inputs[0])
    cell = t.nodes.new("ShaderNodeVectorMath")
    cell.operation = "FLOOR"
    t.links.new(scale.outputs["Vector"], cell.inputs[0])
    noise = t.nodes.new("ShaderNodeTexWhiteNoise")
    noise.noise_dimensions = "3D"
    t.links.new(cell.outputs["Vector"], noise.inputs["Vector"])
    on = t.nodes.new("ShaderNodeMath")
    on.operation = "GREATER_THAN"
    on.inputs[1].default_value = 0.5 if office else 0.7
    t.links.new(noise.outputs["Value"], on.inputs[0])
    rgb = t.nodes.new("ShaderNodeSeparateColor")
    t.links.new(noise.outputs["Color"], rgb.inputs["Color"])
    grade = t.nodes.new("ShaderNodeMapRange")  # 0.35..1 of full brightness
    grade.inputs["To Min"].default_value = 0.35
    t.links.new(rgb.outputs[0], grade.inputs["Value"])
    lumn = t.nodes.new("ShaderNodeRGBToBW")
    t.links.new(tex.outputs["Color"], lumn.inputs["Color"])
    glass = t.nodes.new("ShaderNodeMath")
    glass.operation = "LESS_THAN"
    glass.inputs[1].default_value = 0.5
    t.links.new(lumn.outputs["Val"], glass.inputs[0])
    mask = t.nodes.new("ShaderNodeMath")
    mask.operation = "MULTIPLY"
    t.links.new(on.outputs[0], mask.inputs[0])
    t.links.new(glass.outputs[0], mask.inputs[1])
    graded = t.nodes.new("ShaderNodeMath")
    graded.operation = "MULTIPLY"
    t.links.new(mask.outputs[0], graded.inputs[0])
    t.links.new(grade.outputs["Result"], graded.inputs[1])
    strength = t.nodes.new("ShaderNodeMath")
    strength.operation = "MULTIPLY"
    strength.inputs[1].default_value = 0.32 if office else 0.7
    t.links.new(graded.outputs[0], strength.inputs[0])
    tint = t.nodes.new("ShaderNodeMix")
    tint.data_type = "RGBA"
    tint.inputs["A"].default_value = (1.0, 0.7, 0.42, 1)
    tint.inputs["B"].default_value = (0.92, 0.9, 0.84, 1) if office else (1.0, 0.82, 0.6, 1)
    t.links.new(rgb.outputs[1], tint.inputs["Factor"])
    t.links.new(tint.outputs["Result"], b.inputs["Emission Color"])
    t.links.new(strength.outputs[0], b.inputs["Emission Strength"])
    if office:
        # Curtain wall glass should carry the sky, not read as matte paint.
        b.inputs["Roughness"].default_value = 0.18
        b.inputs["Metallic"].default_value = 0.35


def add_haze(fog=(0.42, 0.27, 0.26)):
    """Distance haze on every surface, so the modelled city fades into the
    evening instead of ending at a hard edge. Done in each material from the
    camera distance — a world volume would cost a noisy render, and a
    compositor mist would also flatten the sky."""
    for m in bpy.data.materials:
        if not m.use_nodes or m.get("_haze"):
            continue
        t = m.node_tree
        out = next((n for n in t.nodes if n.type == "OUTPUT_MATERIAL"), None)
        if out is None or not out.inputs["Surface"].links:
            continue
        m["_haze"] = True
        src = out.inputs["Surface"].links[0].from_socket
        cam_d = t.nodes.new("ShaderNodeCameraData")
        rng = t.nodes.new("ShaderNodeMapRange")
        rng.inputs["From Min"].default_value = 280
        rng.inputs["From Max"].default_value = 1400
        rng.inputs["To Max"].default_value = 0.92
        t.links.new(cam_d.outputs["View Distance"], rng.inputs["Value"])
        em = t.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = (*fog, 1)
        mix = t.nodes.new("ShaderNodeMixShader")
        t.links.new(rng.outputs["Result"], mix.inputs["Fac"])
        t.links.new(src, mix.inputs[1])
        t.links.new(em.outputs["Emission"], mix.inputs[2])
        t.links.new(mix.outputs["Shader"], out.inputs["Surface"])


def add_bloom():
    """A soft glow around the lights — the difference between lit windows and
    white rectangles. Blender 5 builds the compositor as a node group."""
    try:
        tree = bpy.data.node_groups.new("Bloom", "CompositorNodeTree")
        scene.compositing_node_group = tree
        tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        rl = tree.nodes.new("CompositorNodeRLayers")
        glare = tree.nodes.new("CompositorNodeGlare")
        out = tree.nodes.new("NodeGroupOutput")
        for key, value in (("Type", "Bloom"), ("Quality", "High")):
            if key in glare.inputs:
                glare.inputs[key].default_value = value
        for key, value in (("Threshold", 0.9), ("Strength", 0.55), ("Size", 0.6)):
            if key in glare.inputs:
                glare.inputs[key].default_value = value
        tree.links.new(rl.outputs["Image"], glare.inputs["Image"])
        tree.links.new(glare.outputs["Image"], out.inputs[0])
        print("bloom: on")
    except (AttributeError, KeyError, TypeError, RuntimeError) as exc:
        print(f"bloom: unavailable ({exc})")


if args.look == "dusk":
    apply_dusk()
    add_haze()
    add_bloom()
    scene.view_settings.exposure = 0.0
    for look in ("AgX - Punchy", "Punchy", "AgX - Medium High Contrast"):
        try:
            scene.view_settings.look = look
            break
        except TypeError:
            continue


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

shots = json.load(open(os.path.join(here, "shots.json")))["shots"]
spec = shots[args.clip]
# A sequence cuts between saved moves: one clip, several shots, hard cuts.
segments = [shots[name] for name in spec["sequence"]] if "sequence" in spec else [spec]
fps = segments[0]["fps"]
counts = [int(fps * s["seconds"]) for s in segments]
n = sum(counts)
scene.render.resolution_x, scene.render.resolution_y = round(args.height * 16 / 9), args.height  # 16:9
scene.render.resolution_percentage = args.percent
scene.render.fps = fps
scene.render.image_settings.file_format = "PNG"
out_dir = os.path.join(shot, args.clip)
os.makedirs(out_dir, exist_ok=True)


def pose(f):
    for seg, count in zip(segments, counts):
        if f < count:
            break
        f -= count
    t = f / max(1, count - 1)
    t = t * t * (3 - 2 * t)  # ease in and out, like a real camera move
    if "orbit" in seg:
        o = seg["orbit"]
        a = math.radians(o["fromDeg"] + (o["toDeg"] - o["fromDeg"]) * t)
        c = o["centre"]
        pos = [c[0] + math.sin(a) * o["radius"], c[1] + o["height"], c[2] + math.cos(a) * o["radius"]]
        look = c
    else:
        k0, k1 = seg["path"][0], seg["path"][-1]
        pos = [k0["pos"][i] + (k1["pos"][i] - k0["pos"][i]) * t for i in range(3)]
        look = [k0["look"][i] + (k1["look"][i] - k0["look"][i]) * t for i in range(3)]
    return pos, look, seg.get("fov", cam_data["fov"])


def check_path():
    """Fail a camera move that goes inside, or too close to, a building, or
    whose view of its subject is blocked. Every stage of the first published
    orbit reported success while its last half second was the inside of a
    neighbouring tower; this is the check that would have caught it."""
    dg = bpy.context.evaluated_depsgraph_get()
    dirs = [Vector(d) for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))]
    problems = []
    for f in range(n):
        pos, look, _ = pose(f)
        p, target = z_up(pos), z_up(look)
        near = min((scene.ray_cast(dg, p, d, distance=50)[1] - p).length
                   if scene.ray_cast(dg, p, d, distance=50)[0] else 50 for d in dirs)
        # Inside a closed mesh, the ray straight up meets a face from behind.
        hit, loc, normal, *_ = scene.ray_cast(dg, p, Vector((0, 0, 1)), distance=2000)
        inside = hit and normal.z > 0.5
        to = target - p
        # The subject is the tower, so the look ray is expected to meet the
        # tower; only a hit on the city (the merged neighbour meshes) blocks.
        hit_b, _, _, _, hit_ob, _ = scene.ray_cast(dg, p, to.normalized(), distance=to.length)
        blocked = hit_b and hit_ob is not None and footprint(hit_ob) > 300
        if inside or near < 2.5 or blocked:
            why = "inside geometry" if inside else f"{near:.1f} m from a surface" if near < 2.5 else "view of the subject blocked"
            problems.append(f"frame {f + 1}: {why} at {[round(v) for v in pos]}")
    for line in problems[:40]:
        print("CHECK", line)
    print(f"CHECK {args.clip}: {n} frames, {len(problems)} problem frames")
    return not problems


if args.check:
    sys.exit(0 if check_path() else 3)
# The first runner checks the whole move before anyone renders it; with
# fail-fast, a bad path costs a minute instead of twenty runners' time.
if args.chunk == 0 and not args.frames and not check_path():
    sys.exit(3)


# Frames are numbered 1..n in the file names whichever runner draws them, so
# the chunks drop into one folder and assemble in order.
mine = ([int(x) - 1 for x in args.frames.split(",")] if args.frames
        else [f for f in range(n) if f % args.of == args.chunk])
for f in mine:
    pos, look, fov = pose(f)
    cam.data.angle_y = math.radians(fov)
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
