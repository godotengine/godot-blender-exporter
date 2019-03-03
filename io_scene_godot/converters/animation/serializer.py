"""Export animation into Godot scene tree"""
import collections
import re
import math
import bpy
import mathutils
from ...structures import (NodeTemplate, NodePath, Array, Map,
                           InternalResource)

NEAREST_INTERPOLATION = 0
LINEAR_INTERPOLATION = 1

UPDATE_CONTINUOUS = 0
UPDATE_DISCRETE = 1
UPDATE_TRIGGER = 2
UPDATE_CAPTURE = 3


def strip_adjacent_dup_keyframes(frames, values):
    """Strip removable keyframes to reduce export size"""
    stripped_frames = list()
    stripped_values = list()

    assert len(frames) == len(values)
    length = len(frames)

    stripped_frames.append(frames[0])
    stripped_values.append(values[0])

    duplicated = False
    for index in range(1, length - 1):
        if not duplicated:
            stripped_frames.append(frames[index])
            stripped_values.append(values[index])
            if values[index] == values[index - 1]:
                duplicated = True
        elif values[index] != values[index + 1]:
            duplicated = False
            stripped_frames.append(frames[index])
            stripped_values.append(values[index])

    stripped_frames.append(frames[length - 1])
    stripped_values.append(values[length - 1])

    return stripped_frames, stripped_values


class BezierFrame:
    """A keyframe point in a bezier fcurve"""
    def __init__(self, value, left_handle, right_handle):
        self.value = value
        self.left_handle = left_handle
        self.right_handle = right_handle


class TransformFrame:
    """A data structure hold transform values of an animation key,
    it is used as an intermedia data structure, being updated during
    parsing the fcurve data and finally being converted to a transform
    matrix."""
    ATTRIBUTES = {'location', 'scale', 'rotation_quaternion', 'rotation_euler'}

    def __init__(self, rotation_mode='QUATERNION'):
        self.location = mathutils.Vector((0, 0, 0))
        self.scale = mathutils.Vector((1, 1, 1))

        self.rotation_mode = rotation_mode
        self.rotation_euler = mathutils.Euler((0, 0, 0))
        self.rotation_quaternion = mathutils.Quaternion((1.0, 0.0, 0.0, 0.0))

    def __eq__(self, other):
        """Overrides the default implementation"""
        if isinstance(other, TransformFrame):
            return (self.get_scale() == other.get_scale() and
                    self.get_quaternion() == other.get_quaternion() and
                    self.get_translation() == other.get_translation())
        return False

    @classmethod
    def factory(cls, xform_matrix, rotation_mode='QUATERNION'):
        """Factory method, return an instance created from transform matrix"""
        xform_frame = cls()
        xform_frame.rotation_mode = rotation_mode
        xform_frame.location = xform_matrix.to_translation()
        xform_frame.rotation_quaternion = xform_matrix.to_quaternion()
        # FIXME: lose negative scale
        xform_frame.scale = xform_matrix.to_scale()

        if rotation_mode == 'QUATERNION':
            xform_frame.rotation_euler = xform_matrix.to_euler()
        else:
            xform_frame.rotation_euler = xform_matrix.to_euler(rotation_mode)
        return xform_frame

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

    def get_quaternion(self):
        """Return the rotation Quaternion"""
        if self.rotation_mode == 'QUATERNION':
            return self.rotation_quaternion
        return self.rotation_euler.to_quaternion()

    def get_scale(self):
        """Return a Vector 3d with scale values along axis"""
        return self.scale

    def get_translation(self):
        """Return a Vector 4d with translation value
        in homogeneous coordinates"""
        translation = self.location.copy()
        translation.resize_4d()
        return translation


