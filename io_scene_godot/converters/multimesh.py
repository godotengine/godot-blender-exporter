import bpy
import mathutils
import math
import re
from ..structures import (
    Array, NodeTemplate, InternalResource, Map, gamma_correct,fix_matrix)
from .mesh import ArrayMeshResourceExporter

def export_multimesh_node(escn_file, export_settings,
                           obj, parent_gd_node):
    """Export a blender object with parent_bone to a BoneAttachment"""
    context = bpy.context
    dg = context.evaluated_depsgraph_get()
    ob = context.object.evaluated_get(dg)

    ps = ob.particle_systems.active
    instance_object=ps.settings.instance_collection.all_objects[0]

    multimeshnode = NodeTemplate(re.sub('[^a-zA-Z0-9]','',ps.name) + 'MultiMesh',
                                   'MultiMeshInstance', parent_gd_node)

    # Export instance mesh resource first
    instance_mesh_exporter = ArrayMeshResourceExporter(instance_object)
    # armature_obj = None
    # if "ARMATURE" in export_settings['object_types']:
    #     armature_obj = get_modifier_armature(obj)
    #     if armature_obj:
    #         instance_mesh_exporter.init_mesh_bones_data(armature_obj, export_settings)
    #         # set armature to REST so current pose does not affect converted
    #         # meshes.
    #         armature_pose_position = armature_obj.data.pose_position
    #         armature_obj.data.pose_position = "REST"
    mesh_id = instance_mesh_exporter.export_mesh(escn_file, export_settings)

    multimeshExporter = MultiMeshResourceExporter(obj,mesh_id,ps)


    multimeshid = multimeshExporter.export_multimesh(escn_file,export_settings,ps.name)

    multimeshnode['multimesh'] = 'SubResource(%d)' % multimeshid
    multimeshnode['visible'] = obj.visible_get()

    escn_file.add_node(multimeshnode)
    return multimeshnode

def has_particle(node):
    """Returns True if the object has particles"""
    context = bpy.context
    dg = context.evaluated_depsgraph_get()
    ob = context.object.evaluated_get(dg)

    return len(ob.particle_systems)>0


class MultiMeshResourceExporter:
    """Export a multimesh resource from a blender mesh object"""

    def __init__(self, mesh_object,instance_mesh_id,particle_system):
        # blender multimesh object
        self.object = mesh_object
        self.instance_mesh_id= instance_mesh_id
        self.particle_system=particle_system

        self.mesh_resource = None
        

    def export_multimesh(self, escn_file, export_settings,particle_name):
        """Saves a mesh into the escn file"""
        converter = MultiMeshConverter(self.particle_system)
        key = MultiMeshResourceKey('MultiMesh', self.object, export_settings,particle_name)
        # Check if mesh resource exists so we don't bother to export it twice,
        multimesh_id = escn_file.get_internal_resource(key)
        if multimesh_id is not None:
            return multimesh_id

        multimesh = converter.to_multimesh()
        if multimesh is not None:
            self.mesh_resource = MultiMeshResource(particle_name)
            self.mesh_resource['instance_count']='%d' % len(self.particle_system.particles)
            self.mesh_resource['mesh']='SubResource(%d)' % self.instance_mesh_id
            self.mesh_resource['transform_array']='PoolVector3Array(%s)' % converter.to_multimesh()

            multimesh_id = escn_file.add_internal_resource(self.mesh_resource, key)
            assert multimesh_id is not None

        return multimesh_id


class MultiMeshResourceKey:
    """Produces a key based on an mesh object's data, every different
    Mesh Resource would have a unique key"""

    def __init__(self, rsc_type, obj, export_settings,particle_name):
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
        self['mesh']= None
        self['transform_array'] = None

class MultiMeshConverter:
    """Blender Particles' mat4x4 to Godot MultiMesh resource PoolVector3Array"""
    def __init__(self,particle_system):
        self.particle_system=particle_system
    def to_multimesh(self):
        transform_array=[]
        float32array=''
        for p in self.particle_system.particles:
            quat_x = mathutils.Quaternion((1.0, 0.0, 0.0), math.radians(90.0))
            quat_y = mathutils.Quaternion((0.0, 1.0, 0.0), math.radians(90.0))
            quat_z = mathutils.Quaternion((0.0, 0.0, 1.0), math.radians(90.0))
            quat_a = p.rotation.copy()
            quat_a.rotate(quat_x)
            quat_a.rotate(quat_y)
            quat_a.rotate(quat_z)
            quat_a.normalize()
            a=quat_a[1]
            quat_a[1]=quat_a[3]
            quat_a[3]=a
            
            rot=quat_a
            loc = p.location- mathutils.Vector((0,0,1))
            scl = p.size
            print('loc',loc,'rot',rot,'size',scl)
            
            mat_rot = rot.to_matrix()
            mat_trans = mathutils.Matrix.Translation(loc)

            mat = mat_trans @ (mat_rot.to_4x4()*scl)

            mat4 = mat.to_4x4()
            print(mat4)
            

            # float32array+=str(round(mat4[0][0],3))+','
            # float32array+=str(round(mat4[2][0],3))+','
            # float32array+=str(round(mat4[1][0],3))+','
            # float32array+=str(round(mat4[0][3],3))+','
            
            # float32array+=str(round(mat4[0][2],3))+','
            # float32array+=str(round(mat4[2][2],3))+','
            # float32array+=str(round(mat4[1][2],3))+','
            # float32array+=str(round(mat4[2][3],3))+','
            
            # float32array+=str(round(mat4[0][1],3))+','
            # float32array+=str(round(mat4[2][1],3))+','
            # float32array+=str(round(mat4[1][1],3))+','
            # float32array+=str(round(-mat4[1][3],3))+','

            transform_array.append(mat4_to_string(mat4))

            # float32array+=str(round(mat4[0][0],3))+','
            # float32array+=str(round(mat4[0][0],3))+','
            # float32array+=str(round(mat4[0][0],3))+','
            # float32array+=str(round(mat4[0][0],3))+','
            # float32array+=str(round(mat4[0][0],3))+','
            # float32array+=str(round(mat4[0][0],3))+','
            # float32array+=str(round(mat4[0][0],3))+','
            # float32array+=str(round(mat4[0][0],3))+','
            # float32array+=str(round(mat4[0][0],3))+','
            # float32array+=str(round(mat4[0][0],3))+','
            # float32array+=str(round(mat4[0][0],3))+','
                    
        # float32array=float32array[:-1]
        return ','.join(transform_array)

def mat4_to_string(mtx):
    """Converts a matrix to a "Transform" string that can be parsed by Godot"""
    mtx = fix_matrix(mtx)
    array = Array('',suffix='')
    for row in range(3):
        for col in range(3):
            array.append(mtx[row][col])

    # Export the basis
    for axis in range(3):
        array.append(mtx[axis][3])

    return array.to_string()