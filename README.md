# Godot Engine's native Blender exporter add-on.

Native Godot scene format exporter for [Blender](https://www.blender.org), making the
export process to [Godot Engine](https://godotengine.org) as straightforward as possible.

*WARNING*: This exporter is experimental, and still lacks many features.

## Installation

1. Run `python build.py` in project directory. `io_scene_godot.zip` file will be created.
2. Launch Blender and open `File > User Preferences`.
    - (**Ctrl+Atl+U**) under Linux
    - (**Cmd+,**) under OSX
3. Click on `Install from File...` and upload the above zip file.
4. Search for "*godot*" in Add-ons section and enable the plugin called "*Godot Engine Exporter* ".
5. Enjoy hassle-free export.

If you find bugs or want to suggest improvements, please open an issue on the
upstream [GitHub repository](https://github.com/godotengine/blender-exporter).

## License

This Godot exporter is distributed under the terms of the GNU General
Public License, version 2 or later. See the [LICENSE.txt](/LICENSE.txt) file
for details.