class Track:
    """Animation track base type"""
    def __init__(self, track_type, track_path,
                 frames_iter, values_iter):
        self.type = track_type
        self.path = track_path
        # default to linear
        self.interp = LINEAR_INTERPOLATION
        self.frames = list()
        self.values = list()

        for frame in frames_iter:
            self.frames.append(frame)
        for value in values_iter:
            self.values.append(value)

        assert len(self.frames) == len(self.values)

    def add_frame_data(self, frame, value):
        """Add add frame to track"""
        self.frames.append(frame)
        self.values.append(value)

    def frame_end(self):
        """The frame number of last frame"""
        if not self.frames:
            return 0
        return self.frames[-1]

    def frame_begin(self):
        """The frame number of first frame"""
        if not self.frames:
            return 0
        return self.frames[0]

    def convert_to_keys_object(self):
        """Convert to a godot animation keys object"""
        # need to be overrided
        assert False

    def blend_frames(self, frame_val1, frame_val2):
        """Blend two frame values into one"""
        # need to be overrided
        assert False

    def to_string(self):
        """Serialize a track object"""
        return self.convert_to_keys_object().to_string()

    def blend(self, track):
        """Blend current track with another one, used in nla editor"""
        assert self.interp == track.interp
        assert self.type == track.type

        if self.frame_begin() > track.frame_end():
            self.frames = track.frames + self.frames
            self.values = track.value + self.values
        elif self.frame_end() < track.frame_begin():
            self.frames = self.frames + track.frames
            self.values = self.values + track.values
        else:
            new_frames = list()
            new_values = list()

            blend_begin = max(self.frame_begin(), track.frame_begin())
            blend_end = min(self.frame_end(), track.frame_end())

            self_frame_idx = 0
            track_frame_idx = 0
            while self.frames[self_frame_idx] != blend_begin:
                new_frames.append(self.frames[self_frame_idx])
                new_values.append(self.values[self_frame_idx])
                self_frame_idx += 1

            while track.frames[track_frame_idx] != blend_begin:
                new_frames.append(track.frames[track_frame_idx])
                new_values.append(track.values[track_frame_idx])
                track_frame_idx += 1

            while (self_frame_idx < len(self.frames) and
                   track_frame_idx < len(track.frames) and
                   self.frames[self_frame_idx] <= blend_end and
                   track.frames[track_frame_idx] <= blend_end):
                if (self.frames[self_frame_idx] ==
                        track.frames[track_frame_idx]):
                    new_frames.append(self.frames[self_frame_idx])

                    new_values.append(
                        self.blend_frames(
                            self.values[self_frame_idx],
                            track.values[track_frame_idx]
                        )
                    )

                    self_frame_idx += 1
                    track_frame_idx += 1
                elif (self.frames[self_frame_idx] <
                      track.frames[track_frame_idx]):
                    new_frames.append(self.frames[self_frame_idx])
                    new_values.append(self.values[self_frame_idx])
                    self_frame_idx += 1
                else:
                    new_frames.append(track.frames[track_frame_idx])
                    new_values.append(track.values[track_frame_idx])
                    track_frame_idx += 1

            while self_frame_idx < len(self.frames):
                new_frames.append(self.frames[self_frame_idx])
                new_values.append(self.values[self_frame_idx])
                self_frame_idx += 1

            while track_frame_idx < len(track.frames):
                new_frames.append(track.frames[track_frame_idx])
                new_values.append(track.values[track_frame_idx])
                track_frame_idx += 1

            self.frames = new_frames
            self.values = new_values


