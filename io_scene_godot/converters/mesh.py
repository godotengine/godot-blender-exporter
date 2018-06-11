"""Exports a normal triangle mesh"""
import bpy
import bmesh
import mathutils

from .material import export_material
from ..structures import (Array, NodeTemplate, InternalResource, NodePath,
                          ValidationError)
from . import physics
from . import armature

MAX_BONE_PER_VERTEX = 4


# ------------------------------- The Mesh -----------------------------------
def export_mesh_node(escn_file, export_settings, node, parent_gd_node):
    """Exports a MeshInstance. If the mesh is not already exported, it will
    trigger the export of that mesh"""
    if (node.data is None or
            "MESH" not in export_settings['object_types']):
        return parent_gd_node

    # If this mesh object has physics properties, we need to export them first
    # because they need to be higher in the scene-tree
    if physics.has_physics(node):
        parent_gd_node = physics.export_physics_properties(
            escn_file, export_settings, node, parent_gd_node
        )

    if (node.hide_render or
            (physics.has_physics(node) and node.draw_type == "WIRE")):
        return parent_gd_node

    else:
        armature_data = armature.get_armature_data(node)

        skeleton_node = None
        if ("ARMATURE" in export_settings['object_types'] and
                armature_data is not None):
            skeleton_node = armature.find_skeletion_node(parent_gd_node)

        mesh_id = export_mesh(
            escn_file,
            export_settings,
            skeleton_node,
            node
        )

        mesh_node = NodeTemplate(node.name, "MeshInstance", parent_gd_node)
        mesh_node['mesh'] = "SubResource({})".format(mesh_id)
        mesh_node['visible'] = not node.hide
        if skeleton_node is not None:
            mesh_node['skeleton'] = NodePath(
                mesh_node.get_path(), skeleton_node.get_path())
        if not physics.has_physics(node) or not physics.is_physics_root(node):
            mesh_node['transform'] = node.matrix_local
        else:
            mesh_node['transform'] = mathutils.Matrix.Identity(4)
        escn_file.add_node(mesh_node)

        return mesh_node


def export_mesh(escn_file, export_settings, skeleton_node, node):
    """Saves a mesh into the escn file """
    # Check if it exists so we don't bother to export it twice
    mesh = node.data
    mesh_id = escn_file.get_internal_resource(mesh)

    if mesh_id is not None:
        return mesh_id

    mesh_resource = InternalResource('ArrayMesh')

    surfaces = make_arrays(
        escn_file,
        export_settings,
        skeleton_node,
        node)

    if export_settings['export_shape_key'] and node.data.shape_keys:
        mesh_resource["blend_shape/names"] = Array(prefix="PoolStringArray(")
        mesh_resource["blend_shape/mode"] = 0
        for _, shape_key in extract_shape_keys(node.data.shape_keys):
            mesh_resource["blend_shape/names"].append(
                '"{}"'.format(shape_key.name))

    for surface in surfaces:
        mesh_resource[surface.name_str] = surface

    mesh_id = escn_file.add_internal_resource(mesh_resource, mesh)
    assert mesh_id is not None

    return mesh_id


def triangulate_mesh(mesh):
    """Triangulate a mesh"""
    tri_mesh = bmesh.new()
    tri_mesh.from_mesh(mesh)
    bmesh.ops.triangulate(tri_mesh, faces=tri_mesh.faces, quad_method=2)
    tri_mesh.to_mesh(mesh)
    tri_mesh.free()

    mesh.update(calc_tessface=True)


def find_bone_vertex_groups(vertex_groups, skeleton_node):
    """Find the id of vertex groups connected to bone weights,
    return a dict() mapping from vertex_group id to bone id"""
    ret = dict()
    if skeleton_node is not None:
        # the bone's index in the bones list is exported as the id
        for bone_name, bone_id in skeleton_node.bone_name_to_id_map.items():
            group = vertex_groups.get(bone_name)
            if group is not None:
                ret[group.index] = bone_id
    return ret


def make_arrays(escn_file, export_settings, skeleton_node, node):
    """Generates arrays of positions, normals etc"""
    armature_data = armature.get_armature_data(node)
    if armature_data is not None:
        original_pose_position = armature_data.pose_position
        armature_data.pose_position = 'REST'
        bpy.context.scene.update()

    mesh = node.to_mesh(bpy.context.scene,
                        export_settings['use_mesh_modifiers'],
                        "RENDER")

    # Prepare the mesh for export
    triangulate_mesh(mesh)

    uv_layer_count = len(mesh.uv_textures)
    if uv_layer_count > 2:
        uv_layer_count = 2

    if mesh.uv_textures:
        has_tangents = True
        mesh.calc_tangents()
    else:
        mesh.calc_normals_split()
        has_tangents = False

    # find the vertex group id of bone weights
    gid_to_bid_map = find_bone_vertex_groups(
        node.vertex_groups, skeleton_node)

    # Separate by materials into single-material surfaces
    surfaces = generate_surfaces(
        escn_file,
        export_settings,
        mesh,
        has_tangents,
        gid_to_bid_map
    )

    if (export_settings['export_shape_key'] and
            node.data.shape_keys is not None):
        export_morphs(
            export_settings, node, surfaces, has_tangents, gid_to_bid_map)

    has_bone = True if armature_data is not None else False

    for surface_id, surface in enumerate(surfaces):
        surface.id = surface_id
        surface.vertex_data.has_bone = has_bone
        for vert_data in surface.morph_arrays:
            vert_data.has_bone = has_bone

    bpy.data.meshes.remove(mesh)

    if armature_data is not None:
        armature_data.pose_position = original_pose_position
        bpy.context.scene.update()

    return surfaces


