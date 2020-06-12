# Godot Engine's native Blender exporter add-on.

Native Godot scene format exporter for [Blender](https://www.blender.org), making the
export process to [Godot Engine](https://godotengine.org) as straightforward as possible.

*WARNING*: This exporter is experimental, and still lacks many features.

## Installation

1. Copy the `io_scene_godot` directory the location where Blender stores the
   scripts/addons folder on your system (you should see other io_scene_*
   folders there from other addons). Copy the entire dir and not just its
   contents.
2. Go to the Blender settings and enable the "Godot Exporter" plugin.
3. Export your file with `File` -> `Export` -> `Godot Engine (.escn)`

If you find bugs or want to suggest improvements, please open an issue on the
upstream [GitHub repository](https://github.com/godotengine/blender-exporter).


## Usage

See [the documentation](https://docs.godotengine.org/en/stable/getting_started/workflow/assets/escn_exporter/index.html) included in the official Godot docs).

## Development Notes

This repository includes a Makefile to assist with development. Running
`make` from the project root will:

1. Export all of the blend files from the `tests/scenes` directory.  
   If you add a feature, it is suggested that you add a new blend file to
   the `tests/scenes` directory that uses this feature.
2. Runs `diff` on the output files compared to the reference exports. This acts
   as a regression test.
3. Runs [pycodestyle](http://pycodestyle.pycqa.org/en/latest/) and
   [pylint](https://www.pylint.org/) style tests. Your code must pass these to
   be elegible to merge.


Current regression tests use the daily build of Blender 2.8 from Blender [official
site](https://builder.blender.org/download/) and runs on ubuntu 16.04. If you run
the tests with different Blender version or on different platforms, the output may
slightly differ.


## License

This Godot exporter is distributed under the terms of the GNU General
Public License, version 2 or later. See the [LICENSE.txt](/LICENSE.txt) file
for details.