class TransformTrack(Track):
    """Animation track whose frame value is TranslationFrame object"""
    def __init__(self, track_path, frames_iter=(), values_iter=()):
        super().__init__("transform", track_path, frames_iter, values_iter)
        self.parent_trans_inverse = mathutils.Matrix.Identity(4)

        # Fix of object's rotation, directional object like
        # camera, spotLight has different initial orientation
        self.is_directional = False

        self.interp = LINEAR_INTERPOLATION

    def set_parent_inverse(self, parent_inverse):
        """Blender interpolate is matrix_basis, it needs to left multiply
        its parent's object.matrix_parent_inverse to get
        matrix_local(parent space transform)"""
        self.parent_trans_inverse = mathutils.Matrix(parent_inverse)

    def blend_frames(self, frame_val1, frame_val2):
        """Blend two transform frames into one"""
        # FIXME: currently only blend with ADD
        new_frame = TransformFrame()
        for frame in (frame_val1, frame_val2):
            if frame.rotation_mode != 'QUATERNION':
                frame.rotation_quaternion = (
                    frame.rotation_euler.to_quaternion()
                )

        new_frame.rotation_quaternion = (
            frame_val1.rotation_quaternion @ frame_val2.rotation_quaternion
        )

        new_frame.location = frame_val1.location + frame_val2.location
        new_frame.scale = frame_val1.scale

        return new_frame

    def convert_to_keys_object(self):
        """Convert a transform track to godot structure"""
        array = Array(prefix='[', suffix=']')

        time_per_frame = 1 / bpy.context.scene.render.fps
        scene_frame_start = bpy.context.scene.frame_start

        if self.interp == LINEAR_INTERPOLATION:
            frames, values = strip_adjacent_dup_keyframes(
                self.frames, self.values)
        else:
            frames = self.frames
            values = self.values

        for frame, trans_frame in zip(frames, values):
            # move animation first frame to scene.frame_start
            if frame < scene_frame_start:
                continue

            # get actual translation from blender weird location..
            translation = (
                self.parent_trans_inverse @ trans_frame.get_translation())

            location = mathutils.Vector(
                [x / translation[3] for x in translation[:3]])
            quaternion = trans_frame.get_quaternion()
            scale = trans_frame.get_scale()

            # convert from z-up to y-up
            location = mathutils.Vector([location.x, location.z, -location.y])
            quaternion = mathutils.Quaternion(
                [quaternion.w, quaternion.x, quaternion.z, -quaternion.y])
            scale = mathutils.Vector([scale.x, scale.z, scale.y])

            # for directional objects like SpotLight, camera, etc.
            if self.is_directional:
                rotation = mathutils.Euler((math.radians(-90), 0, 0))
                quaternion = quaternion @ rotation.to_quaternion()

            array.append((frame - scene_frame_start) * time_per_frame)
            # transition default 1.0
            array.append(1.0)
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


class ValueTrack(Track):
    """Animation track which has the type 'value' in godot"""
    def __init__(self, track_path, interp=LINEAR_INTERPOLATION,
                 frames_iter=(), values_iter=()):
        super().__init__("value", track_path, frames_iter, values_iter)
        self.interp = interp

    def blend_frames(self, frame_val1, frame_val2):
        # FIXME: default use REPLACE
        return max(frame_val1, frame_val2)

    def convert_to_keys_object(self):
        """Convert a value track to a godot keys object"""
        time_array = Array(prefix='PoolRealArray(', suffix=')')
        transition_array = Array(prefix='PoolRealArray(', suffix=')')
        value_array = Array(prefix='[', suffix=']')

        time_per_frame = 1 / bpy.context.scene.render.fps
        scene_frame_start = bpy.context.scene.frame_start

        if self.interp == LINEAR_INTERPOLATION:
            frames, values = strip_adjacent_dup_keyframes(
                self.frames, self.values)
        else:
            frames = self.frames
            values = self.values

        for frame, frame_val in zip(frames, values):
            # move animation first frame to scene.frame_start
            if frame < scene_frame_start:
                continue

            time = (frame - scene_frame_start) * time_per_frame
            time_array.append(time)
            transition_array.append(1)
            value_array.append(frame_val)

        keys_map = Map()
        keys_map["times"] = time_array.to_string()
        keys_map["transitions"] = transition_array.to_string()
        keys_map["update"] = UPDATE_CONTINUOUS
        keys_map["values"] = value_array.to_string()

        return keys_map


class FloatTrack(ValueTrack):
    """Value track whose frame value is float"""
    def blend_frames(self, frame_val1, frame_val2):
        return max(frame_val1, frame_val2)


class ColorTrack(ValueTrack):
    """Value track whose frame value is mathutils.Color"""
    def blend_frames(self, frame_val1, frame_val2):
        return mathutils.Color(
            tuple(map(max, frame_val1, frame_val2))
        )


