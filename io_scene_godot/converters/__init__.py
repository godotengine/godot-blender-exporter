"""
This file provides the conversion for a single blend object into one or
more godot nodes. All the converters should take as input arguments:
 - The ESCN file (so you can use add_internal_resource() method etc.)
 - The exporter config (so you can see what options the user selected)
 - The node to export
 - The path to the parent node

One-function exporters are stored in simple_nodes. Others (such as meshes)
are stored in individual files.
"""

from .simple_nodes import *
from .mesh import export_mesh_node
from .physics import export_physics_properties


BLENDER_TYPE_TO_EXPORTER = {
    "MESH": export_mesh_node,
    "CAMERA": export_camera_node,
    "LAMP": export_lamp_node,
    "EMPTY": export_empty_node
}
