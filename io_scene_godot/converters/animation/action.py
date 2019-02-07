"""Convert Blender action into some intermedia class,
then serialized to godot escn"""

import re
import collections
import logging
import math
import copy
import bpy
import mathutils
from .serializer import FloatTrack, TransformTrack, ColorTrack, TransformFrame
from .constraint_baking import check_object_constraint
from ...structures import (NodePath, fix_bone_attachment_location)


# a triple contains information to convert an attribute
# or a fcurve of blender to godot data structures
AttributeConvertInfo = collections.namedtuple(
    'AttributeConvertInfo',
    ['bl_name', 'gd_name', 'converter_function']
)


def get_action_frame_range(action):
    """Return a tuple which is the frame range of action"""
    # in blender `last_frame` is included, here plus one to make it
    # excluded to fit python convention
    return int(action.frame_range[0]), int(action.frame_range[1]) + 1


def get_strip_frame_range(strip):
    """Return a tuple which is the frame of a NlaStrip"""
    return int(strip.frame_start), int(strip.frame_end) + 1


class ActionStrip:
    """Abstract of blender action strip, it may override attributes
    of an action object"""
    def __init__(self, action_or_strip):
        self.action = None
        self.frame_range = (0, 0)

        # blender strip does a linear transformation to its
        # wrapped action frame range, so we need a k, b
        # to store the linear function
        self._fk = 1
        self._fb = 0

        if isinstance(action_or_strip, bpy.types.NlaStrip):
            strip = action_or_strip
            self.action = strip.action
            self._fk = (
                (strip.frame_end - strip.frame_start) /
                (self.action.frame_range[1] - self.action.frame_range[0])
            )
            self._fb = self.action.frame_range[1] - self._fk * strip.frame_end
            self.frame_range = get_strip_frame_range(strip)
        elif isinstance(action_or_strip, bpy.types.Action):
            self.action = action_or_strip
            self.frame_range = get_action_frame_range(self.action)
        else:  # action_or_strip is None
            self.frame_range = (0, 190)

    def evaluate_fcurve(self, fcurve, frame):
        """Evaluate a value of fcurve, DO NOT use fcurve.evalute, as
        action may wrapped inside an action strip"""
        return fcurve.evaluate(self._fk * frame + self._fb)

    def evalute_keyframe(self, keyframe):
        """Evaluate a key frame point and return the point in tuple,
        DO NOT directly use keyframe.co, as action may wrapped in a strip"""
        return int(self._fk * keyframe.co[0] + self._fb), keyframe.co[1]


def blender_path_to_bone_name(blender_object_path):
    """Find the bone name inside a fcurve data path,
    the parameter blender_object_path is part of
    the fcurve.data_path generated through
    split_fcurve_data_path()"""
    return re.search(r'pose.bones\["([^"]+)"\]',
                     blender_object_path).group(1)


def split_fcurve_data_path(data_path):
    """Split fcurve data path into a blender
    object path and an attribute name"""
    path_list = data_path.rsplit('.', 1)

    if len(path_list) == 1:
        return '', path_list[0]
    return path_list[0], path_list[1]


def has_obj_fcurves(action_strip):
    """Check whether action has object transform information"""
    if action_strip.action is None:
        return False
    for fcurve in action_strip.action.fcurves:
        obj_path, attribute = split_fcurve_data_path(fcurve.data_path)
        if obj_path == '':
            return True
    return False


def export_constrained_xform_action(godot_node, animation_player,
                                    blender_object, action_strip,
                                    animation_resource):
    """Export transform animation of any object has constraints,
    it use frame_set to traversal each frame, so it's costly"""
    first_frame, last_frame = action_strip.frame_range

    obj_xform_mats = list()
    pbone_xform_mats = collections.OrderedDict()

    scene = bpy.context.scene
    frame_backup = scene.frame_current

    has_pbone_actions = (godot_node.get_type() == 'Skeleton' and
                         blender_object.pose is not None)
    pbone_parent_map = dict()
    if has_pbone_actions:
        for pbone in blender_object.pose.bones:
            pbone_parent = pbone.parent
            # find parent bone and ensure it is exported in godot node
            while (pbone_parent is not None and
                   godot_node.find_bone_id(pbone_parent.name) == -1):
                pbone_parent = pbone_parent.parent
            pbone_parent_map[pbone.name] = pbone_parent

    for frame in range(first_frame, last_frame):
        scene.frame_set(frame)
        obj_xform_mats.append(blender_object.matrix_local.copy())
        if has_pbone_actions:
            for pbone in blender_object.pose.bones:
                pbone_parent = pbone_parent_map[pbone.name]
                if pbone_parent is None:
                    bone_space_xform = (
                        pbone.bone.matrix_local.inverted_safe() @ pbone.matrix)
                else:
                    bone_space_xform = (
                        godot_node.find_bone_rest(pbone.name).inverted_safe()
                        @ pbone_parent.matrix.inverted_safe()
                        @ pbone.matrix)

                if pbone.name not in pbone_xform_mats:
                    pbone_xform_mats[pbone.name] = list()
                pbone_xform_mats[pbone.name].append(bone_space_xform)
    scene.frame_set(frame_backup)

    if (check_object_constraint(blender_object) or
            has_obj_fcurves(action_strip)):
        xform_frames_list = [
            TransformFrame.factory(mat)
            for mat in obj_xform_mats
        ]

        track_path = NodePath(
            animation_player.parent.get_path(),
            godot_node.get_path()
        )

        if godot_node.parent.get_type() == 'BoneAttachment':
            xform_frames_list = [
                fix_bone_attachment_location(blender_object, x.location)
                for x in xform_frames_list
            ]

        animation_resource.add_obj_xform_track(
            godot_node.get_type(), track_path,
            xform_frames_list, action_strip.frame_range,
            # no need for parent_inverse, as it is directly access matrix_local
        )

    if has_pbone_actions:
        for pbone_name, pbone_xform_mat_list in pbone_xform_mats.items():
            if godot_node.find_bone_id(pbone_name) != -1:
                pbone_xform_frames_list = [
                    TransformFrame.factory(mat)
                    for mat in pbone_xform_mat_list
                ]

                track_path = NodePath(
                    animation_player.parent.get_path(),
                    godot_node.get_path(),
                    godot_node.find_bone_name(pbone_name),
                )

                animation_resource.add_track(
                    TransformTrack(
                        track_path,
                        frames_iter=range(first_frame, last_frame),
                        values_iter=pbone_xform_frames_list,
                    )
                )


