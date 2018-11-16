"""Collection of helper functions to baking constraints into action"""

import bpy
import bpy_extras.anim_utils

# a suffix append to action need baking to avoid name collision
# with baked action's name
BAKING_SUFFIX = '--being-baking'


def action_baking_initialize(action):
    """Intialize steps before an action going to baking"""
    if action is not None:
        action.name = action.name + BAKING_SUFFIX


def action_baking_finalize(action):
    """Clear up some baking information for an action having
    going through baking"""
    if action is not None:
        action.name = action.name[:-len(BAKING_SUFFIX)]


def check_object_constraint(blender_object):
    """Return bool indicate if object has constraint"""
    if isinstance(blender_object, bpy.types.Object):
        return True if blender_object.constraints else False
    return False


def check_pose_constraint(blender_object):
    """Return bool indicate if object has pose constraint"""
    if (isinstance(blender_object, bpy.types.Object) and
            isinstance(blender_object.data, bpy.types.Armature)):
        for pose_bone in blender_object.pose.bones:
            if pose_bone.constraints:
                return True
    return False


def bake_constraint_to_action(blender_object, base_action, bake_type,
                              in_place):
    """Bake pose or object constrainst (e.g. IK) to action"""
    if base_action is not None:
        blender_object.animation_data.action = base_action
        frame_range = tuple([int(x) for x in base_action.frame_range])
    else:
        frame_range = (1, 250)  # default, can be improved

    # if action_bake_into is None, it would create a new one
    # and baked into it
    if in_place:
        action_bake_into = base_action
    else:
        action_bake_into = None

    do_pose = bake_type == "POSE"
    do_object = not do_pose

    if bpy.app.version <= (2, 79, 0):
        active_obj_backup = bpy.context.scene.objects.active

        # the object to bake is the current active object
        bpy.context.scene.objects.active = blender_object
        baked_action = bpy_extras.anim_utils.bake_action(
            frame_start=frame_range[0],
            frame_end=frame_range[1],
            frame_step=1,
            only_selected=False,
            action=action_bake_into,
            do_pose=do_pose,
            do_object=do_object,
            do_visual_keying=True,
        )

        bpy.context.scene.objects.active = active_obj_backup
    else:
        baked_action = bpy_extras.anim_utils.bake_action(
            obj=blender_object,
            frame_start=frame_range[0],
            frame_end=frame_range[1],
            frame_step=1,
            only_selected=False,
            action=action_bake_into,
            do_pose=do_pose,
            do_object=do_object,
            do_visual_keying=True,
        )

    if in_place:
        return action_bake_into

    if base_action is not None:
        baked_action.name = base_action.name[:-len(BAKING_SUFFIX)]
    else:
        baked_action.name = blender_object.name + 'Action'
    return baked_action
