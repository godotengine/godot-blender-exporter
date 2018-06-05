"""Export animation into Godot scene tree"""
import collections
import re
import copy
import bpy
import mathutils
from . import armature
from ..structures import (NodeTemplate, NodePath,
                          InternalResource, Array, fix_matrix)

LINEAR_INTERPOLATION = 1


class Track:
    """Animation track, with a type track and a frame list
    the element in frame list is not strictly typed, for example,
    a transform track would have frame with type mathutils.Matrix()"""
    def __init__(self, track_type, track_path, frame_begin, frame_list):
        self.type = track_type
        self.path = track_path
        self.frame_begin = frame_begin
        self.frames = frame_list

    def last_frame(self):
        """The number of last frame"""
        return self.frame_begin + len(self.frames)


class AnimationResource(InternalResource):
    """Internal resource with type Animation"""
    def __init__(self):
        super().__init__('Animation')
        self['step'] = 0.1
        self['length'] = 0
        self.track_count = 0

    def add_track(self, track):
        """add a track to animation resource"""
        track_length = track.last_frame() / bpy.context.scene.render.fps
        if track_length > self['length']:
            self['length'] = track_length

        track_id_str = 'tracks/{}'.format(self.track_count)
        self.track_count += 1

        self[track_id_str + '/type'] = '"{}"'.format(track.type)
        if track.type == 'transform':
            self[track_id_str + '/path'] = track.path
            self[track_id_str + '/interp'] = LINEAR_INTERPOLATION
            self[track_id_str + '/keys'] = transform_frames_to_keys(
                track.frame_begin, track.frames
            )


class AnimationPlayer(NodeTemplate):
    """Godot scene node with type AnimationPlayer"""
    def __init__(self, name, parent):
        super().__init__(name, "AnimationPlayer", parent)
        # use parent node as the animation root node
        self['root_node'] = NodePath(self.get_path(), self.parent.get_path())
        # blender actions not in nla_tracks are treated as default
        self.default_animation = None

    def add_default_animation_resource(self, escn_file, action):
        """Default animation resource may hold animation from children
        objects"""
        self.default_animation = self.create_animation_resource(
            escn_file, action)

    def create_animation_resource(self, escn_file, action):
        """Create a new animation resource and add it into escn file"""
        new_anim_resource = AnimationResource()
        resource_id = escn_file.add_internal_resource(
            new_anim_resource, action)
        self['anims/{}'.format(action.name)] = (
            "SubResource({})".format(resource_id))

        return new_anim_resource


def transform_frames_to_keys(first_frame, frame_list):
    """Convert a list of transform matrix to the keyframes
    of an animation track"""
    array = Array(prefix='[', suffix=']')
    for index, mat in enumerate(frame_list):
        if index > 0 and frame_list[index] == frame_list[index - 1]:
            # do not export same keyframe
            continue

        frame = first_frame + index
        array.append(frame / bpy.context.scene.render.fps)

        # transition default 1.0
        array.append(1.0)

        # convert from z-up to y-up
        transform_mat = fix_matrix(mat)
        location = transform_mat.to_translation()
        quaternion = transform_mat.to_quaternion()
        scale = transform_mat.to_scale()

        array.append(location.x)
        array.append(location.y)
        array.append(location.z)
        array.append(quaternion.x)
        array.append(quaternion.y)
        array.append(quaternion.z)
        array.append(quaternion.w)
        array.append(scale.x)
        array.append(scale.y)
        array.append(scale.z)

    return array


def get_animation_player(escn_file, export_settings, godot_node):
    """Get a AnimationPlayer node, if not existed, a new
    one will be created and returned"""
    animation_player = None

    # looking for a existed AnimationPlayer
    if not export_settings['use_seperate_animation_player']:
        node_ptr = godot_node
        while node_ptr is not None:
            for child in node_ptr.children:
                if child.get_type() == 'AnimationPlayer':
                    animation_player = child
                    break
            if animation_player is not None:
                break
            node_ptr = node_ptr.parent

    if animation_player is None:
        animation_player = AnimationPlayer(
            godot_node.get_name() + 'Animation',
            godot_node.parent,
        )

        escn_file.add_node(animation_player)

    return animation_player


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


def get_frame_range(action):
    """Return the frame range of the action"""
    return int(action.frame_range[0]), int(action.frame_range[1])


