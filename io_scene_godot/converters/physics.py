"""
The physics converter is a little special as it runs before the blender
object is exported. In blender, the object owns the physics. In Godot, the
physics owns the object.
"""

import logging
import mathutils
from ..structures import NodeTemplate, InternalResource, Array, _AXIS_CORRECT

PHYSICS_TYPES = {'KinematicBody', 'RigidBody', 'StaticBody'}


def has_physics(node):
    """Returns True if the object has physics enabled"""
    return node.rigid_body is not None


def is_physics_root(node):
    """Checks to see if this object is the root of the physics tree. This is
    True if none of the parents of the object have physics."""
    return get_physics_root(node) is None


def get_physics_root(node):
    """ Check upstream for other rigid bodies (to allow compound shapes).
    Returns the upstream-most rigid body and how many nodes there are between
    this node and the parent """
    parent_rbd = None
    current_node = node
    while current_node.parent is not None:
        if current_node.parent.rigid_body is not None:
            parent_rbd = current_node.parent
        current_node = current_node.parent
    return parent_rbd


def get_extents(node):
    """Returns X, Y and Z total height"""
    raw = node.bound_box
    vecs = [mathutils.Vector(v) for v in raw]
    mins = vecs[0].copy()
    maxs = vecs[0].copy()

    for vec in vecs:
        mins.x = min(vec.x, mins.x)
        mins.y = min(vec.y, mins.y)
        mins.z = min(vec.z, mins.z)

        maxs.x = max(vec.x, maxs.x)
        maxs.y = max(vec.y, maxs.y)
        maxs.z = max(vec.z, maxs.z)
    return maxs - mins


def export_collision_shape(escn_file, export_settings, node, parent_gd_node,
                           parent_override=None):
    """Exports the collision primitives/geometry"""
    col_name = node.name + 'Collision'
    col_node = NodeTemplate(col_name, "CollisionShape", parent_gd_node)

    if parent_override is None:
        col_node['transform'] = mathutils.Matrix.Identity(4)
    else:
        parent_to_world = parent_override.matrix_world.inverted_safe()
        col_node['transform'] = parent_to_world @ node.matrix_world
    col_node['transform'] = col_node['transform'] @ _AXIS_CORRECT

    rbd = node.rigid_body

    shape_id = None
    col_shape = None
    if rbd.collision_shape in ("CONVEX_HULL", "MESH"):
        is_convex = rbd.collision_shape == "CONVEX_HULL"
        shape_id = generate_shape_mesh(
            escn_file, export_settings,
            node, is_convex
        )
    else:
        bounds = get_extents(node)
        if rbd.collision_shape == "BOX":
            col_shape = InternalResource("BoxShape", col_name)
            col_shape['extents'] = mathutils.Vector(bounds / 2)
            shape_id = escn_file.add_internal_resource(col_shape, rbd)

        elif rbd.collision_shape == "SPHERE":
            col_shape = InternalResource("SphereShape", col_name)
            col_shape['radius'] = max(list(bounds)) / 2
            shape_id = escn_file.add_internal_resource(col_shape, rbd)

        elif rbd.collision_shape == "CAPSULE":
            col_shape = InternalResource("CapsuleShape", col_name)
            col_shape['radius'] = max(bounds.x, bounds.y) / 2
            col_shape['height'] = bounds.z - col_shape['radius'] * 2
            shape_id = escn_file.add_internal_resource(col_shape, rbd)
        else:
            logging.warning("Unable to export physics shape for %s", node.name)

        if col_shape is not None and rbd.use_margin:
            col_shape['margin'] = rbd.collision_margin

    if shape_id is not None:
        col_node['shape'] = "SubResource({})".format(shape_id)
    escn_file.add_node(col_node)

    return col_node


def generate_shape_mesh(escn_file, export_settings, node, is_convex):
    """Generates godots PolygonShape from a blender mesh object"""
    # pylint: disable-msg=cyclic-import
    from .mesh import (MeshConverter, MeshResourceKey)

    margin = 0
    if node.rigid_body.use_margin:
        margin = node.rigid_body.collision_margin

    # Build the Shape resource hash key with rigid margin and mesh data
    if is_convex:
        shape_rsc_type = "ConvexPolygonShape"
    else:
        shape_rsc_type = "ConcavePolygonShape"
    mesh_data_key = MeshResourceKey(shape_rsc_type, node, export_settings)
    shape_rsc_key = (margin, mesh_data_key)

    shape_id = escn_file.get_internal_resource(shape_rsc_key)
    if shape_id is not None:
        return shape_id

    # No cached Shape found, build new one
    col_shape = None
    mesh_converter = MeshConverter(node, export_settings)
    mesh = mesh_converter.to_mesh(calculate_tangents=False)
    if mesh is not None and mesh.polygons:
        vert_array = list()
        for poly in mesh.polygons:
            for vert_id in poly.vertices:
                vert_array.append(list(mesh.vertices[vert_id].co))

        if is_convex:
            col_shape = InternalResource("ConvexPolygonShape", mesh.name)
            col_shape['points'] = Array("PoolVector3Array(", values=vert_array)
        else:
            col_shape = InternalResource("ConcavePolygonShape", mesh.name)
            col_shape['data'] = Array("PoolVector3Array(", values=vert_array)

        if node.rigid_body.use_margin:
            col_shape['margin'] = node.rigid_body.collision_margin

        shape_id = escn_file.add_internal_resource(col_shape, shape_rsc_key)

    mesh_converter.to_mesh_clear()

    return shape_id


def export_physics_controller(escn_file, export_settings, node,
                              parent_gd_node):
    """Exports the physics body "type" as a separate node. In blender, the
    physics body type and the collision shape are one object, in godot they
    are two. This is the physics body type"""
    phys_name = node.name + 'Physics'

    rbd = node.rigid_body
    if rbd.type == "ACTIVE":
        if rbd.kinematic:
            phys_controller = 'KinematicBody'
        else:
            phys_controller = 'RigidBody'
    else:
        phys_controller = 'StaticBody'

    phys_obj = NodeTemplate(phys_name, phys_controller, parent_gd_node)

    #  OPTIONS FOR ALL PHYSICS TYPES
    phys_obj['friction'] = rbd.friction
    phys_obj['bounce'] = rbd.restitution

    col_groups = 0
    for offset, flag in enumerate(rbd.collision_collections):
        col_groups += (1 if flag else 0) << offset

    phys_obj['transform'] = node.matrix_local
    phys_obj['collision_layer'] = col_groups
    phys_obj['collision_mask'] = col_groups

    if phys_controller == "RigidBody":
        phys_obj['can_sleep'] = rbd.use_deactivation
        phys_obj['linear_damp'] = rbd.linear_damping
        phys_obj['angular_damp'] = rbd.angular_damping
        phys_obj['sleeping'] = rbd.use_start_deactivated

    escn_file.add_node(phys_obj)

    return phys_obj


def export_physics_properties(escn_file, export_settings, node,
                              parent_gd_node):
    """Creates the necessary nodes for the physics"""
    parent_rbd = get_physics_root(node)

    if parent_rbd is None:
        parent_gd_node = export_physics_controller(
            escn_file, export_settings, node, parent_gd_node
        )

    # trace the path towards root, find the cloest physics node
    gd_node_ptr = parent_gd_node
    while gd_node_ptr.get_type() not in PHYSICS_TYPES:
        gd_node_ptr = gd_node_ptr.parent
    physics_gd_node = gd_node_ptr

    return export_collision_shape(
        escn_file, export_settings, node, physics_gd_node,
        parent_override=parent_rbd
    )