class BezierTrack(Track):
    """Track using bezier interpolcation"""
    def __init__(self, track_path, frames_iter=(), values_iter=()):
        super().__init__("bezier", track_path, frames_iter, values_iter)

    def blend_frames(self, frame_val1, frame_val2):
        # xxx: default use REPLACE
        return max(frame_val1, frame_val2)

    def convert_to_keys_object(self):
        """Convert a list of bezier point to a pool real array"""
        time_array = Array(prefix='PoolRealArray(', suffix=')')
        points_array = Array(prefix='PoolRealArray(', suffix=')')
        fps = bpy.context.scene.render.fps
        scene_frame_start = bpy.context.scene.frame_start
        for frame, frame_val in zip(self.frames, self.values):
            time = (frame - scene_frame_start) / fps
            time_array.append(time)
            points_array.append(frame_val.value)
            points_array.append((frame_val.left_handle[0] - frame) / fps)
            points_array.append(frame_val.left_handle[1])
            points_array.append((frame_val.right_handle[0] - frame) / fps)
            points_array.append(frame_val.right_handle[1])
        keys_map = Map()
        keys_map["points"] = points_array
        keys_map["times"] = time_array
        return keys_map


def build_const_interp_value_track(track_path, action_strip, converter,
                                   fcurve):
    """Build a godot value track from a Blender const interpolation fcurve"""
    track = FloatTrack(track_path)
    track.interp = NEAREST_INTERPOLATION

    if converter is None:
        for keyframe in fcurve.keyframe_points:
            point_x, point_y = action_strip.evalute_keyframe(keyframe)
            track.add_frame_data(point_x, point_y)
    else:
        for keyframe in fcurve.keyframe_points:
            point_x, point_y = action_strip.evalute_keyframe(keyframe)
            track.add_frame_data(point_x, converter(point_y))

    return track


def build_linear_interp_value_track(track_path, action_strip, converter,
                                    fcurve):
    """Build a godot value track by evaluate every frame of Blender fcurve"""
    track = FloatTrack(track_path)

    frame_range = action_strip.frame_range
    if converter is None:
        for frame in range(frame_range[0], frame_range[1]):
            track.add_frame_data(
                frame, action_strip.evaluate_fcurve(fcurve, frame)
            )
    else:
        for frame in range(frame_range[0], frame_range[1]):
            track.add_frame_data(
                frame, converter(action_strip.evaluate_fcurve(fcurve, frame))
            )

    return track


def build_beizer_interp_value_track(track_path, action_strip, converter,
                                    fcurve):
    """Build a godot bezier track"""
    track = BezierTrack(track_path)

    for keyframe in fcurve.keyframe_points:
        point_value = converter(keyframe.co[1])
        # bezier curve handle use margin
        track.add_frame_data(
            int(keyframe.co[0]),
            BezierFrame(
                point_value,
                (keyframe.handle_left.x,
                 converter(keyframe.handle_left.y) - point_value),
                (keyframe.handle_right.x,
                 converter(keyframe.handle_right.y) - point_value),
            )
        )

    return track


