"""Exports a grease pencil object"""
import logging
import bpy
import mathutils

from .material import export_material
from ..structures import (
    Array, NodeTemplate, InternalResource, Map, gamma_correct)
from .utils import MeshConverter, MeshResourceKey, fix_vertex, gdenums
from .physics import has_physics, export_physics_properties
from .mesh import ArrayMeshResource


def export_grease_node(escn_file, export_settings, obj, parent_gd_node):
    """Exports a MeshInstance. If the mesh is not already exported, it will
    trigger the export of that mesh"""
    # If this mesh object has physics properties, we need to export them first
    # because they need to be higher in the scene-tree

    if has_physics(obj):
        parent_gd_node = export_physics_properties(
            escn_file, export_settings, obj, parent_gd_node
        )

    mesh_node = NodeTemplate(obj.name, "MeshInstance", parent_gd_node)
    mesh_exporter = ArrayGreaseResourceExporter(obj)
    mesh_id = mesh_exporter.export_grease(escn_file, export_settings)

    if mesh_id is not None:
        mesh_node['mesh'] = "SubResource({})".format(mesh_id)
        mesh_node['visible'] = obj.visible_get()

        #mesh_resource = escn_file.internal_resources[mesh_id - 1]
        #export_object_link_material(
        #    escn_file, export_settings, obj, mesh_resource, mesh_node
        #)

    # Transform of rigid mesh is moved up to its collision
    # shapes.
    if has_physics(obj):
        mesh_node['transform'] = mathutils.Matrix.Identity(4)
    else:
        mesh_node['transform'] = obj.matrix_local

    escn_file.add_node(mesh_node)
    return mesh_node


class ArrayGreaseResourceExporter:
    """Export a mesh resource from a blender grease pencil object"""

    def __init__(self, ob):
        # blender grease pencil object
        assert ob.type == "GPENCIL"
        self.object = ob
        self.mesh_resource = None
        self.has_tangents = False

    def export_grease(self, escn_file, export_settings):
        """Saves a mesh into the escn file"""
        key = MeshResourceKey('ArrayMesh', self.object, export_settings)
        # Check if mesh resource exists so we don't bother to export it twice,
        mesh_id = escn_file.get_internal_resource(key)
        if mesh_id is not None:
            return mesh_id

        mesh = self.object.data

        if mesh is not None and len(mesh.layers):
            self.mesh_resource = ArrayMeshResource(mesh.name)

            # Separate by materials into single-material surfaces
            self.generate_surfaces(
                escn_file,
                export_settings,
                mesh
            )

            mesh_id = escn_file.add_internal_resource(self.mesh_resource, key)
            assert mesh_id is not None

        return mesh_id


    def generate_surfaces(self, escn_file, export_settings, mesh):
        """Splits up the mesh into surfaces with a single material each.
        Within this, it creates the Vertex structure to contain all data about
        a single vertex
        """
        surfaces = []
        for glayer in mesh.layers:
            if not len(glayer.frames) or not len(glayer.frames[0].strokes):
                continue

            for stroke in glayer.frames[0].strokes:

                # Find a surface that matches the material, otherwise create a new
                # surface for it
                surface_index = self.mesh_resource.get_surface_id(
                    stroke.material_index
                )
                if surface_index is None:
                    surface_index = len(surfaces)
                    self.mesh_resource.set_surface_id(
                        stroke.material_index, surface_index
                    )
                    surface = Surface()
                    surface.id = surface_index
                    surfaces.append(surface)
                    if mesh.materials:
                        if stroke.material_index >= len(mesh.materials):
                            print('WARN: bad face.material_index')
                            mat = mesh.materials[-1]
                        else:
                            mat = mesh.materials[stroke.material_index]
                        if (mat is not None and
                                export_settings['use_export_material']):
                            surface.material = export_material(
                                escn_file,
                                export_settings,
                                self.object,
                                mat
                            )

                surface = surfaces[surface_index]
                vertex_indices = []

                for vert_id in range(len(stroke.points)):
                    vert = stroke.points[vert_id]
                    new_vert = Vertex( vert )
                    surface.vertex_data.vertices.append(new_vert)
                    surface.vertex_data.indices.append(vert_id)

        for surface in surfaces:
            self.mesh_resource[surface.name_str] = surface


