import os
import shutil
import platform


if platform.system() == "Windows":
	BLENDER_PATH = "C:\\Program Files\\Blender Foundation\\Blender\\blender.exe"
	PYTHON3_PATH = "C:\Program Files\Python36\python.exe"
else:
	BLENDER_PATH = "blender"
	PYTHON3_PATH = "python3"

var = Variables()
var.AddVariables(
	("BLENDER", "path to blender executable", BLENDER_PATH),
	("PYTHON3", "path to python3 executable. Pylint and pycodestyle should be available here", PYTHON3_PATH)
)


env = Environment(variables=var)
Help(var.GenerateHelpText(env))

# Constants within the respository
EXPORT_DIR = './tests/godot_project/exports'
REFERENCE_DIR = './tests/reference_exports'


def export_blends(target, source, env): 
	if os.path.exists(EXPORT_DIR):  # Clear old exports
		shutil.rmtree(EXPORT_DIR) 
	os.makedirs(EXPORT_DIR) 
	
	if os.path.exists('./tests/godot_project/.import'):
		# Ensure we don't have any data cached in godot
		shutil.rmtree('./tests/godot_project/.import')  

	return systemcall('"{}" -b --python ./tests/export_test_scenes.py'.format(
		env['BLENDER']
	))

def systemcall(command):
	if os.system(command) != 0:
		raise Exception("Build Failed")

  
def compare_exports(target, source, env): 
	import difflib
	files_1 = {f for f in os.listdir(EXPORT_DIR) if not f.endswith('.import')}
	files_2 = {f for f in os.listdir(REFERENCE_DIR) if not f.endswith('.import')}
	
	error = False
	differ = difflib.Differ()
	
	for file_name in files_1.union(files_2):
		if file_name not in files_2:
			print("File {} does not exist in path {}".format(file_name, REFERENCE_DIR))
			error = True
			continue
		if file_name not in files_1:
			print("File {} does not exist in path {}".format(file_name, EXPORT_DIR))
			error = True
			continue
	
		data1 = open(os.path.join(REFERENCE_DIR, file_name)).readlines()
		data2 = open(os.path.join(EXPORT_DIR, file_name)).readlines()

		for line_id, line in enumerate(data1):  # Windows vs linux paths shouldn't be considered different
			data1[line_id] = line.replace('/', '\\')
		for line_id, line in enumerate(data2):
			data2[line_id] = line.replace('/', '\\')
		
		for line_number, line in enumerate(differ.compare(data1, data2)):
			if not line[0] == ' ':
				error = True
				print(file_name, line.strip())
				
	if error:
		raise Exception("There are differences between the current exports and the reference exports")
	else:
		print("All Files Match")

def update_examples(target, source, env):
	if os.path.exists(REFERENCE_DIR):
		shutil.rmtree(REFERENCE_DIR)
	shutil.copytree(EXPORT_DIR, REFERENCE_DIR)


def style_test(target, source, env):
	systemcall('"{}" -m pycodestyle io_scene_godot'.format(env["PYTHON3"]))
	systemcall('"{}" -m pylint io_scene_godot'.format(env["PYTHON3"]))


export = env.Command('export_blends', None, export_blends) 
compare = env.Command('compare', None, compare_exports) 
env.Command('update_examples', None, update_examples)
env.Command('style_test', None, style_test)

Depends(compare, export)

Default("compare", "style_test")
