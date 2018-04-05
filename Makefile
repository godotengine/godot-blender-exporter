PYLINT = pylint3
PEP8 = pep8
BLENDER = blender
GODOT = godot

.DEFAULT_GOAL := all

pylint:
	$(PYLINT) io_scene_godot
	$(PYLINT) io_scene_godot

pep8:
	$(PEP8) io_scene_godot


export-blends:
	mkdir -p ./tests/exports/
	rm -rf ./tests/.import  # Ensure we don't have any hangover data
	$(BLENDER) -b --python ./tests/scenes/export_blends.py


test-import: export-blends
	$(GODOT) -e -q --path tests/ > log.txt 2>&1
	@cat log.txt
	! grep -q "ERROR" log.txt


update-examples:
	mkdir -p tests/reference-exports
	cp tests/exports/*.escn tests/reference-exports
	
compare: export-blends
	diff -x "*.escn.import" -r tests/exports/ tests/reference-exports/


style-test: pep8 pylint

all: compare style-test
