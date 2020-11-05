import math
import bpy
import mathutils

from ..structures import (
    Array, NodeTemplate, InternalResource, fix_matrix, mat4_to_string)
from .mesh import ArrayMeshResourceExporter


def export_multimesh_node(escn_file, export_settings,
                          obj, parent_gd_node):
    """Export blender particle to a MultiMeshInstance"""
    context = bpy.context
    dg = context.evaluated_depsgraph_get()
    ob = context.object.evaluated_get(dg)

    multimeshid_active=None
    for i in ob.particle_systems:
        ps = i
        if (ps.settings.instance_collection and
                ps.settings.instance_collection.all_objects[0]):
            instance_object = ps.settings.instance_collection.all_objects[0]
        elif ps.settings.instance_object:
            instance_object = ps.settings.instance_object

        multimeshnode = NodeTemplate(ps.name, 'MultiMeshInstance', parent_gd_node)

        # Export instance mesh resource first
        instance_mesh_exporter = ArrayMeshResourceExporter(instance_object)

        mesh_id = instance_mesh_exporter.export_mesh(escn_file, export_settings)

        multimeshExporter = MultiMeshResourceExporter(obj, mesh_id, ps)

        multimeshid = multimeshExporter.export_multimesh(
            escn_file, export_settings, ps.name)
        
        if i==ob.particle_systems.active_index:
            multimeshid_active=multimeshid

    multimeshnode['multimesh'] = 'SubResource({})'.format(multimeshid_active)
    multimeshnode['visible'] = obj.visible_get()

    escn_file.add_node(multimeshnode)

    return multimeshnode


def has_particle(node):
    """Returns True if the object has particles"""
    context = bpy.context
    dg = context.evaluated_depsgraph_get()
    ob = context.object.evaluated_get(dg)

    return len(ob.particle_systems) > 0


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
        key = MultiMeshResourceKey(
            'MultiMesh', self.object, export_settings, particle_name)
        # Check if mesh resource exists so we don't bother to export it twice,
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


class MultiMeshResourceKey:
    """Produces a key based on an mesh object's data, every different
    Mesh Resource would have a unique key"""

    def __init__(self, rsc_type, obj, export_settings, particle_name):
        mesh_data = obj.data

        # Resource type included because same blender mesh may be used as
        # MeshResource or CollisionShape, but they are different resources
        gd_rsc_type = rsc_type

        # Precalculate the hash now for better efficiency later
        self._data = tuple([obj.name, particle_name, gd_rsc_type])
        self._hash = hash(self._data)

    def __hash__(self):
        return self._hash

    def __eq__(self, other):
        # pylint: disable=protected-access
        return (self.__class__ == other.__class__ and
                self._data == other._data)


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
        transform_array = []
        float32array = ''
        for p in self.particle_system.particles:
            quat_x = mathutils.Quaternion((1.0, 0.0, 0.0), math.radians(90.0))
            quat_y = mathutils.Quaternion((0.0, 1.0, 0.0), math.radians(90.0))
            quat_z = mathutils.Quaternion((0.0, 0.0, 1.0), math.radians(90.0))
            quat_a = p.rotation.copy()
            quat_a.rotate(quat_x)
            quat_a.rotate(quat_y)
            quat_a.rotate(quat_z)
            quat_a.normalize()
            a = quat_a[1]
            quat_a[1] = quat_a[3]
            quat_a[3] = a

            rot = quat_a
            loc = p.location - mathutils.Vector((0, 0, 1))
            scl = p.size

            mat_sca_x = mathutils.Matrix.Scale(scl, 4, (1.0, 0.0, 0.0))
            mat_sca_y = mathutils.Matrix.Scale(scl, 4, (0.0, 1.0, 0.0))
            mat_sca_z = mathutils.Matrix.Scale(scl, 4, (0.0, 0.0, 1.0))

            mat_rot = rot.to_matrix()
            mat_trs = mathutils.Matrix.Translation(loc)

            mat = (
                mat_trs @ mat_rot.to_4x4() @ mat_sca_x @ mat_sca_y @ mat_sca_z
            )

            mat4 = mat.to_4x4()

            transform_array.append(mat4_to_string(mat4,prefix='',suffix=''))
        return ','.join(transform_array)
