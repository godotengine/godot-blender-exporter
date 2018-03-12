"""
Export to godot's escn file format - a format that Godot can work with
without significant importing (it's the same as Godot's tscn format).
"""
# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# ##### END GPL LICENSE BLOCK #####

import bpy
from bpy.props import StringProperty, BoolProperty, FloatProperty, EnumProperty

from bpy_extras.io_utils import ExportHelper
bl_info = {  # pylint: disable=invalid-name
    "name": "Godot Engine Exporter",
    "author": "Juan Linietsky",
    "blender": (2, 5, 8),
    "api": 38691,
    "location": "File > Import-Export",
    "description": ("Export Godot Scenes to a format that can be efficiently imported. "),
    "warning": "",
    "wiki_url": ("https://godotengine.org"),
    "tracker_url": "https://github.com/godotengine/blender-exporter",
    "support": "OFFICIAL",
    "category": "Import-Export"
}


class ExportGodot(bpy.types.Operator, ExportHelper):
    """Selection to Godot"""
    bl_idname = "export_godot.escn"
    bl_label = "Export to Godot"
    bl_options = {"PRESET"}

    filename_ext = ".escn"
    filter_glob = StringProperty(default="*.escn", options={"HIDDEN"})

    # List of operator properties, the attributes will be assigned
    # to the class instance from the operator settings before calling
    object_types = EnumProperty(
        name="Object Types",
        options={"ENUM_FLAG"},
        items=(
            ("EMPTY", "Empty", ""),
            ("CAMERA", "Camera", ""),
            ("LAMP", "Lamp", ""),
            # ("ARMATURE", "Armature", ""),
            ("MESH", "Mesh", ""),
            # ("CURVE", "Curve", ""),
        ),
        default={
            "EMPTY",
            "CAMERA",
            "LAMP",
            # "ARMATURE",
            "MESH",
            # "CURVE"
        },
    )

    use_export_selected = BoolProperty(
        name="Selected Objects",
        description="Export only selected objects (and visible in active "
                    "layers if that applies).",
        default=False,
        )
    use_mesh_modifiers = BoolProperty(
        name="Apply Modifiers",
        description="Apply modifiers to mesh objects (on a copy!).",
        default=True,
        )
    use_active_layers = BoolProperty(
        name="Active Layers",
        description="Export only objects on the active layers.",
        default=True,
        )
    material_search_paths = EnumProperty(
        name="Material Search Paths",
        description="Search for existing godot materials with names that match"
                    "the blender material names (ie the file <matname>.tres"
                    "containing a material resource)",
        default="PROJECT_DIR",
        items=(
            (
                "NONE", "None",
                "Don't search for materials"
            ),
            (
                "EXPORT_DIR", "Export Directory",
                "Search the folder where the escn is exported to"
            ),
            (
                "PROJECT_DIR", "Project Directory",
                "Search for materials in the godot project directory"
            ),
        )
    )

    @property
    def check_extension(self):
        """Checks if the file extension is valid. It appears we don't
        really care.... """
        return True

    def execute(self, context):
        """Begin the export"""
        if not self.filepath:
            raise Exception("filepath not set")

        keywords = self.as_keywords(ignore=(
            "axis_forward",
            "axis_up",
            "global_scale",
            "check_existing",
            "filter_glob",
            "xna_validate",
        ))

        from . import export_godot
        return export_godot.save(self, context, **keywords)


def menu_func(self, context):
    """Add to the manu"""
    self.layout.operator(ExportGodot.bl_idname, text="Godot Engine (.escn)")


def register():
    """Add addon to blender"""
    bpy.utils.register_module(__name__)

    bpy.types.INFO_MT_file_export.append(menu_func)


def unregister():
    """Remove addon from blender"""
    bpy.utils.unregister_module(__name__)

    bpy.types.INFO_MT_file_export.remove(menu_func)


if __name__ == "__main__":
    register()
