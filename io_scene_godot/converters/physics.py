"""
The physics converter is a little special as it runs before the blender
object is exported. In blender, the object owns the physics. In Godot, the
physics owns the object.
"""

import logging
import bpy
import mathutils
import bmesh
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
        parent_to_world = parent_override.matrix_world.inverted()
        col_node['transform'] = parent_to_world * node.matrix_world
    col_node['transform'] *= _AXIS_CORRECT

    rbd = node.rigid_body

    shape_id = None
    bounds = get_extents(node)

    if rbd.collision_shape == "BOX":
        col_shape = InternalResource("BoxShape", col_name)
        col_shape['extents'] = mathutils.Vector(bounds/2)
        shape_id = escn_file.add_internal_resource(col_shape, rbd)

    elif rbd.collision_shape == "SPHERE":
        col_shape = InternalResource("SphereShape", col_name)
        col_shape['radius'] = max(list(bounds))/2
        shape_id = escn_file.add_internal_resource(col_shape, rbd)

    elif rbd.collision_shape == "CAPSULE":
        col_shape = InternalResource("CapsuleShape", col_name)
        col_shape['radius'] = max(bounds.x, bounds.y) / 2
        col_shape['height'] = bounds.z - col_shape['radius'] * 2
        shape_id = escn_file.add_internal_resource(col_shape, rbd)
    elif rbd.collision_shape == "CONVEX_HULL":
        col_shape, shape_id = generate_convex_mesh_array(
            escn_file, export_settings,
            node
        )
    elif rbd.collision_shape == "MESH":
        col_shape, shape_id = generate_triangle_mesh_array(
            escn_file, export_settings,
            node
        )
    else:
        logging.warning("Unable to export physics shape for %s", node.name)

    if shape_id is not None:

        if rbd.use_margin or rbd.collision_shape == "MESH":
            col_shape['margin'] = rbd.collision_margin
        col_node['shape'] = "SubResource({})".format(shape_id)
    escn_file.add_node(col_node)

    return col_node


def generate_convex_mesh_array(escn_file, export_settings, node):
    """Generates godots ConvexPolygonShape from an object"""
    mesh = node.data
    key = (mesh, "ConvexCollisionMesh")
    resource_id = escn_file.get_internal_resource(key)
    if resource_id is not None:
        return resource_id

    col_shape = InternalResource("ConvexPolygonShape", mesh.name)

    mesh = node.to_mesh(bpy.context.scene,
                        export_settings['use_mesh_modifiers'],
                        "RENDER")

    # Triangulate
    triangulated_mesh = bmesh.new()
    triangulated_mesh.from_mesh(mesh)
    # For some reason, generateing the convex hull here causes Godot to crash
    # bmesh.ops.convex_hull(triangulated_mesh, input=triangulated_mesh.verts)
    bmesh.ops.triangulate(triangulated_mesh, faces=triangulated_mesh.faces)
    triangulated_mesh.to_mesh(mesh)
    triangulated_mesh.free()

    vert_array = list()
    for poly in mesh.polygons:
        for vert_id in poly.vertices:
            vert_array.append(list(mesh.vertices[vert_id].co))

    bpy.data.meshes.remove(mesh)

    col_shape['points'] = Array("PoolVector3Array(", values=vert_array)

    return col_shape, escn_file.add_internal_resource(col_shape, key)


def generate_triangle_mesh_array(escn_file, export_settings, node):
    """Generates godots ConcavePolygonShape from an object"""
    mesh = node.data
    key = (mesh, "TriangleCollisionMesh")
    resource_id = escn_file.get_internal_resource(key)
    if resource_id is not None:
        return resource_id

    col_shape = InternalResource("ConcavePolygonShape", mesh.name)

    mesh = node.to_mesh(bpy.context.scene,
                        export_settings['use_mesh_modifiers'],
                        "RENDER")

    # Triangulate
    triangulated_mesh = bmesh.new()
    triangulated_mesh.from_mesh(mesh)
    bmesh.ops.triangulate(triangulated_mesh, faces=triangulated_mesh.faces)
    triangulated_mesh.to_mesh(mesh)
    triangulated_mesh.free()

    vert_array = list()
    for poly in mesh.polygons:
        for vert_id in poly.vertices:
            vert_array.append(list(mesh.vertices[vert_id].co))

    bpy.data.meshes.remove(mesh)

    col_shape['data'] = Array("PoolVector3Array(", values=vert_array)

    return col_shape, escn_file.add_internal_resource(col_shape, key)


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
    for offset, bit in enumerate(rbd.collision_groups):
        col_groups += bit << offset

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
