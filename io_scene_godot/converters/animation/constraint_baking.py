"""Collection of helper functions to baking constraints into action"""
import bpy


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
