"""Exports particles as multimesh to Godot"""
import math
import bpy
import mathutils

from ..structures import (
    NodeTemplate, InternalResource, mat4_to_string)
from .mesh import ArrayMeshResourceExporter


def export_multimesh_node(escn_file, export_settings,
                          obj, parent_gd_node):
    """Export blender particle to a MultiMeshInstance"""
    context = bpy.context
    dg_eval = context.evaluated_depsgraph_get()
    obj_eval = context.object.evaluated_get(dg_eval)

    multimeshid_active = None
    for _ps in obj_eval.particle_systems:
        # In Blender's particle system params, If "Render - Render As" are
        # switched to "Collection", there maybe several objects instanced to
        # one particle, but in Godot one MultiMeshInstance just have one
        # object to instance, so choose the first object in Blender to display
        # as the only one object in Godot's MultiMeshInstance's resource.
        if (_ps.settings.instance_collection and
                _ps.settings.instance_collection.all_objects[0]):
            instance_object = _ps.settings.instance_collection.all_objects[0]
        elif _ps.settings.instance_object:
            instance_object = _ps.settings.instance_object

        multimeshnode = NodeTemplate(
            _ps.name, 'MultiMeshInstance', parent_gd_node
            )

        # Export instance mesh resource first
        instance_mesh_exporter = ArrayMeshResourceExporter(instance_object)

        mesh_id = instance_mesh_exporter.export_mesh(
            escn_file, export_settings
            )

        multimesh_exporter = MultiMeshResourceExporter(obj, mesh_id, _ps)

        multimeshid = multimesh_exporter.export_multimesh(
            escn_file, export_settings, _ps.name)

        if _ps == obj_eval.particle_systems.active:
            multimeshid_active = multimeshid

    multimeshnode['multimesh'] = 'SubResource({})'.format(multimeshid_active)
    multimeshnode['visible'] = obj.visible_get()

    escn_file.add_node(multimeshnode)

    return multimeshnode


def has_particle(node):
    """Returns True if the object has particles"""
    context = bpy.context
    dg_eval = context.evaluated_depsgraph_get()
    obj_eval = context.object.evaluated_get(dg_eval)

    return len(obj_eval.particle_systems) > 0


class MultiMeshResourceExporter:
    """Export a multimesh resource from a blender mesh object"""

    def __init__(self, mesh_object, instance_mesh_id, particle_system):
        # blender multimesh object
        self.object = mesh_object
        self.instance_mesh_id = instance_mesh_id
        self.particle_system = particle_system

        self.mesh_resource = None

    def export_multimesh(self, escn_file, export_settings, particle_name):
        """Saves a mesh into the escn file"""
        converter = MultiMeshConverter(self.particle_system)
        # Due the missing instance particle support in Godot,
        # we export one MultiMeshResource from each ParticleSystem.
        # For now it is safe to use bpy ParticleSystem object as
        # the hash key.
        key = self.particle_system
        # Check if multi-mesh resource exists so we don't bother to export it twice,
        multimesh_id = escn_file.get_internal_resource(key)
        if multimesh_id is not None:
            return multimesh_id

        multimesh = converter.to_multimesh()
        if multimesh is not None:
            self.mesh_resource = MultiMeshResource(particle_name)
            self.mesh_resource['instance_count'] = '{}'.format(
                len(self.particle_system.particles))
            self.mesh_resource['mesh'] = 'SubResource({})'.format(
                self.instance_mesh_id)
            self.mesh_resource['transform_array'] = (
                'PoolVector3Array({})'.format(
                    converter.to_multimesh())
                )

            multimesh_id = escn_file.add_internal_resource(
                self.mesh_resource, key)
            assert multimesh_id is not None

        return multimesh_id


class MultiMeshResource(InternalResource):
    """Godot MultiMesh resource"""

    def __init__(self, name):
        super().__init__('MultiMesh', name)
        self['transform_format'] = 1

        # Change above value in MultiMeshResourceExporter
        self['instance_count'] = 0
        self['mesh'] = None
        self['transform_array'] = None


class MultiMeshConverter:
    """Blender Particles' mat4x4 to
    Godot MultiMesh resource PoolVector3Array"""

    def __init__(self, particle_system):
        self.particle_system = particle_system

    def to_multimesh(self):
        """Evaluates object & converts to final multimesh, ready for export.
        The multimesh is only temporary."""
        transform_array = []
        float32array = ''
        for _particle in self.particle_system.particles:
            quat_x = mathutils.Quaternion((1.0, 0.0, 0.0), math.radians(90.0))
            quat_y = mathutils.Quaternion((0.0, 1.0, 0.0), math.radians(90.0))
            quat_z = mathutils.Quaternion((0.0, 0.0, 1.0), math.radians(90.0))
            quat_a = _particle.rotation.copy()
            quat_a.rotate(quat_x)
            quat_a.rotate(quat_y)
            quat_a.rotate(quat_z)
            quat_a.normalize()
            rot_tmp = quat_a[1]
            quat_a[1] = quat_a[3]
            quat_a[3] = rot_tmp

            rot = quat_a
            loc = _particle.location - mathutils.Vector((0, 0, 1))
            scl = _particle.size

            mat_sca_x = mathutils.Matrix.Scale(scl, 4, (1.0, 0.0, 0.0))
            mat_sca_y = mathutils.Matrix.Scale(scl, 4, (0.0, 1.0, 0.0))
            mat_sca_z = mathutils.Matrix.Scale(scl, 4, (0.0, 0.0, 1.0))

            mat_rot = rot.to_matrix()
            mat_trs = mathutils.Matrix.Translation(loc)

            mat = (
                mat_trs @ mat_rot.to_4x4() @ mat_sca_x @ mat_sca_y @ mat_sca_z
            )

            mat4 = mat.to_4x4()

            transform_array.append(mat4_to_string(mat4, prefix='', suffix=''))
        return ','.join(transform_array)
