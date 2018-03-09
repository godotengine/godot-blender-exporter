"""
The physics converter is a little special as it runs before the blender
object is exported. In blender, the object owns the physics. In Godot, the
physics owns the object.
"""
import math
import logging
import mathutils
from ..structures import NodeTemplate, InternalResource


AXIS_CORRECT = mathutils.Matrix.Rotation(math.radians(-90), 4, 'X')


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


def export_collision_shape(escn_file, export_settings, node, parent_path):
    """Exports the collision primitives/geometry"""
    col_name = node.name + 'Collision'
    col_node = NodeTemplate(col_name, "CollisionShape", parent_path)
    col_node.transform = mathutils.Matrix.Identity(4) * AXIS_CORRECT

    rbd = node.rigid_body

    col_shape = None
    bounds = get_extents(node)

    if rbd.collision_shape == "BOX":
        col_shape = InternalResource("BoxShape")
        col_shape.extents = mathutils.Vector(bounds/2)

    elif rbd.collision_shape == "SPHERE":
        col_shape = InternalResource("SphereShape")
        col_shape.radius = max(list(bounds))/2

    elif rbd.collision_shape == "CAPSULE":
        col_shape = InternalResource("CapsuleShape")
        col_shape.radius = max(bounds.x, bounds.y) / 2
        col_shape.height = bounds.z - col_shape.radius * 2
    # elif rbd.collision_shape == "CONVEX_HULL":
    #   pass
    # elif rbd.collision_shape == "MESH":
    #   pass
    else:
        logging.warning("Unable to export physics shape for %s", node.name)

    if col_shape is not None:
        shape_id = escn_file.add_internal_resource(col_shape, rbd)
        col_node.shape = "SubResource({})".format(shape_id)
    escn_file.add_node(col_node)


def export_physics_properties(escn_file, export_settings, node, parent_path):
    """Creates the necessary nodes for the physics"""
    phys_name = node.name + 'Physics'

    rbd = node.rigid_body
    if rbd.type == "ACTIVE":
        if rbd.kinematic:
            phys_controller = 'KinematicBody'
        else:
            phys_controller = 'RigidBody'
    else:
        phys_controller = 'StaticBody'

    phys_obj = NodeTemplate(phys_name, phys_controller, parent_path)

    #  OPTIONS FOR ALL PHYSICS TYPES
    phys_obj.friction = rbd.friction
    phys_obj.bounce = rbd.restitution

    col_groups = 0
    for offset, bit in enumerate(rbd.collision_groups):
        col_groups += bit << offset

    phys_obj.transform = node.matrix_local
    phys_obj.collision_layer = col_groups
    phys_obj.collision_mask = col_groups

    if phys_controller == "RigidBody":
        phys_obj.can_sleep = rbd.use_deactivation
        phys_obj.linear_damp = rbd.linear_damping
        phys_obj.angular_damp = rbd.angular_damping
        phys_obj.sleeping = rbd.use_start_deactivated

    escn_file.add_node(phys_obj)

    # Computer parent path for child nodes
    if parent_path == '.':
        phys_path = phys_name
    else:
        phys_path = parent_path + '/' + phys_name

    export_collision_shape(escn_file, export_settings, node, phys_path)

    return phys_path
