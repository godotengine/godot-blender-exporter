PYLINT = pylint3
PEP8 = pep8
BLENDER = blender
GODOT = godot

pylint:
	$(PYLINT) io_scene_godot
	$(PYLINT) io_scene_godot

pep8:
	$(PEP8) io_scene_godot


.PHONY = test-blends
test-blends:
	rm -rf ./tests/.import  # Ensure we don't have any hangover data
	$(BLENDER) -b --python ./tests/scenes/export_blends.py


test-import: test-blends
	$(GODOT) -e -q --path tests/ > log.txt 2>&1
	@cat log.txt
	! grep -q "ERROR" log.txt
