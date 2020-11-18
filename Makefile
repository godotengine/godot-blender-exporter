PYLINT = pylint
PEP8 = pycodestyle
BLENDER = blender
GODOT = godot

.DEFAULT_GOAL := all

pylint:
	$(PYLINT) io_scene_godot

pep8:
	$(PEP8) io_scene_godot


export-blends:
	mkdir -p ./tests/godot_project/exports/
	rm -rf ./tests/godot_project/.import  # Ensure we don't have any hangover data
	$(BLENDER) -b --python ./tests/export_test_scenes.py


test-import: export-blends
	$(GODOT) -e -q --path tests/ > log.txt 2>&1
	@cat log.txt
	! grep -q "ERROR" log.txt


update-examples:
	mkdir -p tests/reference_exports
	find tests/godot_project/exports/ -name *.escn | while read f; \
	do \
		mkdir -p "tests/reference_exports/$$(echo $$f | cut -d/ -f4)"; \
		cp "$$f" "tests/reference_exports/$$(echo $$f | cut -d/ -f4-)"; \
	done;

compare: export-blends
	diff -x "*.escn.import" -r tests/godot_project/exports/ tests/reference_exports/


style-test: pep8 pylint

all: style-test compare
