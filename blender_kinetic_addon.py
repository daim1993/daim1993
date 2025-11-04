bl_info = {
    "name": "Kinetic Screen 18×8 (Video → Pops)",
    "author": "you + ChatGPT",
    "version": (2, 0, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > Kinetic",
    "description": "Builds an 18×8 grid, samples an MP4 to drive pop-out depth (black=0, white=max), 45° lighting, bakes keys, and renders 2304×1024 with shadows.",
    "category": "Animation",
}

import bpy
import os
import math
from mathutils import Vector
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import (
    StringProperty, FloatProperty, IntProperty, BoolProperty, EnumProperty
)

# ---------------------------
# Helpers
# ---------------------------

def smoothstep(x: float) -> float:
    x = max(0.0, min(1.0, float(x)))
    return x * x * (3.0 - 2.0 * x)

def ensure_collection(name: str):
    scn = bpy.context.scene
    if name in bpy.data.collections:
        col = bpy.data.collections[name]
        if col.name not in [c.name for c in scn.collection.children]:
            scn.collection.children.link(col)
        return col
    col = bpy.data.collections.new(name)
    scn.collection.children.link(col)
    return col

def remove_collection(name: str):
    if name in bpy.data.collections:
        col = bpy.data.collections[name]
        for o in list(col.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.collections.remove(col)

def set_key_interp_bezier(obj, data_path, index=None):
    ad = obj.animation_data
    if not ad or not ad.action: return
    for fc in ad.action.fcurves:
        if fc.data_path == data_path and (index is None or fc.array_index == index):
            for k in fc.keyframe_points:
                k.interpolation = 'BEZIER'
                k.handle_left_type = 'AUTO'
                k.handle_right_type = 'AUTO'

def has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False

# ---------------------------
# Properties
# ---------------------------

class KineticProps(PropertyGroup):
    video_path: StringProperty(
        name="Choreography MP4",
        description="Black = 0 pop, White = max pop",
        subtype='FILE_PATH'
    )
    max_pop: FloatProperty(
        name="Max Pop Height (BU)",
        default=2.0, min=0.01, max=20.0
    )
    ease_strength: FloatProperty(
        name="Ease (Smoothstep)",
        default=1.0, min=0.0, max=1.0,
        description="0 = linear, 1 = full smoothstep"
    )
    invert: BoolProperty(
        name="Invert Brightness",
        default=False,
        description="White = 0, Black = max"
    )
    sample_step: IntProperty(
        name="Frame Step",
        default=1, min=1, max=8,
        description="Bake every Nth frame (reduces key count)"
    )
    fps_override: IntProperty(
        name="FPS (0 = from video)",
        default=0, min=0, max=240
    )
    box_size: FloatProperty(
        name="Box Size (BU)",
        default=1.28, min=0.1, max=10.0,
        description="18 * 1.28 = 23.04 BU (matches 2304 px)"
    )
    gap: FloatProperty(
        name="Gap (BU)",
        default=0.02, min=0.0, max=1.0
    )
    engine: EnumProperty(
        name="Render Engine",
        items=[
            ('CYCLES', 'Cycles', 'High-quality shadows'),
            ('BLENDER_EEVEE', 'Eevee', 'Fast preview')
        ],
        default='CYCLES'
    )
    samples: IntProperty(
        name="Samples",
        default=128, min=1, max=4096
    )
    out_path: StringProperty(
        name="Output File",
        subtype='FILE_PATH',
        default="//kinetic_output.mp4"
    )

# ---------------------------
# Operators
# ---------------------------

class KIN_OT_InstallOpenCV(Operator):
    bl_idname = "kinetic.install_opencv"
    bl_label = "Install OpenCV (headless)"
    bl_description = "Installs opencv-python-headless into Blender's Python"
    bl_options = {'REGISTER'}

    def execute(self, context):
        import sys, subprocess, ensurepip
        try:
            ensurepip.bootstrap()
            py = sys.executable
            subprocess.check_call([py, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
            subprocess.check_call([py, "-m", "pip", "install", "opencv-python-headless", "numpy"])
            self.report({'INFO'}, "Installed opencv-python-headless + numpy.")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed: {e}")
            return {'CANCELLED'}

class KIN_OT_CreateGrid(Operator):
    bl_idname = "kinetic.create_grid"
    bl_label = "Create 18×8 Grid"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        p = context.scene.kinetic_props
        cols, rows = 18, 8
        box = p.box_size
        gap = p.gap
        spacing = box + gap

        # cleanup & collection
        remove_collection("KineticScreen")
        col = ensure_collection("KineticScreen")

        # parent
        parent = bpy.data.objects.new("KineticScreen_Parent", None)
        col.objects.link(parent)

        # shared material
        mat = bpy.data.materials.get("Kinetic_Mat")
        if not mat:
            mat = bpy.data.materials.new("Kinetic_Mat")
            mat.use_nodes = True
            nt = mat.node_tree
            nt.nodes.clear()
            out = nt.nodes.new("ShaderNodeOutputMaterial")
            bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
            bsdf.inputs['Base Color'].default_value = (0.2, 0.2, 0.2, 1.0)
            bsdf.inputs['Roughness'].default_value = 0.5
            nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

        # center offsets
        offset_x = -(cols * spacing) / 2 + spacing / 2
        offset_y = -(rows * spacing) / 2 + spacing / 2

        # create cubes
        for r in range(rows):
            for c in range(cols):
                bpy.ops.mesh.primitive_cube_add(size=box)
                o = context.active_object
                o.name = f"Box_{r:02d}_{c:02d}"
                o.location = Vector((
                    offset_x + c * spacing,
                    offset_y + r * spacing,
                    0.0
                ))
                o.data.materials.clear()
                o.data.materials.append(mat)
                o.parent = parent
                o["grid_row"] = r
                o["grid_col"] = c

                # move to collection
                for oc in list(o.users_collection):
                    oc.objects.unlink(o)
                col.objects.link(o)

        # lighting & camera
        self.setup_lighting(col)
        self.setup_camera(cols * spacing, rows * spacing)
        self.report({'INFO'}, "Created grid, lighting, and camera.")
        return {'FINISHED'}

    def setup_lighting(self, col):
        for name in ("Kinetic_Sun", "Kinetic_Fill"):
            obj = bpy.data.objects.get(name)
            if obj:
                bpy.data.objects.remove(obj, do_unlink=True)

        # 45° sun
        sun = bpy.data.lights.new("Kinetic_Sun_Data", type='SUN')
        sun.energy = 3.0
        sun.angle = math.radians(5)
        sobj = bpy.data.objects.new("Kinetic_Sun", sun)
        sobj.location = (10, -10, 10)
        sobj.rotation_euler = (math.radians(45), 0.0, math.radians(45))
        col.objects.link(sobj)

        # fill
        area = bpy.data.lights.new("Kinetic_Fill_Data", type='AREA')
        area.energy = 1000
        area.shape = 'SQUARE'
        area.size = 40
        aobj = bpy.data.objects.new("Kinetic_Fill", area)
        aobj.location = (0, 0, 20)
        col.objects.link(aobj)

    def setup_camera(self, width, height):
        cam = bpy.data.objects.get("Kinetic_Cam")
        if cam:
            bpy.data.objects.remove(cam, do_unlink=True)
        bpy.ops.object.camera_add(location=(0, 0, 30))
        cam = bpy.context.active_object
        cam.name = "Kinetic_Cam"
        cam.rotation_euler = (0.0, 0.0, 0.0)
        bpy.context.scene.camera = cam
        cam.data.type = 'ORTHO'
        cam.data.ortho_scale = max(width, height) * 1.15

class KIN_OT_LoadVideoAndBake(Operator):
    bl_idname = "kinetic.load_video_and_bake"
    bl_label = "Load Video → Bake Keys"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Import here so add-on can still register without OpenCV present
        if not has_module("cv2") or not has_module("numpy"):
            self.report({'ERROR'}, "OpenCV not found. Click 'Install OpenCV (headless)' first.")
            return {'CANCELLED'}

        import cv2
        import numpy as np

        p = context.scene.kinetic_props
        path = bpy.path.abspath(p.video_path)
        if not path or not os.path.exists(path):
            self.report({'ERROR'}, "Please choose a valid MP4 file.")
            return {'CANCELLED'}

        # collect boxes
        boxes = [o for o in bpy.data.objects if o.name.startswith("Box_")]
        if not boxes:
            self.report({'ERROR'}, "No boxes found. Create the grid first.")
            return {'CANCELLED'}

        # map (r,c) -> object
        cols, rows = 18, 8
        grid = [[None for _ in range(cols)] for _ in range(rows)]
        for o in boxes:
            r = int(o.get("grid_row", 0))
            c = int(o.get("grid_col", 0))
            if 0 <= r < rows and 0 <= c < cols:
                grid[r][c] = o
            # ensure action exists
            if not o.animation_data:
                o.animation_data_create()
            if not o.animation_data.action:
                o.animation_data.action = bpy.data.actions.new(name=f"{o.name}_Action")

        # open video
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            self.report({'ERROR'}, "Failed to open video with OpenCV.")
            return {'CANCELLED'}

        fps_v = cap.get(cv2.CAP_PROP_FPS) or 0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = p.fps_override if p.fps_override > 0 else (int(round(fps_v)) if fps_v > 0 else 30)
        duration = total_frames if total_frames > 0 else 300

        scene = context.scene
        scene.frame_start = 1
        scene.frame_end = duration
        scene.render.fps = fps

        # bake loop
        target_size = (cols, rows)  # width, height
        step = max(1, int(p.sample_step))
        read_index = 0
        baked_count = 0

        while True:
            ret, frame_bgr = cap.read()
            if not ret:
                break
            read_index += 1

            if (read_index - 1) % step != 0:
                continue

            # BGR->RGB, resize to 18x8, convert to 0..1 floats
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            small = cv2.resize(frame_rgb, target_size, interpolation=cv2.INTER_AREA)
            small_f = small.astype(np.float32) / 255.0

            # Rec.709 luminance
            luma = (0.2126 * small_f[..., 0] +
                    0.7152 * small_f[..., 1] +
                    0.0722 * small_f[..., 2])

            if p.invert:
                luma = 1.0 - luma

            if p.ease_strength > 0.0:
                s = luma * luma * (3.0 - 2.0 * luma)
                luma = (1.0 - p.ease_strength) * luma + p.ease_strength * s

            f = read_index  # timeline frame index starts at 1

            # insert keys
            for r in range(rows):
                for c in range(cols):
                    obj = grid[r][c]
                    if obj is None: continue
                    z = float(luma[r, c]) * p.max_pop
                    obj.location.z = z
                    obj.keyframe_insert(data_path="location", frame=f, index=2)

            baked_count += 1
            if baked_count % 50 == 0:
                self.report({'INFO'}, f"Baked {baked_count} frames...")

            if read_index >= duration:
                break

        cap.release()

        # smooth curves
        for o in boxes:
            set_key_interp_bezier(o, "location", index=2)

        self.report({'INFO'}, f"Baked {baked_count} sampled frames (step={step}).")
        return {'FINISHED'}

class KIN_OT_SetupRender(Operator):
    bl_idname = "kinetic.setup_render"
    bl_label = "Setup Render (2304×1024)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = context.scene
        p = context.scene.kinetic_props

        s.render.resolution_x = 2304
        s.render.resolution_y = 1024
        s.render.resolution_percentage = 100

        # engine
        engine = p.engine
        try:
            s.render.engine = engine
        except Exception:
            # Blender flavors differ; silently fallback to Cycles
            s.render.engine = 'CYCLES'

        if s.render.engine == 'CYCLES':
            s.cycles.samples = p.samples
            s.cycles.use_denoising = True
            s.cycles.use_adaptive_sampling = True
        else:
            s.eevee.use_soft_shadows = True
            s.eevee.shadow_cube_size = '1024'
            s.eevee.shadow_cascade_size = '2048'
            s.eevee.taa_samples = min(64, p.samples)

        # output
        s.render.image_settings.file_format = 'FFMPEG'
        s.render.ffmpeg.format = 'MPEG4'
        s.render.ffmpeg.codec = 'H264'
        s.render.ffmpeg.constant_rate_factor = 'HIGH'
        s.render.filepath = bpy.path.abspath(p.out_path)

        self.report({'INFO'}, f"Render configured → {s.render.filepath}")
        return {'FINISHED'}

class KIN_OT_Render(Operator):
    bl_idname = "kinetic.render_animation"
    bl_label = "Render Animation"
    bl_options = {'REGISTER'}

    def execute(self, context):
        bpy.ops.render.render('INVOKE_DEFAULT', animation=True)
        return {'FINISHED'}

# ---------------------------
# UI
# ---------------------------

class KIN_PT_Main(Panel):
    bl_label = "Kinetic Screen"
    bl_idname = "KIN_PT_MAIN"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Kinetic'

    def draw(self, context):
        l = self.layout
        p = context.scene.kinetic_props

        if not has_module("cv2") or not has_module("numpy"):
            box = l.box()
            box.label(text="Dependency", icon='INFO')
            box.label(text="OpenCV (headless) is required.")
            box.operator("kinetic.install_opencv", icon='CONSOLE')

        b = l.box()
        b.label(text="1) Create Grid", icon='MESH_GRID')
        b.prop(p, "box_size")
        b.prop(p, "gap")
        b.operator("kinetic.create_grid", icon='ADD')

        b = l.box()
        b.label(text="2) Load Video & Bake", icon='FILE_MOVIE')
        b.prop(p, "video_path", text="")
        row = b.row(align=True)
        row.prop(p, "max_pop")
        row.prop(p, "sample_step")
        row = b.row(align=True)
        row.prop(p, "ease_strength")
        row.prop(p, "invert")
        b.prop(p, "fps_override")
        b.operator("kinetic.load_video_and_bake", icon='KEY_HLT')

        b = l.box()
        b.label(text="3) Render", icon='RENDER_ANIMATION')
        b.prop(p, "engine")
        b.prop(p, "samples")
        b.prop(p, "out_path", text="Output")
        b.operator("kinetic.setup_render", icon='PREFERENCES')
        b.operator("kinetic.render_animation", icon='RENDER_ANIMATION')

# ---------------------------
# Register
# ---------------------------

classes = (
    KineticProps,
    KIN_OT_InstallOpenCV,
    KIN_OT_CreateGrid,
    KIN_OT_LoadVideoAndBake,
    KIN_OT_SetupRender,
    KIN_OT_Render,
    KIN_PT_Main,
)

def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.kinetic_props = bpy.props.PointerProperty(type=KineticProps)

def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    del bpy.types.Scene.kinetic_props

if __name__ == "__main__":
    register()
