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

# Script copyright (C) Juan Linietsky
# Contact Info: juan@godotengine.org

"""
This script is an exporter to Godot Engine

http://www.godotengine.org
"""

import os
import collections
import functools
import logging
import math
import bpy
import mathutils

from . import structures
from . import converters

logging.basicConfig(level=logging.INFO, format="[%(levelname)s]: %(message)s")


@functools.lru_cache(maxsize=1)  # Cache it so we don't search lots of times
def find_godot_project_dir(export_path):
    """Finds the project.godot file assuming that the export path
    is inside a project (looks for a project.godot file)"""
    project_dir = export_path

    # Search up until we get to the top, which is "/" in *nix.
    # Standard Windows ends up as, e.g., "C:\", and independent of what else is
    # in the world, we can at least watch for repeats, because that's bad.
    last = None
    while not os.path.isfile(os.path.join(project_dir, "project.godot")):
        project_dir = os.path.split(project_dir)[0]
        if project_dir == "/" or project_dir == last:
            raise structures.ValidationError(
                "Unable to find godot project file"
            )
        last = project_dir
    logging.info("Found godot project directory at %s", project_dir)
    return project_dir


class ExporterLogHandler(logging.Handler):
    """Custom handler for exporter, would report logging message
    to GUI"""

    def __init__(self, operator):
        super().__init__()
        self.setLevel(logging.WARNING)
        self.setFormatter(logging.Formatter("%(message)s"))

        self.blender_op = operator

    def emit(self, record):
        if record.levelno == logging.WARNING:
            self.blender_op.report({'WARNING'}, record.message)
        else:
            self.blender_op.report({'ERROR'}, record.message)


class GodotExporter:
    """Handles picking what nodes to export and kicks off the export process"""

    def export_node(self, node, parent_gd_node):
        """Recursively export a node. It calls the export_node function on
        all of the nodes children. If you have heirarchies more than 1000 nodes
        deep, this will fail with a recursion error"""
        if node not in self.valid_nodes:
            return
        logging.info("Exporting Blender Object: %s", node.name)

        prev_node = bpy.context.scene.objects.active
        bpy.context.scene.objects.active = node

        # Figure out what function will perform the export of this object
        if node.type in converters.BLENDER_TYPE_TO_EXPORTER:
            exporter = converters.BLENDER_TYPE_TO_EXPORTER[node.type]
        else:
            logging.warning(
                "Unknown object type. Treating as empty: %s", node.name
            )
            exporter = converters.BLENDER_TYPE_TO_EXPORTER["EMPTY"]

        is_bone_attachment = False
        if ("ARMATURE" in self.config['object_types'] and
                node.parent and node.parent_bone != ''):
            is_bone_attachment = True
            parent_gd_node = converters.BONE_ATTACHMENT_EXPORTER(
                self.escn_file,
                node,
                parent_gd_node
            )

        # Perform the export, note that `exported_node.paren`t not
        # always the same as `parent_gd_node`, as sometimes, one
        # blender node exported as two parented node
        exported_node = exporter(self.escn_file, self.config, node,
                                 parent_gd_node)

        if is_bone_attachment:
            for child in parent_gd_node.children:
                child['transform'] = structures.fix_bone_attachment_transform(
                    node, child['transform']
                )

        # CollisionShape node has different direction in blender
        # and godot, so it has a -90 rotation around X axis,
        # here rotate its children back
        if (exported_node.parent is not None and
                exported_node.parent.get_type() == 'CollisionShape'):
            exported_node['transform'] = (
                mathutils.Matrix.Rotation(math.radians(90), 4, 'X') *
                exported_node['transform'])

        # if the blender node is exported and it has animation data
        if exported_node != parent_gd_node:
            converters.ANIMATION_DATA_EXPORTER(
                self.escn_file,
                self.config,
                exported_node,
                node,
                "transform"
            )

        for child in node.children:
            self.export_node(child, exported_node)

        bpy.context.scene.objects.active = prev_node

    def should_export_node(self, node):
        """Checks if a node should be exported:"""
        if node.type not in self.config["object_types"]:
            return False

        if self.config["use_active_layers"]:
            valid = False
            for i in range(20):
                if node.layers[i] and self.scene.layers[i]:
                    valid = True
                    break
            if not valid:
                return False

        if self.config["use_export_selected"] and not node.select:
            return False

        return True

    def export_scene(self):
        """Decide what objects to export, and export them!"""
        # Scene root
        root_gd_node = structures.NodeTemplate(
            self.scene.name,
            "Spatial",
            None
        )
        self.escn_file.add_node(root_gd_node)
        logging.info("Exporting scene: %s", self.scene.name)

        # Decide what objects to export
        for obj in self.scene.objects:
            if obj in self.valid_nodes:
                continue
            if self.should_export_node(obj):
                # Ensure all parents are also going to be exported
                node = obj
                while node is not None:
                    if node not in self.valid_nodes:
                        self.valid_nodes.append(node)
                    node = node.parent

        logging.info("Exporting %d objects", len(self.valid_nodes))

        for obj in self.scene.objects:
            if obj in self.valid_nodes and obj.parent is None:
                self.export_node(obj, root_gd_node)

    def load_supported_features(self):
        """According to `project.godot`, determine all new feature supported
        by that godot version"""
        project_dir = ""
        try:
            project_dir = self.config["project_path_func"]()
        except structures.ValidationError:
            project_dir = False
            logging.warning(
                "Not export to Godot project dir, disable all beta features.")

        # minimal supported version
        conf_versiton = 3
        if project_dir:
            project_file_path = os.path.join(project_dir, "project.godot")
            with open(project_file_path, "r") as proj_f:
                for line in proj_f:
                    if not line.startswith("config_version"):
                        continue

                    _, version_str = tuple(line.split("="))
                    conf_versiton = int(version_str)
                    break

        if conf_versiton < 2:
            logging.error(
                "Godot version smaller than 3.0, not supported by this addon")

        if conf_versiton >= 4:
            # godot >=3.1
            self.config["feature_bezier_track"] = True

    def export(self):
        """Begin the export"""
        self.escn_file = structures.ESCNFile(structures.FileEntry(
            "gd_scene",
            collections.OrderedDict((
                ("load_steps", 1),
                ("format", 2)
            ))
        ))

        self.export_scene()
        self.escn_file.fix_paths(self.config)
        with open(self.path, 'w') as out_file:
            out_file.write(self.escn_file.to_string())

        return True

    def __init__(self, path, kwargs, operator):
        self.path = path
        self.operator = operator
        self.scene = bpy.context.scene
        self.config = kwargs
        self.config["path"] = path
        self.config["project_path_func"] = functools.partial(
            find_godot_project_dir, path
        )
        # optional features
        self.config["feature_bezier_track"] = False
        if self.config["use_beta_features"]:
            self.load_supported_features()

        self.valid_nodes = []
        self.escn_file = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


def save(operator, context, filepath="", **kwargs):
    """Begin the export"""
    exporter_log_handler = ExporterLogHandler(operator)
    logging.getLogger().addHandler(exporter_log_handler)

    with GodotExporter(filepath, kwargs, operator) as exp:
        exp.export()

    logging.getLogger().removeHandler(exporter_log_handler)

    return {"FINISHED"}