def export_transform_action(godot_node, animation_player,
                            blender_object, action, animation_resource):
    """Export a action with bone and object transform"""

    class TransformFrame:
        """A data structure hold transform values of an animation key,
        it is used as an intermedia data structure, being updated during
        parsing the fcurve data and finally being converted to a transform
        matrix, notice itself uses location, scale, rotation not matrix"""
        ATTRIBUTES = {
            'location', 'scale', 'rotation_quaternion', 'rotation_euler'}

        def __init__(self, default_transform, rotation_mode):
            self.location = default_transform.to_translation()
            # fixme: lose negative scale
            self.scale = default_transform.to_scale()

            # quaternion and euler fcurves may both exist in fcurves
            self.rotation_mode = rotation_mode
            self.rotation_quaternion = default_transform.to_quaternion()
            if rotation_mode == 'QUATERNION':
                self.rotation_euler = default_transform.to_euler()
            else:
                self.rotation_euler = default_transform.to_euler(
                    rotation_mode
                )

        def update(self, attribute, array_index, value):
            """Use fcurve data to update the frame"""
            if attribute == 'location':
                self.location[array_index] = value
            elif attribute == 'scale':
                self.scale[array_index] = value
            elif attribute == 'rotation_quaternion':
                self.rotation_quaternion[array_index] = value
            elif attribute == 'rotation_euler':
                self.rotation_euler[array_index] = value

        def to_matrix(self):
            """Convert location, scale, rotation to a transform matrix"""
            if self.rotation_mode == 'QUATERNION':
                rot_mat = self.rotation_quaternion.to_matrix().to_4x4()
            else:
                rot_mat = self.rotation_euler.to_matrix().to_4x4()
            loc_mat = mathutils.Matrix.Translation(self.location)
            sca_mat = mathutils.Matrix.Scale(1, 4, self.scale)
            return loc_mat * rot_mat * sca_mat

    first_frame, last_frame = get_frame_range(action)

    # if no skeleton node exist, it will be None
    skeleton_node = armature.find_skeletion_node(godot_node)

    transform_frames_map = collections.OrderedDict()
    for fcurve in action.fcurves:
        # fcurve data are seperated into different channels,
        # for example a transform action would have several fcurves
        # (location.x, location.y, rotation.x ...), so here fcurves
        # are aggregated to object while being evaluted
        object_path, attribute = split_fcurve_data_path(fcurve.data_path)

        if object_path not in transform_frames_map:
            if attribute in TransformFrame.ATTRIBUTES:

                default_frame = None

                if object_path.startswith('pose'):
                    bone_name = blender_path_to_bone_name(object_path)

                    # if the correspond bone of this track not exported, skip
                    if (skeleton_node is None or
                            skeleton_node.find_bone_id(bone_name) == -1):
                        continue

                    pose_bone = blender_object.pose.bones[
                        blender_object.pose.bones.find(bone_name)
                    ]
                    default_frame = TransformFrame(
                        pose_bone.matrix_basis,
                        pose_bone.rotation_mode
                    )
                else:
                    # the fcurve location is matrix_basis.to_translation()
                    default_frame = TransformFrame(
                        blender_object.matrix_basis,
                        blender_object.rotation_mode
                    )

                transform_frames_map[object_path] = [
                    copy.deepcopy(default_frame)
                    for _ in range(last_frame - first_frame + 1)
                ]

        if attribute in TransformFrame.ATTRIBUTES:

            for frame in range(first_frame, last_frame + 1):
                transform_frames_map[
                    object_path][frame - first_frame].update(
                        attribute,
                        fcurve.array_index,
                        fcurve.evaluate(frame)
                    )

    for object_path, frame_list in transform_frames_map.items():
        if object_path == '':
            # object_path equals '' represents node itself

            # convert matrix_basis to matrix_local(parent space transform)
            normalized_frame_list = [
                blender_object.matrix_parent_inverse *
                x.to_matrix() for x in frame_list]

            track_path = NodePath(
                animation_player.parent.get_path(),
                godot_node.get_path()
            )

        elif object_path.startswith('pose'):
            track_path = NodePath(
                animation_player.parent.get_path(),
                godot_node.get_path(),
                blender_path_to_bone_name(object_path)
            )

            normalized_frame_list = [x.to_matrix() for x in frame_list]

        animation_resource.add_track(
            Track(
                'transform',
                track_path,
                first_frame,
                normalized_frame_list
            )
        )

# ----------------------------------------------


ACTION_EXPORTER_MAP = {
    'transform': export_transform_action,
}


def export_animation_data(escn_file, export_settings, godot_node,
                          blender_object, action_type):
    """Export the action and nla_tracks in blender_object.animation_data,
    it will further call the action exporting function in AnimationDataExporter
    given by `func_name`"""
    animation_player = get_animation_player(
        escn_file, export_settings, godot_node)

    exporter_func = ACTION_EXPORTER_MAP[action_type]

    exported_actions = set()

    action = blender_object.animation_data.action
    if action is not None:
        if animation_player.default_animation is None:
            # choose a arbitrary action as the hash key for animation resource
            animation_player.add_default_animation_resource(
                escn_file, action)

        exported_actions.add(action)

        exporter_func(godot_node, animation_player, blender_object,
                      action, animation_player.default_animation)

    # export actions in nla_tracks, each exported to seperate
    # animation resources
    for nla_track in blender_object.animation_data.nla_tracks:
        for nla_strip in nla_track.strips:
            # make sure no duplicate action exported
            if nla_strip.action not in exported_actions:
                exported_actions.add(nla_strip.action)
                anim_resource = animation_player.create_animation_resource(
                    escn_file, nla_strip.action
                )
                exporter_func(godot_node, animation_player, blender_object,
                              nla_strip.action, anim_resource)
