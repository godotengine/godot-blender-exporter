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

import logging
import bpy

from . import structures
from . import converters

logging.basicConfig(level=logging.INFO, format="[%(levelname)s]: %(message)s")



class GodotExporter:
    def export_node(self, node, parent_path):
        """Recursively export a node. It calls the export_node function on
        all of the nodes children. If you have heirarchies more than 1000 nodes
        deep, this will fail with a recursion error"""
        if node not in self.valid_nodes:
            return
        logging.info("Exporting Blender Object: %s", node.name)

        prev_node = bpy.context.scene.objects.active
        bpy.context.scene.objects.active = node

        node_name = node.name

        if node.type in converters.BLENDER_TYPE_TO_EXPORTER:
            exporter = converters.BLENDER_TYPE_TO_EXPORTER[node.type]
        else:
            logging.warning("Unknown object type. Treating as empty: %s", node.name)
            exporter = converters.BLENDER_TYPE_TO_EXPORTER["EMPTY"]

        if node.rigid_body is not None:
            # Physics export is unique in that it requires creation of a new
            # node at a higher level than the mesh node. If more objects
            # do this, a new solution will need to be found.
            parent_path = converters.export_physics_properties(
                self.escn_file, self.config, node, parent_path
            )

        exporter(self.escn_file, self.config, node, parent_path)

        if parent_path == ".":
            parent_path = node_name
        else:
            parent_path = parent_path+"/"+node_name

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
        self.escn_file.add_node(
            structures.SectionHeading("node", type="Spatial", name=self.scene.name)
        )
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
        self.escn_file = structures.ESCNFile(
            structures.SectionHeading("gd_scene", load_steps=1, format=2)
        )

        self.export_scene()

        with open(self.path, 'w') as out_file:
            out_file.write(self.escn_file.to_string())

        return True

    def __init__(self, path, kwargs, operator):
        self.path = path
        self.operator = operator
        self.scene = bpy.context.scene
        self.config = kwargs
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
