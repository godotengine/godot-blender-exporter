"""Exports a grease pencil object"""
import logging
import bpy
import mathutils

from .material import export_material
from ..structures import (
    Array, NodeTemplate, InternalResource, Map, gamma_correct)
from .utils import MeshConverter, MeshResourceKey
from .physics import has_physics, export_physics_properties

MAX_BONE_PER_VERTEX = 4

def export_grease_node(escn_file, export_settings, obj, parent_gd_node):
    """Exports a MeshInstance. If the mesh is not already exported, it will
    trigger the export of that mesh"""
    # If this mesh object has physics properties, we need to export them first
    # because they need to be higher in the scene-tree

    if has_physics(obj):
        parent_gd_node = export_physics_properties(
            escn_file, export_settings, obj, parent_gd_node
        )
        # skip wire mesh which is used as collision mesh
        if obj.display_type == "WIRE":
            return parent_gd_node

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


def fix_vertex(vtx):
    """Changes a single position vector from y-up to z-up"""
    return mathutils.Vector((vtx.x, vtx.z, -vtx.y))




class ArrayMeshResource(InternalResource):
    """Godot ArrayMesh resource, containing surfaces"""

    def __init__(self, name):
        super().__init__('ArrayMesh', name)
        self._mat_to_surf_mapping = dict()

    def get_surface_id(self, material_index):
        """Given blender material index, return the corresponding
        surface id"""
        return self._mat_to_surf_mapping.get(material_index, None)

    def set_surface_id(self, material_index, surface_id):
        """Set a relation between material and surface"""
        self._mat_to_surf_mapping[material_index] = surface_id


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

                    # Merge similar vertices
                    tup = new_vert.get_tup()
                    if tup not in surface.vertex_map:
                        surface.vertex_map[tup] = len(surface.vertex_data.vertices)
                        surface.vertex_data.vertices.append(new_vert)

                    vertex_index = surface.vertex_map[tup]
                    surface.vertex_index_map[vert_id] = vertex_index

                    vertex_indices.append(vertex_index)

                if len(vertex_indices) > 2:  # Only triangles and above
                    surface.vertex_data.indices.append(vertex_indices)

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

    def calc_tangent_dp(self, vert):
        """Calculates the dot product of the tangent. I think this has
        something to do with normal mapping"""
        cross_product = vert.normal.cross(vert.tangent)
        dot_product = cross_product.dot(vert.bitangent)
        return 1.0 if dot_product > 0.0 else -1.0

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

    def get_tangent_array(self):
        """Generate a single array that contains the tangents of all the
        vertices in this surface"""
        has_tangents = self.vertices[0].tangent is not None
        if has_tangents:
            tangent_vals = Array("FloatArray(")
            for vert in self.vertices:
                tangent_vals.extend(
                    list(vert.tangent) + [self.calc_tangent_dp(vert)]
                )
        else:
            tangent_vals = Array("null, ; No Tangents", "", "")
        return tangent_vals

    def get_uv_array(self, uv_index):
        """Returns an array representing the specified UV index"""
        uv_layer_count = len(self.vertices[0].uv)
        if uv_index >= uv_layer_count:
            # If lacking 2 UV layers, mark them as null
            return Array("null, ; No UV%d" % (uv_index+1), "", "")

        uv_vals = Array("Vector2Array(")
        for vert in self.vertices:
            uv_vals.extend([
                vert.uv[uv_index].x,
                1.0-vert.uv[uv_index].y
            ])

        return uv_vals

    def generate_lines(self):
        """Generates the various arrays that are part of the surface (eg
        normals, position etc.)"""
        surface_lines = Array(
            prefix='[\n\t\t', seperator=',\n\t\t', suffix='\n\t]'
        )

        position_vals = Array("Vector3Array(",
                              values=[v.vertex for v in self.vertices])
        #normal_vals = Array("Vector3Array(",
        #                    values=[v.normal for v in self.vertices])

        surface_lines.append(position_vals.to_string())
        #surface_lines.append(normal_vals.to_string())
        surface_lines.append("null, ; No Normals")
        surface_lines.append(self.get_tangent_array().to_string())
        surface_lines.append(self.get_color_array().to_string())

        surface_lines.append(self.get_uv_array(0).to_string())
        surface_lines.append(self.get_uv_array(1).to_string())

        surface_lines.append("null, ; No Bones")
        surface_lines.append("null, ; No Bone Weights")


        # Indices- each face is made of 3 verts, and these are the indices
        # in the vertex arrays. The backface is computed from the winding
        # order, hence v[2] before v[1]
        if self.indices:
            face_indices = Array(
                "IntArray(",
                values=[[v[0], v[2], v[1]] for v in self.indices]
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
        surface_object['primitive'] = 5  # triangle strip
        surface_object['arrays'] = self.vertex_data
        surface_object['morph_arrays'] = self.morph_arrays
        return surface_object

    def to_string(self):
        """Serialize"""
        return self.generate_object().to_string()

# PRIMITIVE_POINTS = 0 — Render array as points (one vertex equals one point).
# PRIMITIVE_LINES = 1 — Render array as lines (every two vertices a line is created).
# PRIMITIVE_LINE_STRIP = 2 — Render array as line strip.
# PRIMITIVE_LINE_LOOP = 3 — Render array as line loop (like line strip, but closed).
# PRIMITIVE_TRIANGLES = 4 — Render array as triangles (every three vertices a triangle is created).
# PRIMITIVE_TRIANGLE_STRIP = 5 — Render array as triangle strips.
# PRIMITIVE_TRIANGLE_FAN = 6 — Render array as triangle fans.

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
