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
        return bool(blender_object.constraints)
    return False


def check_pose_constraint(blender_object):
    """Return bool indicate if object has pose constraint"""
    if (isinstance(blender_object, bpy.types.Object) and
            isinstance(blender_object.data, bpy.types.Armature)):
        for pose_bone in blender_object.pose.bones:
            if pose_bone.constraints:
                return True
    return False


def bake_constraint_to_action(blender_object, base_action, in_place):
    """Bake pose or object constrainst (e.g. IK) to action"""
    if base_action is not None:
        blender_object.animation_data.action = base_action
        frame_range = range(
            int(base_action.frame_range[0]),
            int(base_action.frame_range[1]) + 1)
    else:
        frame_range = range(1, 251)  # default, can be improved

    # if action_bake_into is None, it would create a new one
    # and baked into it
    if in_place:
        action_bake_into = base_action
    else:
        action_bake_into = None

    baked_action = bpy_extras.anim_utils.bake_action_objects(
        object_action_pairs=[(blender_object, action_bake_into)],
        frames=frame_range,
        only_selected=False,
        do_pose=True,
        do_object=True,
        do_visual_keying=True,
    )[0]

    if in_place:
        return action_bake_into

    if base_action is not None:
        baked_action.name = base_action.name[:-len(BAKING_SUFFIX)]
    else:
        baked_action.name = blender_object.name + 'Action'
    return baked_action
