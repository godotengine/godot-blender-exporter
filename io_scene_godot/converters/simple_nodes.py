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


def find_shader_node(node_tree, name):
    """Find the shader node from the tree with the given name."""
    for node in node_tree.nodes:
        if node.bl_idname == name:
            return node
    logging.warning("%s node not found", name)
    return None


def node_input(node, name):
    """Get the named input value from the shader node."""
    for inp in node.inputs:
        if inp.name == name:
            return inp.default_value
    logging.warning("%s input not found in %s", name, node.bl_idname)
    return None


class LightNode(NodeTemplate):
    """Base class for godot light node"""
    _light_attr_conv = [
        AttributeConvertInfo(
            'specular_factor', 'light_specular', lambda x: x),
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


def export_light_node(escn_file, export_settings, node, parent_gd_node):
    """Exports lights - well, the ones it knows about. Other light types
    just throw a warning"""
    bl_light_to_gd_light = {
        "POINT": "OmniLight",
        "SPOT": "SpotLight",
        "SUN": "DirectionalLight",
    }

    light = node.data
    if light.type in bl_light_to_gd_light:
        light_node = LightNode(
            node.name, bl_light_to_gd_light[light.type], parent_gd_node)
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
        # These cannot be set via AttributeConvertInfo as it will not handle
        # animations correctly
        light_node['transform'] = fix_directional_transform(node.matrix_local)
        if light.use_nodes:
            emission = find_shader_node(light.node_tree, 'ShaderNodeEmission')
            if emission:
                strength = node_input(emission, 'Strength') or 100
                color = node_input(emission, 'Color') or [1, 1, 1]
                # we don't have an easy way to get these in cycles
                # don't set them and let godot use its defaults
                del light_node['light_specular']
                del light_node['shadow_color']
                # strength=100 in cycles is roughly equivalent to energy=1
                light_node['light_energy'] = abs(strength / 100.0)
                light_node['light_color'] = gamma_correct(color)
                light_node['shadow_enabled'] = light.cycles.cast_shadow
                light_node['light_negative'] = strength < 0
        else:
            light_node['shadow_enabled'] = light.use_shadow

        escn_file.add_node(light_node)

    export_animation_data(escn_file, export_settings,
                          light_node, node.data, 'light')

    return light_node
