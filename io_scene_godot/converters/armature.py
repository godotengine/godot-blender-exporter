"""Export a armature node"""
import mathutils
from ..structures import NodeTemplate


def get_armature_data(node):
    """Get the armature modifier of a blender object
    if does not have one, return None"""
    for modifier in node.modifiers:
        if modifier.type.lower() == 'armature':
            return modifier.object.data
    return None


class Bone:
    """A Bone has almost same attributes as Godot bones"""

    # must be ordered, Godot scene exporter force the first
    # attribute of bone be 'name'
    attributes = (
        "name",
        "parent",
        "rest",
        "pose",
        "enabled",
        "bound_children",
    )

    def __init__(self, bone_id, name, parent_id):
        # name needs wrapped by double quotes
        self.id = bone_id
        self.name = '"{}"'.format(name)

        # attributes
        self.parent = parent_id
        self.rest = mathutils.Matrix()
        self.pose = mathutils.Matrix()
        self.enabled = True
        self.bound_children = None

    def attr_to_key(self, attr_name):
        """Add bone id to bone attribute"""
        assert attr_name in Bone.attributes

        return "bones/{}/{}".format(self.id, attr_name).lower()


def export_bone(pose_bone, self_id, parent_id):
    """Convert a Blender bone to a escn bone"""
    bone_name = pose_bone.name

    rest_bone = pose_bone.bone
    if pose_bone.parent is None:
        rest_mat = rest_bone.matrix_local
    else:
        rest_mat = (rest_bone.parent.matrix_local.inverted_safe() *
                    rest_bone.matrix_local)
    pose_mat = pose_bone.matrix_basis

    bone = Bone(self_id, bone_name, parent_id)
    bone.rest = rest_mat
    bone.pose = pose_mat
    return bone


def attach_bones_to_skeleton(skeleton_node, bone_list):
    """Convert Bone list to attributes of skeleton node"""
    for bone in bone_list:
        for attr in Bone.attributes:
            if not getattr(bone, attr) is None:
                skeleton_node[bone.attr_to_key(attr)] = getattr(bone, attr)


def export_armature_node(escn_file, export_settings, node, parent_gd_node):
    """Export an armature node"""
    if "ARMATURE" not in export_settings['object_types']:
        return parent_gd_node

    skeleton_node = NodeTemplate(node.name, "Skeleton", parent_gd_node)
    skeleton_node['transform'] = node.matrix_local

    bone_list = list()
    for index, pose_bone in enumerate(node.pose.bones):
        if pose_bone.parent is None:
            parent_id = -1
        else:
            parent_id = node.pose.bones.find(pose_bone.parent.name)
        bone_list.append(export_bone(pose_bone, index, parent_id))

    attach_bones_to_skeleton(skeleton_node, bone_list)

    escn_file.add_node(skeleton_node)

    return skeleton_node
