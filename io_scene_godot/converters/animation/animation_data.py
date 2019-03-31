"""Parsing Blender animation_data to create appropriate Godot
AnimationPlayer as well as distribute Blender action into various
action exporting functions"""

import bpy
import mathutils
from .action import (
    export_camera_action,
    export_shapekey_action,
    export_light_action,
    export_transform_action,
    export_constrained_xform_action,
)
from .constraint_baking import (
    check_object_constraint,
    check_pose_constraint,
)
from .serializer import get_animation_player
from .action import ActionStrip


ACTION_EXPORTER_MAP = {
    'transform': export_transform_action,
    'shapekey': export_shapekey_action,
    'light': export_light_action,
    'camera': export_camera_action,
}


class ObjectAnimationExporter:
    """A helper class holding states while exporting
    animation data from a blender object"""

    def __init__(self, godot_node, blender_object, action_type):
        self.godot_node = godot_node
        self.blender_object = blender_object

        self.animation_player = None

        self.need_baking = False

        self.unmute_nla_tracks = []
        self.mute_nla_tracks = []

        self.check_baking_condition(action_type)
        self.preprocess_nla_tracks(blender_object)

        if not self.need_baking:
            self.action_exporter_func = ACTION_EXPORTER_MAP[action_type]
        else:
            self.action_exporter_func = export_constrained_xform_action

    def check_baking_condition(self, action_type):
        """Check whether the animated object has any constraint and
        thus need to do baking, if needs, some states would be set"""
        has_obj_cst = check_object_constraint(self.blender_object)
        has_pose_cst = check_pose_constraint(self.blender_object)
        self.need_baking = (
            action_type == 'transform' and (has_obj_cst or has_pose_cst)
        )

    def preprocess_nla_tracks(self, blender_object):
        """Iterative through nla tracks, separately store mute and unmuted
        tracks"""
        if blender_object.animation_data:
            for nla_track in blender_object.animation_data.nla_tracks:
                if not nla_track.strips:
                    # skip empty tracks
                    continue
                if not nla_track.mute:
                    self.unmute_nla_tracks.append(nla_track)
                else:
                    self.mute_nla_tracks.append(nla_track)

    def export_active_action(self, escn_file, export_settings, active_action):
        """Export the active action, if needed, would call bake.

        Note that active_action maybe None, which would happen when object has
        some constraint (so even no action it is still animated)"""
        if active_action is None:
            # object has constraints on other objects
            assert self.need_baking
            anim_rsc_name = self.blender_object.name + 'Action'
        else:
            anim_rsc_name = active_action.name

        if self.animation_player.active_animation is None:
            self.animation_player.add_active_animation_resource(
                escn_file, anim_rsc_name
            )

        self.action_exporter_func(
            self.godot_node,
            export_settings,
            self.blender_object,
            ActionStrip(active_action),
            self.animation_player.active_animation
        )
        self.clear_action_effect()

        if not self.need_baking:
            # here export unmuted nla_tracks into animation resource,
            # this is not needed for baking, as baking has applied to
            # active action
            for track in self.unmute_nla_tracks:
                for strip in track.strips:
                    if strip.action:
                        self.action_exporter_func(
                            self.godot_node,
                            export_settings,
                            self.blender_object,
                            ActionStrip(strip),
                            self.animation_player.active_animation
                        )
                        self.clear_action_effect()

    def export_active_action_from_nla(self, escn_file, export_settings):
        """Export all unmute nla_tracks into an active action.
        Note that it would not do baking for constraint"""
        if self.animation_player.active_animation is None:
            self.animation_player.add_active_animation_resource(
                escn_file, self.blender_object.name + 'Action'
            )

        for track in self.unmute_nla_tracks:
            for strip in track.strips:
                if strip.action:
                    self.action_exporter_func(
                        self.godot_node,
                        export_settings,
                        self.blender_object,
                        ActionStrip(strip),
                        self.animation_player.active_animation
                    )
                    self.clear_action_effect()

    def export_stashed_track(self, escn_file, export_settings, stashed_track):
        """Export a muted nla_track, track with all its contained action
        is exported to a single animation_resource.

        It works as an action lib"""
        if not stashed_track.strips:
            return

        # if only one action in nla_track, user may not editted
        # nla_track name, thus this would make exported name nicer
        if len(stashed_track.strips) > 1:
            anim_name = stashed_track.name
        else:
            anim_name = stashed_track.strips[0].name

        anim_resource = self.animation_player.create_animation_resource(
            escn_file, anim_name
        )

        if self.need_baking:
            stashed_track.mute = False

        for strip in stashed_track.strips:
            if strip.action:
                self.action_exporter_func(
                    self.godot_node,
                    export_settings,
                    self.blender_object,
                    ActionStrip(strip),
                    anim_resource
                )
                self.clear_action_effect()

        if self.need_baking:
            stashed_track.mute = True
        else:  # not self.need_baking:
            # if baking, nla_tracks are already baked into strips
            for nla_track in self.unmute_nla_tracks:
                for strip in nla_track.strips:
                    if strip.action:
                        self.action_exporter_func(
                            self.godot_node,
                            export_settings,
                            self.blender_object,
                            ActionStrip(strip),
                            anim_resource
                        )
                        self.clear_action_effect()

    def clear_action_effect(self):
        """Clear side effect of exporting an action"""
        if (isinstance(self.blender_object, bpy.types.Object) and
                self.blender_object.pose is not None):
            for pose_bone in self.blender_object.pose.bones:
                rest_bone = pose_bone.bone
                pose_bone.matrix_basis = mathutils.Matrix.Identity(4)


def export_animation_data(escn_file, export_settings, godot_node,
                          blender_object, action_type):
    """Export the action and nla_tracks in blender_object.animation_data,
    it will further call the action exporting function in AnimationDataExporter
    given by `func_name`"""
    if not export_settings['use_export_animation']:
        return

    anim_exporter = ObjectAnimationExporter(
        godot_node, blender_object, action_type
    )

    if (blender_object.animation_data is None and
            not anim_exporter.need_baking):
        return

    anim_exporter.animation_player = get_animation_player(
        escn_file, export_settings, godot_node
    )

    # back up active action to reset back after finish exporting
    if blender_object.animation_data:
        active_action = blender_object.animation_data.action
    else:
        active_action = None

    if (active_action is not None or anim_exporter.need_baking):
        anim_exporter.export_active_action(
            escn_file, export_settings, active_action)
    elif anim_exporter.unmute_nla_tracks:
        # if has effective nla_tracks but no active action, fake one
        anim_exporter.export_active_action_from_nla(
            escn_file, export_settings)

    # export actions in nla_tracks, each exported to seperate
    # animation resources
    if export_settings['use_stashed_action']:
        if blender_object.animation_data:
            # clear active action, isolate NLA track
            blender_object.animation_data.action = None
            obj_use_nla_backup = blender_object.animation_data.use_nla
            blender_object.animation_data.use_nla = True
        for stashed_track in anim_exporter.mute_nla_tracks:
            anim_exporter.export_stashed_track(
                escn_file, export_settings, stashed_track)
        if blender_object.animation_data:
            blender_object.animation_data.use_nla = obj_use_nla_backup

    if blender_object.animation_data is not None:
        blender_object.animation_data.action = active_action
