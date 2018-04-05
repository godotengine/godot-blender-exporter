"""
This file provides the conversion for a single blend object into one or
more godot nodes. All the converters should take as input arguments:
 - The ESCN file (so you can use add_internal_resource() method etc.)
 - The exporter config (so you can see what options the user selected)
 - The blender node to export
 - The parent Godot scene node of the node being processed

All converters that convert nodes should return the node itself. All
converters that convert resources should return the resource ID. Additional,
converters for resources should have internal protection against importing
twice

One-function exporters are stored in simple_nodes. Others (such as meshes)
are stored in individual files.
"""

from .simple_nodes import *  # pylint: disable=wildcard-import
from .mesh import export_mesh_node
from .physics import export_physics_properties


BLENDER_TYPE_TO_EXPORTER = {
    "MESH": export_mesh_node,
    "CAMERA": export_camera_node,
    "LAMP": export_lamp_node,
    "EMPTY": export_empty_node
}
