"""Export a armature node"""
import collections
import mathutils
from ..structures import NodeTemplate, NodePath, Array


def export_bone_attachment(escn_file, node, parent_gd_node):
    """Export a blender object with parent_bone to a BoneAttachment"""
    bone_attachment = NodeTemplate('BoneAttachment',
                                   'BoneAttachment', parent_gd_node)

    # node.parent_bone is exactly the bone name
    # in the parent armature node
    bone_attachment['bone_name'] = "\"{}\"".format(
        parent_gd_node.find_bone_name(node.parent_bone)
    )

    # parent_gd_node is the SkeletonNode with the parent bone
    bone_id = parent_gd_node.find_bone_id(node.parent_bone)

    # append node to its parent bone's bound_children list
    parent_gd_node["bones/{}/{}".format(bone_id, 'bound_children')].append(
        NodePath(parent_gd_node.get_path(), bone_attachment.get_path())
    )

    escn_file.add_node(bone_attachment)
    return bone_attachment


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


def should_export(export_settings, armature_obj, rest_bone):
    """Return a bool indicates whether a bone should be exported"""
    # if bone has a child object, it must exported
    for child in armature_obj.children:
        if child.parent_bone == rest_bone.name:
            return True

    if not (export_settings['use_exclude_ctrl_bone'] and
            not rest_bone.use_deform):
        return True

    return False


def export_bone(pose_bone, bl_bones_to_export):
    """Convert a Blender bone to a escn bone"""
    bone_name = pose_bone.name
    parent_bone_name = ""

    rest_bone = pose_bone.bone

    ps_bone_ptr = pose_bone.parent
    while ps_bone_ptr is not None and ps_bone_ptr not in bl_bones_to_export:
        ps_bone_ptr = ps_bone_ptr.parent
    if ps_bone_ptr is not None:
        rest_mat = (ps_bone_ptr.bone.matrix_local.inverted_safe() @
                    rest_bone.matrix_local)
        parent_bone_name = ps_bone_ptr.name
    else:
        rest_mat = rest_bone.matrix_local
        parent_bone_name = ""

    pose_mat = pose_bone.matrix_basis

    bone = Bone(bone_name, parent_bone_name)
    bone.rest = rest_mat
    bone.pose = pose_mat
    return bone


class SkeletonNode(NodeTemplate):
    """tscn node with type Skeleton"""
    BoneInfo = collections.namedtuple(
        "boneInfo",
        ('id', 'name'),
    )

    def __init__(self, name, parent):
        super().__init__(name, "Skeleton", parent)
        # Mapping from blender bone name to godot bone id and name
        self.bones = dict()

    def find_bone_id(self, bl_bone_name):
        """"Given blender bone name return the bone id in Skeleton node"""
        if bl_bone_name not in self.bones:
            return -1
        return self.bones[bl_bone_name].id

    def find_bone_name(self, bl_bone_name):
        """"Given blender bone name return the bone name in Skeleton node"""
        if bl_bone_name not in self.bones:
            return ""
        return self.bones[bl_bone_name].name

    def find_bone_rest(self, bl_bone_name):
        """Given a blender bone name , return its rest matrix"""
        gd_bone_id = self.find_bone_id(bl_bone_name)
        if gd_bone_id == -1 or gd_bone_id >= len(self.bones):
            return mathutils.Matrix.Identity(4)
        bone_rest_key = 'bones/{}/rest'.format(gd_bone_id)
        return self[bone_rest_key]

    def add_bones(self, bone_list):
        """Add a list of bone to skeleton node"""
        # need first add all bones into name_to_id_map,
        # otherwise the parent bone finding would be incorrect
        bone_name_set = set()
        for bone in bone_list:
            bone.id = len(self.bones)
            bl_bone_name = bone.name

            # filter illegal char from blender bone name
            bone.name = bone.name.replace(":", "").replace("/", "")
            # solve possible name conflict
            iterations = 1
            gd_bone_name = bone.name
            while gd_bone_name in bone_name_set:
                gd_bone_name = bone.name + str(iterations).zfill(3)
                iterations += 1
            bone.name = gd_bone_name

            bone_name_set.add(bone.name)
            self.bones[bl_bone_name] = SkeletonNode.BoneInfo(
                bone.id, bone.name
            )

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
    skeleton_node = SkeletonNode(node.name, parent_gd_node)
    skeleton_node['transform'] = node.matrix_local

    # according to configures, generate a set of blender bones
    # need to be exported
    bl_bones_to_export = list()
    for pose_bone in node.pose.bones:
        if should_export(export_settings, node, pose_bone.bone):
            bl_bones_to_export.append(pose_bone)

    gd_bone_list = list()
    for pose_bone in bl_bones_to_export:
        if pose_bone in bl_bones_to_export:
            gd_bone = export_bone(pose_bone, bl_bones_to_export)
            gd_bone_list.append(gd_bone)

    skeleton_node.add_bones(gd_bone_list)

    escn_file.add_node(skeleton_node)

    return skeleton_node
