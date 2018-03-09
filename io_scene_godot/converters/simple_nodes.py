"""
Any exporters that can be written in a single function can go in here.
Anything more complex should go in it's own file
"""

import math
import logging
import mathutils
from ..structures import NodeTemplate

# Used to correct spotlights and cameras, which in blender are Z-forwards and
# in Godot are Y-forwards
AXIS_CORRECT = mathutils.Matrix.Rotation(math.radians(-90), 4, 'X')


def export_empty_node(escn_file, export_settings, node, parent_path):
    """Converts an empty (or any unknown node) into a spatial"""
    empty_node = NodeTemplate(node.name, "Spatial", parent_path)
    empty_node.transform = node.matrix_local
    escn_file.add_node(empty_node)


def export_camera_node(escn_file, export_settings, node, parent_path):
    """Exports a camera"""
    if node.data is None:
        return

    cam_node = NodeTemplate(node.name, "Camera", parent_path)
    camera = node.data

    cam_node.far = camera.clip_end
    cam_node.near = camera.clip_start

    if camera.type == "PERSP":
        cam_node.projection = 0
        cam_node.fov = math.degrees(camera.angle)
    else:
        cam_node.projection = 1
        cam_node.size = camera.ortho_scale * 0.5

    cam_node.transform = node.matrix_local * AXIS_CORRECT
    escn_file.add_node(cam_node)


def export_lamp_node(escn_file, export_settings, node, parent_path):
    """Exports lights - well, the ones it knows about. Other light types
    just throw a warning"""
    if node.data is None:
        return

    light = node.data

    if light.type == "POINT":
        light_node = NodeTemplate(node.name, "OmniLight", parent_path)
        light_node.omni_range = light.distance
        light_node.shadow_enabled = light.shadow_method != "NOSHADOW"

        if not light.use_sphere:
            logging.warning("Ranged light without sphere enabled: %s", node.name)

    elif light.type == "SPOT":
        light_node = NodeTemplate(node.name, "SpotLight", parent_path)
        light_node.spot_range = light.distance
        light_node.spot_angle = math.degrees(light.spot_size/2)
        light_node.spot_angle_attenuation = 0.2/(light.spot_blend + 0.01)
        light_node.shadow_enabled = light.shadow_method != "NOSHADOW"

        if not light.use_sphere:
            logging.warning("Ranged light without sphere enabled: %s", node.name)

    elif light.type == "SUN":
        light_node = NodeTemplate(node.name, "DirectionalLight", parent_path)
        light_node.shadow_enabled = light.shadow_method != "NOSHADOW"
    else:
        light_node = None
        logging.warning("Unknown light type. Use Point, Spot or Sun: %s", node.name)

    if light_node is not None:
        # Properties common to all lights
        light_node.light_color = mathutils.Color(light.color)
        light_node.transform = node.matrix_local * AXIS_CORRECT
        light_node.light_negative = light.use_negative
        light_node.light_specular = 1.0 if light.use_specular else 0.0
        light_node.light_energy = light.energy

        escn_file.add_node(light_node)
