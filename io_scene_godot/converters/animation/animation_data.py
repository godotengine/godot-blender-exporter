"""Parsing Blender animation_data to create appropriate Godot
AnimationPlayer as well as distribute Blender action into various
action exporting functions"""

import bpy
from .action import (
    export_camera_action,
    export_shapekey_action,
    export_light_action,
    export_transform_action
)
from .constraint_baking import (
    bake_constraint_to_action,
    check_object_constraint,
    check_pose_constraint,
    action_baking_finalize,
    action_baking_initialize
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

        self.action_exporter_func = ACTION_EXPORTER_MAP[action_type]
        self.animation_player = None

        self.has_object_constraint = False
        self.has_pose_constraint = False
        self.need_baking = False

        self.unmute_nla_tracks = []
        self.mute_nla_tracks = []

        self.check_baking_condition(action_type)
        self.preprocess_nla_tracks(blender_object)

    def check_baking_condition(self, action_type):
        """Check whether the animated object has any constraint and
        thus need to do baking, if needs, some states would be set"""
        has_obj_cst = check_object_constraint(self.blender_object)
        has_pose_cst = check_pose_constraint(self.blender_object)
        self.need_baking = (
            action_type == 'transform' and (has_obj_cst or has_pose_cst)
        )
        self.has_object_constraint = has_obj_cst
        self.has_pose_constraint = has_pose_cst

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

    def bake_to_new_action(self, action_to_bake):
        """Baking object and pose constraint altogether.

        Note that it accept a action to bake (which would not be modified)
        and always return a new created baked actiony"""
        if self.has_object_constraint and self.has_pose_constraint:
            tmp = bake_constraint_to_action(
                self.blender_object, action_to_bake, "OBJECT", False
            )
            ret = bake_constraint_to_action(
                self.blender_object, action_to_bake, "POSE", True
            )
        elif self.has_pose_constraint:
            ret = bake_constraint_to_action(
                self.blender_object, action_to_bake, "POSE", False
            )
        elif self.has_object_constraint:
            ret = bake_constraint_to_action(
                self.blender_object, action_to_bake, "OBJECT", False
            )
        return ret

    def export_active_action(self, escn_file, active_action):
        """Export the active action, if needed, would call bake.

        Note that active_action maybe None, which would happen when object has
        some constraint (so even no action it is still animated)"""
        if self.need_baking:
            action_baking_initialize(active_action)
            action_active_to_export = self.bake_to_new_action(active_action)
        else:
            action_active_to_export = active_action

        if self.animation_player.active_animation is None:
            self.animation_player.add_active_animation_resource(
                escn_file, action_active_to_export.name
            )

        self.action_exporter_func(
            self.godot_node,
            self.animation_player,
            self.blender_object,
            ActionStrip(action_active_to_export),
            self.animation_player.active_animation
        )

        if self.need_baking:
            # remove new created action
            bpy.data.actions.remove(action_active_to_export)
            action_baking_finalize(active_action)
        else:
            # here export unmuted nla_tracks into animation resource,
            # this is not needed for baking, as baking has applied to
            # active action
            for track in self.unmute_nla_tracks:
                for strip in track.strips:
                    if strip.action:
                        self.action_exporter_func(
                            self.godot_node,
                            self.animation_player,
                            self.blender_object,
                            ActionStrip(strip),
                            self.animation_player.active_animation
                        )

    def export_active_action_from_nla(self, escn_file):
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
                        self.animation_player,
                        self.blender_object,
                        ActionStrip(strip),
                        self.animation_player.active_animation
                    )

    def export_stashed_track(self, escn_file, stashed_track):
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

        for strip in stashed_track.strips:
            if strip.action:
                if self.need_baking:
                    action_baking_initialize(strip.action)
                    action_to_export = self.bake_to_new_action(strip.action)
                else:
                    action_to_export = strip.action

                self.action_exporter_func(
                    self.godot_node,
                    self.animation_player,
                    self.blender_object,
                    ActionStrip(strip, action_to_export),
                    anim_resource
                )

                if self.need_baking:
                    # remove baked action
                    bpy.data.actions.remove(action_to_export)
                    action_baking_finalize(strip.action)

        if not self.need_baking:
            # if baking, nla_tracks are already baked into strips
            for nla_track in self.unmute_nla_tracks:
                for strip in nla_track.strips:
                    if strip.action:
                        self.action_exporter_func(
                            self.godot_node,
                            self.animation_player,
                            self.blender_object,
                            ActionStrip(strip),
                            anim_resource
                        )


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
        anim_exporter.export_active_action(escn_file, active_action)
    elif anim_exporter.unmute_nla_tracks:
        # if has effective nla_tracks but no active action, fake one
        anim_exporter.export_active_action_from_nla(escn_file)

    # export actions in nla_tracks, each exported to seperate
    # animation resources
    if export_settings['use_stashed_action']:
        for stashed_track in anim_exporter.mute_nla_tracks:
            anim_exporter.export_stashed_track(escn_file, stashed_track)

    if active_action is not None:
        blender_object.animation_data.action = active_action