def export_transform_action(godot_node, animation_player, blender_object,
                            action_strip, animation_resource):
    """Export a action with bone and object transform"""
    def init_transform_frames_list(object_path, blender_object, godot_node,
                                   first_frame, last_frame):
        """Initialize a list of TransformFrame for an animated object"""
        if object_path.startswith('pose'):
            bone_name = blender_path_to_bone_name(object_path)

            # bone fcurve in a non armature object
            if godot_node.get_type() != 'Skeleton':
                logging.warning(
                    "Skip bone fcurves of Armature object not being exported. "
                    "object '%s'",
                    blender_object.name
                )
                return None

            # if the correspond bone of this track not exported, skip
            if godot_node.find_bone_id(bone_name) == -1:
                return None

            pose_bone = blender_object.pose.bones[
                blender_object.pose.bones.find(bone_name)
            ]

            default_frame = TransformFrame.factory(
                pose_bone.matrix_basis,
                pose_bone.rotation_mode
            )
        else:
            # the fcurve location is matrix_basis.to_translation()
            default_frame = TransformFrame.factory(
                blender_object.matrix_basis,
                blender_object.rotation_mode
            )

        return [
            copy.deepcopy(default_frame)
            for _ in range(last_frame - first_frame)
        ]

    first_frame, last_frame = action_strip.frame_range
    xform_frames_list_map = collections.OrderedDict()
    for fcurve in action_strip.action.fcurves:
        # fcurve data are seperated into different channels,
        # for example a transform action would have several fcurves
        # (location.x, location.y, rotation.x ...), so here fcurves
        # are aggregated to object while being evaluted
        object_path, attribute = split_fcurve_data_path(fcurve.data_path)

        if attribute in TransformFrame.ATTRIBUTES:
            if object_path not in xform_frames_list_map:

                frame_values = init_transform_frames_list(
                    object_path, blender_object,
                    godot_node, first_frame, last_frame
                )

                # unsuccessfully initialize frames, then skip this fcurve
                if not frame_values:
                    continue

                xform_frames_list_map[object_path] = frame_values

            for frame in range(first_frame, last_frame):
                xform_frames_list_map[object_path][frame - first_frame].update(
                    attribute,
                    fcurve.array_index,
                    action_strip.evaluate_fcurve(fcurve, frame)
                )

    for object_path, frame_value_list in xform_frames_list_map.items():
        if object_path == '':
            # empty object_path represents transform of object itself
            track_path = NodePath(
                animation_player.parent.get_path(),
                godot_node.get_path()
            )

            if godot_node.parent.get_type() == 'BoneAttachment':
                frame_value_list = [
                    fix_bone_attachment_location(blender_object, x.location)
                    for x in frame_value_list
                ]

            animation_resource.add_obj_xform_track(
                godot_node.get_type(), track_path,
                frame_value_list, action_strip.frame_range,
                blender_object.matrix_parent_inverse
            )

        elif object_path.startswith('pose'):
            track_path = NodePath(
                animation_player.parent.get_path(),
                godot_node.get_path(),
                godot_node.find_bone_name(
                    blender_path_to_bone_name(object_path)
                ),
            )
            animation_resource.add_track(
                TransformTrack(
                    track_path,
                    frames_iter=range(first_frame, last_frame),
                    values_iter=frame_value_list,
                )
            )