def extract_shape_keys(blender_shape_keys):
    """Return a list of (shape_key_index, shape_key_object) each of them
    is a shape key needs exported"""
    # base shape key needn't be exported
    ret = list()
    base_key = blender_shape_keys.reference_key
    for index, shape_key in enumerate(blender_shape_keys.key_blocks):
        if shape_key != base_key:
            ret.append((index, shape_key))
    return ret


def intialize_surfaces_morph_data(surfaces):
    """Initialize a list of empty morph for surfaces"""
    surfaces_morph_list = [VerticesArrays() for _ in range(len(surfaces))]

    for index, morph in enumerate(surfaces_morph_list):
        morph.vertices = [None] * len(surfaces[index].vertex_data.vertices)

    return surfaces_morph_list


def export_morphs(export_settings, node, surfaces, has_tangents,
                  gid_to_bid_map):
    """Export shape keys in mesh node and append them to surfaces"""
    for index, shape_key in extract_shape_keys(node.data.shape_keys):

        node.show_only_shape_key = True
        node.active_shape_key_index = index
        shape_key.value = 1.0

        mesh = node.to_mesh(bpy.context.scene,
                            export_settings['use_mesh_modifiers'],
                            "RENDER")
        triangulate_mesh(mesh)

        if has_tangents:
            mesh.calc_tangents()
        else:
            mesh.calc_normals_split()

        surfaces_morph_data = intialize_surfaces_morph_data(surfaces)

        for face in mesh.polygons:
            surface_index = -1
            for surf_index, surf in enumerate(surfaces):
                # todo:
                # use the `material_to_surface` map from `generate_surfaces`
                if surf.face_material_index == face.material_index:
                    surface_index = surf_index
                    break

            if surface_index != -1:
                surface = surfaces[surface_index]
                morph = surfaces_morph_data[surface_index]

                for loop_id in range(face.loop_total):
                    loop_index = face.loop_start + loop_id
                    new_vert = VerticesArrays.create_vertex_from_loop(
                        mesh, loop_index, has_tangents, gid_to_bid_map
                    )

                    vertex_index = surface.vertex_index_map[loop_index]

                    morph.vertices[vertex_index] = new_vert

        for surf_index, surf in enumerate(surfaces):
            surf.morph_arrays.append(surfaces_morph_data[surf_index])

        bpy.data.meshes.remove(mesh)


def generate_surfaces(escn_file, export_settings, mesh, has_tangents,
                      gid_to_bid_map):
    """Splits up the mesh into surfaces with a single material each.
    Within this, it creates the Vertex structure to contain all data about
    a single vertex
    """
    material_to_surface = {}
    surfaces = []

    for face_index in range(len(mesh.polygons)):
        face = mesh.polygons[face_index]

        # Find a surface that matches the material, otherwise create a new
        # surface for it
        if face.material_index not in material_to_surface:
            material_to_surface[face.material_index] = len(surfaces)
            surface = Surface()
            surface.face_material_index = face.material_index
            surfaces.append(surface)
            if mesh.materials:
                mat = mesh.materials[face.material_index]
                if mat is not None:
                    surface.material = export_material(
                        escn_file,
                        export_settings,
                        mat
                    )

        surface = surfaces[material_to_surface[face.material_index]]
        vertex_indices = []

        for loop_id in range(face.loop_total):
            loop_index = face.loop_start + loop_id

            new_vert = VerticesArrays.create_vertex_from_loop(
                mesh, loop_index, has_tangents, gid_to_bid_map)

            # Merge similar vertices
            tup = new_vert.get_tup()
            if tup not in surface.vertex_map:
                surface.vertex_map[tup] = len(surface.vertex_data.vertices)
                surface.vertex_data.vertices.append(new_vert)

            vertex_index = surface.vertex_map[tup]
            surface.vertex_index_map[loop_index] = vertex_index

            vertex_indices.append(vertex_index)

        if len(vertex_indices) > 2:  # Only triangles and above
            surface.vertex_data.indices.append(vertex_indices)

    return surfaces


