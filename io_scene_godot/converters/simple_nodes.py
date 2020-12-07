"""
Any exporters that can be written in a single function can go in here.
Anything more complex should go in it's own file
"""

import logging
import math
import mathutils
from ..structures import (
    NodeTemplate, fix_directional_transform, gamma_correct, InternalResource,
    Map, Array
)
from .animation import export_animation_data, AttributeConvertInfo
from .mesh import export_mesh_node


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
        AttributeConvertInfo('color', 'light_color', gamma_correct),
        AttributeConvertInfo('shadow_color', 'shadow_color', gamma_correct),
    ]
    _omni_attr_conv = [
        AttributeConvertInfo(
            'energy', 'light_energy', lambda x: abs(x / 100.0)),
        AttributeConvertInfo('cutoff_distance', 'omni_range', lambda x: x),
    ]
    _spot_attr_conv = [
        AttributeConvertInfo(
            'energy', 'light_energy', lambda x: abs(x / 100.0)),
        AttributeConvertInfo(
            'spot_size', 'spot_angle', lambda x: math.degrees(x/2)
        ),
        AttributeConvertInfo(
            'spot_blend', 'spot_angle_attenuation', lambda x: 0.2/(x + 0.01)
        ),
        AttributeConvertInfo('cutoff_distance', 'spot_range', lambda x: x),
    ]
    _directional_attr_conv = [
        AttributeConvertInfo('energy', 'light_energy', abs),
    ]

    @property
    def attribute_conversion(self):
        """Get a list of quaternary tuple
        (blender_attr, godot_attr, lambda converter, attr type)"""
        if self.get_type() == 'OmniLight':
            return self._light_attr_conv + self._omni_attr_conv
        if self.get_type() == 'SpotLight':
            return self._light_attr_conv + self._spot_attr_conv
        if self.get_type() == 'DirectionalLight':
            return self._light_attr_conv + self._directional_attr_conv
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
            "%s light is not supported. Use Point, Spot or Sun", node.name
        )

    if light_node is not None:
        for item in light_node.attribute_conversion:
            bl_attr, gd_attr, converter = item
            light_node[gd_attr] = converter(getattr(light, bl_attr))

        # Properties common to all lights
        # These cannot be set via AttributeConvertInfo as it will not handle
        # animations correctly
        light_node['transform'] = fix_directional_transform(node.matrix_local)
        light_node['light_negative'] = light.energy < 0
        light_node['shadow_enabled'] = (
            light.use_shadow and light.cycles.cast_shadow)

        escn_file.add_node(light_node)

    export_animation_data(escn_file, export_settings,
                          light_node, node.data, 'light')

    return light_node

def _export_spline(escn_file, spline, name):
    points = Array("PoolVector3Array(")
    tilts = Array("PoolRealArray(")
    axis_correct = mathutils.Matrix((
        (1, 0, 0),  # X in blender is  X in Godot
        (0, 0, -1),  # Y in blender is -Z in Godot
        (0, 1, 0),  # Z in blender is  Y in Godot
    )).normalized()

    src_points = spline.bezier_points
    if spline.use_cyclic_u:
        # Godot fakes a closed path by adding the start point at the end
        # https://github.com/godotengine/godot-proposals/issues/527
        src_points = [*src_points, src_points[0]]

    for point in src_points:
        # blender handles are absolute
        # godot handles are relative to the control point
        points.extend((point.handle_left - point.co) @ axis_correct)
        points.extend((point.handle_right - point.co) @ axis_correct)
        points.extend(point.co @ axis_correct)
        tilts.append(point.tilt)

    data = Map()
    data["points"] = points
    data["tilts"] = tilts

    curve_resource = InternalResource("Curve3D", name)
    curve_resource["_data"] = data
    curve_id = escn_file.get_internal_resource(spline)
    if curve_id is None:
        return escn_file.add_internal_resource(curve_resource, spline)
    return escn_file.get_internal_resource(spline)

def export_curve_node(escn_file, export_settings, node, parent_gd_node):
    """Export a curve to a Path node, with a child mesh."""
    splines = node.data.splines

    path_node = NodeTemplate(node.name, "Path", parent_gd_node)
    path_node["transform"] = node.matrix_local
    escn_file.add_node(path_node)

    for spline in splines:
        # https://docs.blender.org/manual/en/latest/modeling/curves/editing/curve.html#set-spline-type
        # Godot only supports bezier, and blender cannot convert losslessly
        if spline.type == "BEZIER":
            curve_id = _export_spline(escn_file, splines[0], node.data.name)
            if spline == splines.active:
                path_node["curve"] = "SubResource({})".format(curve_id)

        # Create child MeshInstance renders the bevel for any curve type
        mesh_node = export_mesh_node(escn_file, export_settings, node, path_node)
        # The transform is already set on the path, don't duplicate it
        mesh_node["transform"] = mathutils.Matrix.Identity(4)

    return path_node
