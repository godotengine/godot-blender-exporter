"""Export a armature node"""
import mathutils
from ..structures import NodeTemplate, NodePath, Array


def export_bone_attachment(escn_file, export_settings,
                           bl_object, parent_gd_node):
    """Export a blender object with parent_bone to a BoneAttachment"""
    bone_attachment = NodeTemplate(bl_object.parent_bone + 'BoneAttachment',
                                   'BoneAttachment', parent_gd_node)

    # node.parent_bone is exactly the bone name
    # in the parent armature node
    bone_attachment['bone_name'] = "\"{}\"".format(
        parent_gd_node.find_bone_name(bl_object.parent_bone)
    )

    # parent_gd_node is the SkeletonNode with the parent bone
    bone_id = parent_gd_node.find_bone_id(bl_object.parent_bone)

    # append node to its parent bone's bound_children list
    parent_gd_node["bones/{}/{}".format(bone_id, 'bound_children')].append(
        NodePath(parent_gd_node.get_path(), bone_attachment.get_path())
    )

    escn_file.add_node(bone_attachment)
    return bone_attachment


class Bone:
    """A Bone has almost same attributes as Godot bones"""

    def __init__(self, bone_id, bone_name, parent_name):
        self.id = bone_id
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


def export_bone(pose_bone, bones_mapping):
    """Convert a Blender bone to a escn bone"""
    assert pose_bone.name in bones_mapping
    bone_id = bones_mapping[pose_bone.name]
    bone_name = pose_bone.name
    parent_bone_name = ""

    rest_bone = pose_bone.bone

    ps_bone_iter = pose_bone.parent
    while (ps_bone_iter is not None and
           ps_bone_iter.name not in bones_mapping):
        ps_bone_iter = ps_bone_iter.parent
    if ps_bone_iter is not None:
        rest_mat = (ps_bone_iter.bone.matrix_local.inverted_safe() @
                    rest_bone.matrix_local)
        parent_bone_name = ps_bone_iter.name
    else:
        rest_mat = rest_bone.matrix_local
        parent_bone_name = ""

    pose_mat = pose_bone.matrix_basis

    bone = Bone(bone_id, bone_name, parent_bone_name)
    bone.rest = rest_mat
    bone.pose = pose_mat
    return bone


def ordered_bones(bones):
    """
    Order bones by hierarchy of the bone structure. From this, the proper
    index order of exported bones can be guaranteed.
    """
    ordered = []

    def visit(bone):
        nonlocal ordered
        ordered.append(bone)

        for child in bone.children:
            visit(child)

    for bone in bones:
        if bone.parent is None:
            visit(bone)

    return ordered


def generate_bones_mapping(export_settings, armature_obj):
    """Return a dict mapping blender bone name to godot bone id"""
    bone_id = 0
    bones_mapping = dict()

    # Iterate in actual armature hierarchy order
    for pose_bone in ordered_bones(armature_obj.pose.bones):
        if should_export(export_settings, armature_obj, pose_bone.bone):
            bones_mapping[pose_bone.name] = bone_id
            bone_id += 1

    return bones_mapping


class SkeletonNode(NodeTemplate):
    """tscn node with type Skeleton"""

    def __init__(self, name, parent):
        super().__init__(name, "Skeleton", parent)
        self['bones_in_world_transform'] = True

        # Mapping from blender bone name to godot bone id and name
        #
        # Usually we should not keep information in the godot node
        # instance, but Skeleton is a special case, we need to reference
        # some bone information when dealing with Animation
        self._bones_mapping = dict()

    def set_bones_mapping(self, bones_mapping):
        """set blender bone name to godot bone id map"""
        self._bones_mapping = bones_mapping

    def find_bone_id(self, bl_bone_name):
        """"Given blender bone name return the bone id in Skeleton node"""
        return self._bones_mapping.get(bl_bone_name, -1)

    def find_bone_name(self, bl_bone_name):
        """"Given blender bone name return the bone name in Skeleton node"""
        bone_id = self.find_bone_id(bl_bone_name)
        bone_name_key = 'bones/%d/name' % bone_id
        return self.get(bone_name_key, "").strip('"')

    def find_bone_rest(self, bl_bone_name):
        """Given a blender bone name , return its rest matrix"""
        bone_id = self.find_bone_id(bl_bone_name)
        bone_rest_key = 'bones/%d/rest' % bone_id
        return self.get(bone_rest_key, mathutils.Matrix.Identity(4))


def export_armature_node(escn_file, export_settings,
                         armature_obj, parent_gd_node):
    """Export an armature object"""
    skeleton_node = SkeletonNode(armature_obj.name, parent_gd_node)
    skeleton_node['transform'] = armature_obj.matrix_local

    bones_mapping = generate_bones_mapping(export_settings, armature_obj)
    skeleton_node.set_bones_mapping(bones_mapping)

    gd_bone_list = list()
    for pose_bone in armature_obj.pose.bones:
        if pose_bone.name in bones_mapping:
            gd_bone = export_bone(pose_bone, bones_mapping)
            gd_bone_list.append(gd_bone)

    bone_name_set = set()
    for gd_bone in sorted(gd_bone_list, key=lambda x: x.id):
        # filter illegal char from blender bone name
        gd_bone.name = gd_bone.name.replace(":", "").replace("/", "")

        # solve possible name conflict
        iterations = 1
        name_tmp = gd_bone.name
        while name_tmp in bone_name_set:
            name_tmp = gd_bone.name + str(iterations).zfill(3)
            iterations += 1
        gd_bone.name = name_tmp

        bone_name_set.add(gd_bone.name)

        bone_prefix = 'bones/{}'.format(gd_bone.id)
        # bone name must be the first property
        skeleton_node[bone_prefix + '/name'] = '"{}"'.format(gd_bone.name)
        skeleton_node[bone_prefix + '/parent'] = \
            bones_mapping.get(gd_bone.parent_name, -1)
        skeleton_node[bone_prefix + '/rest'] = gd_bone.rest
        skeleton_node[bone_prefix + '/pose'] = gd_bone.pose
        skeleton_node[bone_prefix + '/enabled'] = True
        skeleton_node[bone_prefix + '/bound_children'] = \
            Array(prefix='[', suffix=']')

    escn_file.add_node(skeleton_node)

    return skeleton_node
