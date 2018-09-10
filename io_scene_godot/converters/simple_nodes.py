"""
Any exporters that can be written in a single function can go in here.
Anything more complex should go in it's own file
"""

import math
import logging
from ..structures import (
    NodeTemplate, fix_directional_transform, gamma_correct
)
from .animation import export_animation_data, AttributeConvertInfo


def export_empty_node(escn_file, export_settings, node, parent_gd_node):
    """Converts an empty (or any unknown node) into a spatial"""
    if "EMPTY" not in export_settings['object_types']:
        return parent_gd_node
    empty_node = NodeTemplate(node.name, "Spatial", parent_gd_node)
    empty_node['transform'] = node.matrix_local
    escn_file.add_node(empty_node)

    return empty_node


class CameraNode(NodeTemplate):
    """Camera node in godot scene"""
    _cam_attr_conv = [
        # blender attr, godot attr, converter lambda, type
        AttributeConvertInfo('clip_end', 'far', lambda x: x),
        AttributeConvertInfo('clip_start', 'near', lambda x: x),
        AttributeConvertInfo('ortho_scale', 'size', lambda x: x),
    ]

    def __init__(self, name, parent):
        super().__init__(name, "Camera", parent)

    @property
    def attribute_conversion(self):
        """Get a list of quaternary tuple
        (blender_attr, godot_attr, lambda converter, attr type)"""
        return self._cam_attr_conv


def export_camera_node(escn_file, export_settings, node, parent_gd_node):
    """Exports a camera"""
    if (node.data is None or node.hide_render or
            "CAMERA" not in export_settings['object_types']):
        return parent_gd_node

    cam_node = CameraNode(node.name, parent_gd_node)
    camera = node.data

    for item in cam_node.attribute_conversion:
        blender_attr, gd_attr, converter = item
        cam_node[gd_attr] = converter(getattr(camera, blender_attr))

    if camera.type == "PERSP":
        cam_node['projection'] = 0
    else:
        cam_node['projection'] = 1

    # `fov` does not go into `attribute_conversion`, because it can not
    # be animated
    cam_node['fov'] = math.degrees(camera.angle)

    cam_node['transform'] = fix_directional_transform(node.matrix_local)
    escn_file.add_node(cam_node)

    export_animation_data(escn_file, export_settings,
                          cam_node, node.data, 'camera')

    return cam_node


class LightNode(NodeTemplate):
    """Base class for godot light node"""
    _light_attr_conv = [
        AttributeConvertInfo(
            'use_specular', 'light_specular', lambda x: 1.0 if x else 0.0
        ),
        AttributeConvertInfo('energy', 'light_energy', lambda x: x),
        AttributeConvertInfo('color', 'light_color', gamma_correct),
        AttributeConvertInfo('shadow_color', 'shadow_color', gamma_correct),
    ]
    _omni_attr_conv = [
        AttributeConvertInfo('distance', 'omni_range', lambda x: x),
    ]
    _spot_attr_conv = [
        AttributeConvertInfo(
            'spot_size', 'spot_angle', lambda x: math.degrees(x/2)
        ),
        AttributeConvertInfo(
            'spot_blend', 'spot_angle_attenuation', lambda x: 0.2/(x + 0.01)
        ),
        AttributeConvertInfo('distance', 'spot_range', lambda x: x),
    ]

    @property
    def attribute_conversion(self):
        """Get a list of quaternary tuple
        (blender_attr, godot_attr, lambda converter, attr type)"""
        if self.get_type() == 'OmniLight':
            return self._light_attr_conv + self._omni_attr_conv
        if self.get_type() == 'SpotLight':
            return self._light_attr_conv + self._spot_attr_conv
        return self._light_attr_conv


def export_lamp_node(escn_file, export_settings, node, parent_gd_node):
    """Exports lights - well, the ones it knows about. Other light types
    just throw a warning"""
    if (node.data is None or node.hide_render or
            "LAMP" not in export_settings['object_types']):
        return parent_gd_node

    light = node.data

    if light.type == "POINT":
        light_node = LightNode(node.name, 'OmniLight', parent_gd_node)

        if not light.use_sphere:
            logging.warning(
                "Ranged light without sphere enabled: %s", node.name
            )

    elif light.type == "SPOT":
        light_node = LightNode(node.name, 'SpotLight', parent_gd_node)
        if not light.use_sphere:
            logging.warning(
                "Ranged light without sphere enabled: %s", node.name
            )

    elif light.type == "SUN":
        light_node = LightNode(node.name, 'DirectionalLight', parent_gd_node)
    else:
        light_node = None
        logging.warning(
            "Unknown light type. Use Point, Spot or Sun: %s", node.name
        )

    if light_node is not None:
        for item in light_node.attribute_conversion:
            bl_attr, gd_attr, converter = item
            light_node[gd_attr] = converter(getattr(light, bl_attr))

        # Properties common to all lights
        light_node['transform'] = fix_directional_transform(node.matrix_local)
        light_node['shadow_enabled'] = light.shadow_method != "NOSHADOW"
        light_node['light_negative'] = light.use_negative

        escn_file.add_node(light_node)

    export_animation_data(escn_file, export_settings,
                          light_node, node.data, 'light')

    return light_node