class AnimationResource(InternalResource):
    """Internal resource with type Animation"""
    def __init__(self, name, owner_anim_player):
        super().__init__('Animation', name)
        self['step'] = 0.1
        self['length'] = 0

        # helper attributes, not exported to ESCN
        self.tracks = collections.OrderedDict()
        self.anim_player = owner_anim_player

    def add_track(self, track):
        """add a track to animation resource"""
        node_path_str = track.path.to_string()
        track_length = (
            (track.frame_end() - bpy.context.scene.frame_start) /
            bpy.context.scene.render.fps
        )
        if track_length > self['length']:
            self['length'] = track_length

        if node_path_str in self.tracks:
            updated_track = self.tracks[node_path_str]
            updated_track.blend(track)
        else:
            track_id_str = 'tracks/{}'.format(len(self.tracks))
            self.tracks[node_path_str] = track
            self[track_id_str + '/type'] = '"{}"'.format(track.type)
            self[track_id_str + '/path'] = node_path_str
            self[track_id_str + '/interp'] = track.interp
            self[track_id_str + '/keys'] = track

    # pylint: disable-msg=too-many-arguments
    def add_obj_xform_track(self, node_type, track_path,
                            xform_frames_list, frame_range,
                            parent_mat_inverse=mathutils.Matrix.Identity(4)):
        """Add a object transform track to AnimationResource"""
        track = TransformTrack(
            track_path,
            frames_iter=range(frame_range[0], frame_range[1]),
            values_iter=xform_frames_list,
        )
        track.set_parent_inverse(parent_mat_inverse)
        if node_type in ("SpotLight", "DirectionalLight",
                         "Camera", "CollisionShape"):
            track.is_directional = True

        self.add_track(track)

    # pylint: disable-msg=too-many-arguments
    def add_attribute_track(self, action_strip, fcurve,
                            converter, node_path, use_bezier=False):
        """Add a track into AnimationResource, the track is a
        one-one mapping to one fcurve."""
        if fcurve is not None and fcurve.keyframe_points:
            interpolation = fcurve.keyframe_points[0].interpolation
            if interpolation == 'CONSTANT':
                new_track = build_const_interp_value_track(
                    node_path, action_strip, converter, fcurve
                )
            elif use_bezier and interpolation == 'BEZIER':
                new_track = build_beizer_interp_value_track(
                    node_path, action_strip, converter, fcurve
                )
            else:
                new_track = build_linear_interp_value_track(
                    node_path, action_strip, converter, fcurve
                )
            self.add_track(new_track)


class AnimationPlayer(NodeTemplate):
    """Godot scene node with type AnimationPlayer"""
    def __init__(self, name, parent):
        super().__init__(name, "AnimationPlayer", parent)
        # use parent node as the animation root node
        self['root_node'] = NodePath(self.get_path(), parent.get_path())
        # blender actions not in nla_tracks are treated as default
        self.active_animation = None

    def add_active_animation_resource(self, escn_file, resource_name):
        """Active animation resource corresponding to blender active action,
        however, int some animation mode it may hold active action from
        children objects"""
        self.active_animation = self.create_animation_resource(
            escn_file, resource_name
        )

    def create_animation_resource(self, escn_file, resource_name):
        """Create a new animation resource and add it into escn file"""
        resource_name_filtered = re.sub(r'[\[\]\{\}]+', '', resource_name)

        new_anim_resource = AnimationResource(resource_name_filtered, self)
        # add animation resource without checking hash,
        # blender action is in world space, while godot animation
        # is in local space (parent space),  so identical actions
        # are not necessarily generates identical godot animations
        resource_id = escn_file.force_add_internal_resource(new_anim_resource)

        # this filter may not catch all illegal char
        self['anims/{}'.format(resource_name_filtered)] = (
            "SubResource({})".format(resource_id))

        return new_anim_resource


def find_child_animation_player(node):
    """Find AnimationPlayer in node's children, None is
    returned if not find one"""
    for child in node.children:
        if child.get_type() == 'AnimationPlayer':
            return child
    return None


def get_animation_player(escn_file, export_settings, godot_node):
    """Get a AnimationPlayer node, its return value depends
    on animation exporting settings"""
    animation_player = None
    # the parent of AnimationPlayer
    animation_base = None

    if export_settings['animation_modes'] == 'ACTIONS':
        animation_player = None
        animation_base = godot_node
    elif export_settings['animation_modes'] == 'SCENE_ANIMATION':
        scene_root = escn_file.nodes[0]
        animation_player = find_child_animation_player(scene_root)
        animation_base = scene_root
    else:  # export_settings['animation_modes'] == 'SQUASHED_ACTIONS':
        animation_base = godot_node
        node_ptr = godot_node
        while node_ptr is not None:
            animation_player = find_child_animation_player(node_ptr)
            if animation_player is not None:
                break
            node_ptr = node_ptr.parent

    if animation_player is None:
        animation_player = AnimationPlayer(
            name='AnimationPlayer',
            parent=animation_base,
        )

        escn_file.add_node(animation_player)

    return animation_player
