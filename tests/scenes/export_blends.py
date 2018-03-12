import bpy
import os
import sys


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
			export_escn(full_path.replace('.blend', '.escn'))
			print("Exported")


if __name__ == "__main__":
	main()
