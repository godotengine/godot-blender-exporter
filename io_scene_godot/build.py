#!/usr/bin/env python

from os.path import abspath, dirname, join as pjoin
import zipfile

SRC_DIR = dirname(abspath(__file__))

with zipfile.ZipFile('io_scene_godot.zip', 'w', zipfile.ZIP_DEFLATED) as arch:
    for filename in [
            '__init__.py',
			'export_godot.py']:
        arch.write(pjoin(SRC_DIR, filename), 'io_scene_godot/'+filename)

print('created file: io_scene_godot.zip')
