import bpy
import os
import sys
import traceback
import json

sys.path = [os.getcwd()] + sys.path  # Ensure exporter from this folder

TEST_SCENE_DIR = os.path.join(os.getcwd(), "tests/test_scenes")
EXPORTED_DIR = os.path.join(os.getcwd(), "tests/godot_project/exports")

def export_escn(out_file, config):
    """Fake the export operator call"""
    import io_scene_godot
    io_scene_godot.export(out_file, config)


def main():
    dir_queue = list()
    dir_queue.append('.')
    while dir_queue:
        dir_relpath = dir_queue.pop(0)

        # read config file if present, otherwise use default
        src_dir_path = os.path.join(TEST_SCENE_DIR, dir_relpath)
        if os.path.exists(os.path.join(src_dir_path, "config.json")):
            with open(os.path.join(src_dir_path, "config.json")) as config_file:
                config = json.load(config_file)
        else:
            config = {}

        # create exported to directory
        exported_dir_path = os.path.join(EXPORTED_DIR, dir_relpath)
        if not os.path.exists(exported_dir_path):
            os.makedirs(exported_dir_path)

        for item in os.listdir(os.path.join(TEST_SCENE_DIR, dir_relpath)):
            item_abspath = os.path.join(TEST_SCENE_DIR, dir_relpath, item)
            if os.path.isdir(item_abspath):
                # push dir into queue for later traversal
                dir_queue.append(os.path.join(dir_relpath, item))
            elif item_abspath.endswith('blend'):
                # export blend file
                print("---------")
                print("Exporting {}".format(os.path.abspath(item_abspath)))
                bpy.ops.wm.open_mainfile(filepath=item_abspath)

                out_path = os.path.join(
                    EXPORTED_DIR,
                    dir_relpath,
                    item.replace('.blend', '.escn')
                    )
                export_escn(out_path, config)
                print("Exported to {}".format(os.path.abspath(out_path)))


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
