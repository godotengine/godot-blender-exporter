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
from .armature import export_armature_node, export_bone_attachment
from .animation import export_animation_data
from .multimesh import export_multimesh_node, has_particle

# TODO: What about Empties which refer to group instances? (in 2.8 Collection
# Instances)
BLENDER_TYPE_TO_EXPORTER = {
    "MESH": export_mesh_node,
    "ARMATURE": export_armature_node,
    "CAMERA": export_camera_node,
    "LIGHT": export_light_node,
    "EMPTY": export_empty_node,
    "CURVE": export_mesh_node,
    "SURFACE": export_mesh_node,
    "META": export_mesh_node,
    "FONT": export_mesh_node
}

BONE_ATTACHMENT_EXPORTER = export_bone_attachment

ANIMATION_DATA_EXPORTER = export_animation_data

MULTIMESH_EXPORTER = export_multimesh_node