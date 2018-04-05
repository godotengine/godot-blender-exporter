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
import logging
import bpy

from . import structures
from . import converters

logging.basicConfig(level=logging.INFO, format="[%(levelname)s]: %(message)s")


def find_godot_project_dir(export_path):
    """Finds the project.godot file assuming that the export path
    is inside a project (looks for a project.godot file)"""
    project_dir = export_path

    while not os.path.isfile(os.path.join(project_dir, "project.godot")):
        project_dir = os.path.split(project_dir)[0]
        if project_dir == "/" or len(project_dir) < 3:
            logging.error("Unable to find godot project file")
            return None
    logging.info("Found godot project directory at %s", project_dir)
    return project_dir


class GodotExporter:
    """Handles picking what nodes to export and kicks off the export process"""

    def export_node(self, node, parent_path):
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

        # Perform the export
        parent_path = exporter(self.escn_file, self.config, node, parent_path)

        for child in node.children:
            self.export_node(child, parent_path)

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
        self.escn_file.add_node(structures.FileEntry(
            "node", collections.OrderedDict((
                ("type", "Spatial"),
                ("name", self.scene.name)
            ))
        ))
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
                self.export_node(obj, ".")

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
        self.config["project_path"] = find_godot_project_dir(path)
        self.valid_nodes = []

        self.escn_file = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


def save(operator, context, filepath="", **kwargs):
    """Begin the export"""
    with GodotExporter(filepath, kwargs, operator) as exp:
        exp.export()

    return {"FINISHED"}