class VerticesArrays:
    """Godot use several arrays to store the data of a surface(e.g. vertices,
    indices, bone weights). A surface object has a single VerticesArrays as its
    default and also may have a morph array with a list of VerticesArrays"""

    def __init__(self):
        self.vertices = []
        self.indices = []
        self.has_bone = False

    def get_color_array(self):
        """Generate a single array that contains the colors of all the vertices
        in this surface"""
        has_colors = self.vertices[0].color is not None
        if has_colors:
            color_vals = Array("ColorArray(")
            for vert in self.vertices:
                col = list(vert.color)
                if len(col) == 3:
                    col += [1.0]
                color_vals.extend(col)
        else:
            color_vals = Array("null, ; no Vertex Colors", "", "")

        return color_vals

    def generate_lines(self):
        """Generates the various arrays that are part of the surface (eg
        normals, position etc.)"""
        surface_lines = Array(
            prefix='[\n\t\t', seperator=',\n\t\t', suffix='\n\t]'
        )

        position_vals = Array("Vector3Array(",
                              values=[v.vertex for v in self.vertices])

        surface_lines.append(position_vals.to_string())
        surface_lines.append("null, ; No Normals")
        surface_lines.append("null, ; No Tangents")
        surface_lines.append("null, ; No Colors")
        surface_lines.append("null, ; No UV1")
        surface_lines.append("null, ; No UV2")
        surface_lines.append("null, ; No Bones")
        surface_lines.append("null, ; No Bone Weights")

        if self.indices:
            face_indices = Array(
                "IntArray(",
                flat_values = self.indices
            )
        else:
            # in morph, it has no indices
            face_indices = Array(
                "null, ; Morph Object", "", ""
            )

        surface_lines.append(face_indices.to_string())

        return surface_lines

    def to_string(self):
        """Serialize"""
        return self.generate_lines().to_string()


class Surface:
    """A surface is a single part of a mesh (eg in blender, one mesh can have
    multiple materials. Godot calls these separate parts separate surfaces"""

    def __init__(self):
        # map from a Vertex.tup() to surface.vertex_data.indices
        self.vertex_map = dict()
        self.vertex_data = VerticesArrays()
        self.morph_arrays = Array(prefix="[", seperator=",\n", suffix="]")
        # map from mesh.loop_index to surface.vertex_data.indices
        self.vertex_index_map = dict()
        self.id = None
        self.material = None

    @property
    def name_str(self):
        """Used to separate surfaces that are part of the same mesh by their
        id"""
        return "surfaces/" + str(self.id)

    def generate_object(self):
        """Generate object with mapping structure which fully
        describe the surface"""
        surface_object = Map()
        if self.material is not None:
            surface_object['material'] = self.material
        surface_object['primitive'] = gdenums['PRIMITIVE_LINE_LOOP']
        surface_object['arrays'] = self.vertex_data
        surface_object['morph_arrays'] = self.morph_arrays
        return surface_object

    def to_string(self):
        """Serialize"""
        return self.generate_object().to_string()


class Vertex:
    """Stores all the attributes for a single vertex"""

    def get_tup(self):
        """Returns a tuple form of this vertex so that it can be hashed"""
        tup = (self.vertex.x, self.vertex.y, self.vertex.z, self.normal.x,
               self.normal.y, self.normal.z)
        for uv_data in self.uv:
            tup = tup + (uv_data.x, uv_data.y)
        if self.color is not None:
            tup = tup + (self.color.x, self.color.y, self.color.z)
        if self.tangent is not None:
            tup = tup + (self.tangent.x, self.tangent.y, self.tangent.z)
        if self.bitangent is not None:
            tup = tup + (self.bitangent.x, self.bitangent.y,
                         self.bitangent.z)
        return tup

    __slots__ = ("vertex", "normal", "tangent", "bitangent", "color", "uv")

    def __init__(self, vert=None):
        # note: grease pencil vert contains:
        # 'co', 'pressure', 'rna_type', 'select', 'strength', 'uv_factor', 'uv_rotation'
        if vert:
            x,y,z = fix_vertex(vert.co)
            self.vertex = mathutils.Vector((x, y, z))
        else:
            self.vertex = mathutils.Vector((0.0, 0.0, 0.0))
        self.normal = mathutils.Vector((0.0, 0.0, 0.0))
        self.tangent = None
        self.bitangent = None
        self.color = None
        self.uv = []