def export_shapekey_action(godot_node, animation_player, blender_object,
                           action_strip, animation_resource):
    """Export shapekey value action"""
    first_frame, last_frame = action_strip.frame_range
    for fcurve in action_strip.action.fcurves:

        object_path, attribute = split_fcurve_data_path(fcurve.data_path)

        if attribute == 'value':
            shapekey_name = re.search(r'key_blocks\["([^"]+)"\]',
                                      object_path).group(1)

            track_path = NodePath(
                animation_player.parent.get_path(),
                godot_node.get_path(),
                "blend_shapes/{}".format(shapekey_name)
            )

            track = FloatTrack(track_path)

            for frame in range(first_frame, last_frame):
                track.add_frame_data(
                    frame,
                    action_strip.evaluate_fcurve(fcurve, frame)
                )

            animation_resource.add_track(track)


def export_light_action(light_node, animation_player, blender_lamp,
                        action_strip, animation_resource):
    """Export light(lamp in Blender) action"""
    # pylint: disable-msg=R0914
    base_node_path = NodePath(
        animation_player.parent.get_path(), light_node.get_path()
    )

    fcurves = action_strip.action.fcurves

    animation_resource.add_attribute_track(
        action_strip,
        fcurves.find('shadow_method'),
        lambda x: x > 0.0,
        base_node_path.new_copy('shadow_enabled'),
    )

    for item in light_node.attribute_conversion:
        bl_attr, gd_attr, converter = item
        if bl_attr not in ('color', 'shadow_color'):
            animation_resource.add_attribute_track(
                action_strip,
                fcurves.find(bl_attr),
                converter,
                base_node_path.new_copy(gd_attr)
            )

    # color tracks is not one-one mapping to fcurve, they
    # need to be treated like transform track
    color_frame_values_map = collections.OrderedDict()

    first_frame, last_frame = action_strip.frame_range
    for fcurve in fcurves:
        _, attribute = split_fcurve_data_path(fcurve.data_path)

        if attribute in ('color', 'shadow_color'):
            if attribute not in color_frame_values_map:
                color_frame_values_map[attribute] = [
                    mathutils.Color()
                    for _ in range(first_frame, last_frame)
                ]
            color_list = color_frame_values_map[attribute]
            for frame in range(first_frame, last_frame):
                color_list[frame - first_frame][fcurve.array_index] = (
                    action_strip.evaluate_fcurve(fcurve, frame)
                )

    for bl_attr, _, converter in light_node.attribute_conversion:
        if (bl_attr in ('color', 'shadow_color') and
                bl_attr in color_frame_values_map):
            color_frame_values_map[bl_attr] = [
                converter(x) for x in color_frame_values_map[bl_attr]
            ]

    for attribute, frame_value_list in color_frame_values_map.items():
        if attribute == 'color':
            track_path = base_node_path.new_copy('light_color')
        else:
            track_path = base_node_path.new_copy('shadow_color')

        animation_resource.add_track(
            ColorTrack(
                track_path,
                frames_iter=range(first_frame, last_frame),
                values_iter=frame_value_list
            )
        )


def export_camera_action(camera_node, animation_player, blender_cam,
                         action_strip, animation_resource):
    """Export camera action"""
    # pylint: disable-msg=R0914
    first_frame, last_frame = action_strip.frame_range
    base_node_path = NodePath(
        animation_player.parent.get_path(), camera_node.get_path()
    )

    fcurves = action_strip.action.fcurves
    for item in camera_node.attribute_conversion:
        bl_attr, gd_attr, converter = item
        animation_resource.add_attribute_track(
            action_strip,
            fcurves.find(bl_attr),
            converter,
            base_node_path.new_copy(gd_attr)
        )

    animation_resource.add_attribute_track(
        action_strip,
        fcurves.find('type'),
        lambda x: 0 if x == 0.0 else 1,
        base_node_path.new_copy('projection'),
    )

    # blender use sensor_width and f_lens to animate fov
    # while godot directly use fov
    fov_animated = False
    focal_len_list = list()
    sensor_size_list = list()

    lens_fcurve = fcurves.find('lens')
    if lens_fcurve is not None:
        fov_animated = True
        for frame in range(first_frame, last_frame):
            focal_len_list.append(
                action_strip.evaluate_fcurve(lens_fcurve, frame)
            )
    sensor_width_fcurve = fcurves.find('sensor_width')
    if sensor_width_fcurve is not None:
        fov_animated = True
        for frame in range(first_frame, last_frame):
            sensor_size_list.append(
                action_strip.evaluate_fcurve(sensor_width_fcurve, frame)
            )

    if fov_animated:
        # export fov track
        if not focal_len_list:
            focal_len_list = [blender_cam.lens
                              for _ in range(first_frame, last_frame)]
        if not sensor_size_list:
            sensor_size_list = [blender_cam.sensor_width
                                for _ in range(first_frame, last_frame)]

        fov_list = list()
        for index, flen in enumerate(focal_len_list):
            fov_list.append(2 * math.degrees(
                math.atan(
                    sensor_size_list[index]/2/flen
                )
            ))

        animation_resource.add_track(
            FloatTrack(
                base_node_path.new_copy('fov'),
                frames_iter=range(first_frame, last_frame),
                values_iter=fov_list
            )
        )
