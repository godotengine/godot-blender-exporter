import bpy
import os
import sys
import traceback

sys.path = [os.getcwd()] + sys.path  # Ensure exporter from this folder
from io_scene_godot import export_godot


def export_escn(out_file):
    """Fake the export operator call"""
    class op:
        def __init__(self):
            self.report = print
            
    res = export_godot.save(op(), bpy.context, out_file, 
        object_types={"EMPTY", "CAMERA", "LAMP", "ARMATURE", "MESH", "CURVE"},
        use_active_layers=False,
        use_export_selected=False,
        use_mesh_modifiers=True,
        material_search_paths = 'PROJECT_DIR'
    )



def main():
    target_dir = os.path.join(os.getcwd(), "tests/scenes")
    for file_name in os.listdir(target_dir):
        full_path = os.path.join(target_dir, file_name)
        if full_path.endswith(".blend"):
            print("Exporting {}".format(full_path))
            bpy.ops.wm.open_mainfile(filepath=full_path)
            
            out_path, blend_name = os.path.split(full_path)
            out_path = os.path.normpath(os.path.join(out_path, '../exports/'))
            out_path = os.path.join(
                out_path, 
                blend_name.replace('.blend', '.escn')
                )
            print(out_path)
            export_escn(out_path)
            print("Exported")


def run_with_abort(function):
    """Runs a function such that an abort causes blender to quit with an error
    code. Otherwise, even a failed script will allow the Makefile to continue
    running"""
    try:
        function()
    except:
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    run_with_abort(main)
