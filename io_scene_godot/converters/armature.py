"""Export a armature node"""
import mathutils
from ..structures import NodeTemplate, NodePath, Array


def export_bone_attachment(escn_file, node, parent_gd_node):
    """Export a blender object with parent_bone to a BoneAttachment"""
    bone_attachment = NodeTemplate('BoneAttachment',
                                   'BoneAttachment', parent_gd_node)

    # node.parent_bone is exactly the bone name
    # in the parent armature node
    bone_attachment['bone_name'] = "\"{}\"".format(node.parent_bone)

    # regard to ```export_armature_node()```, the exported bone id
    # is the index of the bone in node.parent.pose.bones list
    bone_id = node.parent.pose.bones.find(node.parent_bone)

    # append node to its parent bone's bound_children list
    parent_gd_node["bones/{}/{}".format(bone_id, 'bound_children')].append(
        NodePath(parent_gd_node.get_path(), bone_attachment.get_path())
    )

    escn_file.add_node(bone_attachment)
    return bone_attachment


def get_armature_data(node):
    """Get the armature modifier of a blender object
    if does not have one, return None"""
    for modifier in node.modifiers:
        if modifier.type.lower() == 'armature':
            return modifier.object.data
    return None


def find_skeletion_node(node):
    """Return the cloest Skeleton from node to root,
    if not found, return None"""
    node_ptr = node
    while (node_ptr is not None and
           node_ptr.get_type() != "Skeleton"):
        node_ptr = node_ptr.parent
    return node_ptr


class Bone:
    """A Bone has almost same attributes as Godot bones"""
    def __init__(self, bone_name, parent_name):
        # id assigned when add to skeleton
        self.id = None
        self.name = bone_name
        self.parent_name = parent_name
        self.rest = mathutils.Matrix()
        self.pose = mathutils.Matrix()


def export_bone(pose_bone, exclude_ctrl_bone):
    """Convert a Blender bone to a escn bone"""
    bone_name = pose_bone.name
    parent_bone_name = ""

    rest_bone = pose_bone.bone

    if exclude_ctrl_bone:
        rest_mat = rest_bone.matrix_local
        bone_ptr = rest_bone.parent
        while bone_ptr is not None and not bone_ptr.use_deform:
            bone_ptr = bone_ptr.parent
        if bone_ptr is not None:
            rest_mat = (bone_ptr.matrix_local.inverted_safe() *
                        rest_mat)
            parent_bone_name = bone_ptr.name
    else:
        if pose_bone.parent is None:
            rest_mat = rest_bone.matrix_local
        else:
            parent_bone_name = pose_bone.parent.name
            rest_mat = (rest_bone.parent.matrix_local.inverted_safe() *
                        rest_bone.matrix_local)
    pose_mat = pose_bone.matrix_basis

    bone = Bone(bone_name, parent_bone_name)
    bone.rest = rest_mat
    bone.pose = pose_mat
    return bone


class SkeletonNode(NodeTemplate):
    """tscn node with type Skeleton"""
    def __init__(self, name, parent):
        super().__init__(name, "Skeleton", parent)
        self.bone_name_to_id_map = dict()

    def find_bone_id(self, bone_name):
        """"Given bone name find the bone id in Skeleton node"""
        return self.bone_name_to_id_map.get(bone_name, -1)

    def add_bones(self, bone_list):
        """Add a list of bone to skeleton node"""
        # need first add all bones into name_to_id_map,
        # otherwise the parent bone finding would be incorrect
        for bone in bone_list:
            bone.id = len(self.bone_name_to_id_map)
            self.bone_name_to_id_map[bone.name] = bone.id

        for bone in bone_list:
            bone_prefix = 'bones/{}'.format(bone.id)

            # bone name must be the first property
            self[bone_prefix + '/name'] = '"{}"'.format(bone.name)
            self[bone_prefix + '/parent'] = self.find_bone_id(bone.parent_name)
            self[bone_prefix + '/rest'] = bone.rest
            self[bone_prefix + '/pose'] = bone.pose
            self[bone_prefix + '/enabled'] = True
            self[bone_prefix + '/bound_children'] = Array(
                prefix='[', suffix=']')


def export_armature_node(escn_file, export_settings, node, parent_gd_node):
    """Export an armature node"""
    if "ARMATURE" not in export_settings['object_types']:
        return parent_gd_node

    skeleton_node = SkeletonNode(node.name, parent_gd_node)
    skeleton_node['transform'] = node.matrix_local

    bone_list = list()
    for pose_bone in node.pose.bones:
        if (export_settings["use_exclude_ctrl_bone"] and
                pose_bone.bone.use_deform):
            bone = export_bone(
                pose_bone, export_settings["use_exclude_ctrl_bone"])
            bone_list.append(bone)

    skeleton_node.add_bones(bone_list)

    escn_file.add_node(skeleton_node)

    return skeleton_node
