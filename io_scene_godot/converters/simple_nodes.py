"""
Any exporters that can be written in a single function can go in here.
Anything more complex should go in it's own file
"""

import math
import logging
import mathutils
from ..structures import NodeTemplate, fix_directional_transform


def export_empty_node(escn_file, export_settings, node, parent_gd_node):
    """Converts an empty (or any unknown node) into a spatial"""
    if "EMPTY" not in export_settings['object_types']:
        return parent_gd_node
    empty_node = NodeTemplate(node.name, "Spatial", parent_gd_node)
    empty_node['transform'] = node.matrix_local
    escn_file.add_node(empty_node)

    return empty_node


def export_camera_node(escn_file, export_settings, node, parent_gd_node):
    """Exports a camera"""
    if (node.data is None or node.hide_render or
            "CAMERA" not in export_settings['object_types']):
        return parent_gd_node

    cam_node = NodeTemplate(node.name, "Camera", parent_gd_node)
    camera = node.data

    cam_node['far'] = camera.clip_end
    cam_node['near'] = camera.clip_start

    if camera.type == "PERSP":
        cam_node['projection'] = 0
        cam_node['fov'] = math.degrees(camera.angle)
    else:
        cam_node['projection'] = 1
        cam_node['size'] = camera.ortho_scale

    cam_node['transform'] = fix_directional_transform(node.matrix_local)
    escn_file.add_node(cam_node)

    return cam_node


def export_lamp_node(escn_file, export_settings, node, parent_gd_node):
    """Exports lights - well, the ones it knows about. Other light types
    just throw a warning"""
    if (node.data is None or node.hide_render or
            "LAMP" not in export_settings['object_types']):
        return parent_gd_node

    light = node.data

    if light.type == "POINT":
        light_node = NodeTemplate(node.name, "OmniLight", parent_gd_node)
        light_node['omni_range'] = light.distance
        light_node['shadow_enabled'] = light.shadow_method != "NOSHADOW"

        if not light.use_sphere:
            logging.warning(
                "Ranged light without sphere enabled: %s", node.name
            )

    elif light.type == "SPOT":
        light_node = NodeTemplate(node.name, "SpotLight", parent_gd_node)
        light_node['spot_range'] = light.distance
        light_node['spot_angle'] = math.degrees(light.spot_size/2)
        light_node['spot_angle_attenuation'] = 0.2/(light.spot_blend + 0.01)
        light_node['shadow_enabled'] = light.shadow_method != "NOSHADOW"

        if not light.use_sphere:
            logging.warning(
                "Ranged light without sphere enabled: %s", node.name
            )

    elif light.type == "SUN":
        light_node = NodeTemplate(node.name, "DirectionalLight",
                                  parent_gd_node)
        light_node['shadow_enabled'] = light.shadow_method != "NOSHADOW"
    else:
        light_node = None
        logging.warning(
            "Unknown light type. Use Point, Spot or Sun: %s", node.name
        )

    if light_node is not None:
        # Properties common to all lights
        light_node['light_color'] = mathutils.Color(light.color)
        light_node['transform'] = fix_directional_transform(node.matrix_local)
        light_node['light_negative'] = light.use_negative
        light_node['light_specular'] = 1.0 if light.use_specular else 0.0
        light_node['light_energy'] = light.energy

        escn_file.add_node(light_node)

    return light_node