class VerticesArrays:
    """Godot use several arrays to store the data of a surface(e.g. vertices,
    indices, bone weights). A surface object has a single VerticesArrays as its
    default and also may have a morph array with a list of VerticesArrays"""
    def __init__(self):
        self.vertices = []
        self.indices = []
        self.has_bone = False

    @staticmethod
    def create_vertex_from_loop(mesh, loop_index, has_tangents,
                                gid_to_bid_map):
        """Create a vertex from a blender mesh loop"""
        new_vert = Vertex()

        loop = mesh.loops[loop_index]
        new_vert.vertex = fix_vertex(mesh.vertices[loop.vertex_index].co)

        for uv_layer in mesh.uv_layers:
            new_vert.uv.append(mathutils.Vector(
                uv_layer.data[loop_index].uv
            ))

        if mesh.vertex_colors:
            new_vert.color = mathutils.Vector(
                mesh.vertex_colors[0].data[loop_index].color)

        new_vert.normal = fix_vertex(loop.normal)

        if has_tangents:
            new_vert.tangent = fix_vertex(loop.tangent)
            new_vert.bitangent = fix_vertex(loop.bitangent)

        for vertex_group in mesh.vertices[loop.vertex_index].groups:
            if vertex_group.group in gid_to_bid_map:
                new_vert.bones.append(gid_to_bid_map[vertex_group.group])
                new_vert.weights.append(vertex_group.weight)

        return new_vert

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
            return Array("null, ; No UV"+str(uv_index+1), "", "")

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
        surface_lines = []

        position_vals = Array("Vector3Array(",
                              values=[v.vertex for v in self.vertices])
        normal_vals = Array("Vector3Array(",
                            values=[v.normal for v in self.vertices])

        surface_lines.append(position_vals.to_string())
        surface_lines.append(normal_vals.to_string())
        surface_lines.append(self.get_tangent_array().to_string())
        surface_lines.append(self.get_color_array().to_string())

        surface_lines.append(self.get_uv_array(0).to_string())
        surface_lines.append(self.get_uv_array(1).to_string())

        # Bones and Weights
        # Export armature data (if armature exists)
        bones, bone_weights = self._get_bone_arrays()

        surface_lines.append(bones.to_string())
        surface_lines.append(bone_weights.to_string())

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

    def _get_bone_arrays(self):
        """Returns the most influential bones and their weights"""
        if not self.has_bone:
            return [
                Array("null, ; No Bones", "", ""),
                Array("null, ; No Weights", "", "")
            ]

        # Skin Weights
        bone_idx_array = Array("IntArray(")
        bone_ws_array = Array("FloatArray(")
        for vert in self.vertices:
            weights = []
            for i in range(len(vert.bones)):
                weights.append((vert.bones[i], vert.weights[i]))

            weights = sorted(weights, key=lambda x: x[1], reverse=True)
            totalw = 0.0
            for index, weight in enumerate(weights):
                if index >= MAX_BONE_PER_VERTEX:
                    break
                totalw += weight[1]

            if totalw > 0.0:
                for i in range(MAX_BONE_PER_VERTEX):
                    if i < len(weights):
                        bone_idx_array.append(weights[i][0])
                        bone_ws_array.append(weights[i][1]/totalw)
                    else:
                        bone_idx_array.append(0)
                        bone_ws_array.append(0.0)
            else:
                # vertex not assign to any bones
                raise ValidationError(
                    "There are vertices with no bone weight in rigged mesh, "
                    "please fix them in Blender"
                )

        return bone_idx_array, bone_ws_array

    def to_string(self):
        """Serialize"""
        return "[\n\t\t{}\n\t]".format(",\n\t\t".join(self.generate_lines()))


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
        self.face_material_index = -1

    @property
    def name_str(self):
        """Used to separate surfaces that are part of the same mesh by their
        id"""
        return "surfaces/" + str(self.id)

    def to_string(self):
        """Serialize"""
        out_str = "{\n"
        if self.material is not None:

            out_str += "\t\"material\":" + self.material + ",\n"
        out_str += "\t\"primitive\":4,\n"
        out_str += "\t\"arrays\":" + self.vertex_data.to_string() + ",\n"
        out_str += "\t" + "\"morph_arrays\":"
        out_str += self.morph_arrays.to_string()
        out_str += "\n"
        out_str += "}\n"

        return out_str


def fix_vertex(vtx):
    """Changes a single position vector from y-up to z-up"""
    return mathutils.Vector((vtx.x, vtx.z, -vtx.y))


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
        for bone in self.bones:
            tup = tup + (float(bone), )
        for weight in self.weights:
            tup = tup + (float(weight), )

        return tup

    __slots__ = ("vertex", "normal", "tangent", "bitangent", "color", "uv",
                 "bones", "weights")

    def __init__(self):
        self.vertex = mathutils.Vector((0.0, 0.0, 0.0))
        self.normal = mathutils.Vector((0.0, 0.0, 0.0))
        self.tangent = None
        self.bitangent = None
        self.color = None
        self.uv = []
        self.bones = []
        self.weights = []
