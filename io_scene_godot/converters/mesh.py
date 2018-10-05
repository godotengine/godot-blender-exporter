"""Exports a normal triangle mesh"""
import logging
import bpy
import bmesh
import mathutils

from .material import export_material
from ..structures import (Array, NodeTemplate, InternalResource, NodePath,
                          Map)
from . import physics
from . import armature
from . import animation

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
        mesh_node = NodeTemplate(node.name, "MeshInstance", parent_gd_node)
        mesh_exporter = MeshResourceExporter(node)

        armature_data = get_modifier_armature_data(node)
        if ("ARMATURE" in export_settings['object_types'] and
                armature_data is not None):
            skeleton_node = armature.find_skeletion_node(parent_gd_node)
            mesh_exporter.init_mesh_bones_data(skeleton_node)
            mesh_node['skeleton'] = NodePath(
                mesh_node.get_path(), skeleton_node.get_path())

        mesh_id = mesh_exporter.export_mesh(escn_file, export_settings)

        mesh_node['mesh'] = "SubResource({})".format(mesh_id)
        mesh_node['visible'] = not node.hide
        if not physics.has_physics(node) or not physics.is_physics_root(node):
            mesh_node['transform'] = node.matrix_local
        else:
            mesh_node['transform'] = mathutils.Matrix.Identity(4)
        escn_file.add_node(mesh_node)

        export_object_link_material(
            escn_file, export_settings, node, mesh_node
        )

        # export shape key animation
        if (export_settings['use_export_shape_key'] and
                node.data.shape_keys is not None):
            animation.export_animation_data(
                escn_file, export_settings, mesh_node,
                node.data.shape_keys, 'shapekey')

        return mesh_node


def triangulate_mesh(mesh):
    """Triangulate a mesh"""
    tri_mesh = bmesh.new()
    tri_mesh.from_mesh(mesh)
    bmesh.ops.triangulate(tri_mesh, faces=tri_mesh.faces, quad_method=2)
    tri_mesh.to_mesh(mesh)
    tri_mesh.free()

    mesh.update(calc_tessface=True)


def fix_vertex(vtx):
    """Changes a single position vector from y-up to z-up"""
    return mathutils.Vector((vtx.x, vtx.z, -vtx.y))


def get_modifier_armature_data(mesh_object):
    """Get the armature modifier of a blender object
    if does not have one, return None"""
    for modifier in mesh_object.modifiers:
        if isinstance(modifier, bpy.types.ArmatureModifier):
            return modifier.object.data
    return None


def export_object_link_material(escn_file, export_settings, mesh_object,
                                gd_node):
    """Export object linked material, if multiple object link material,
    only export the first one in the material slots"""
    mesh_resource_id = escn_file.get_internal_resource(mesh_object.data)
    mesh_resource = escn_file.internal_resources[mesh_resource_id - 1]
    for index, slot in enumerate(mesh_object.material_slots):
        if slot.link == 'OBJECT' and slot.material is not None:
            surface_id = mesh_resource.get_surface_id(index)
            if surface_id is not None:
                gd_node['material/{}'.format(surface_id)] = export_material(
                    escn_file,
                    export_settings,
                    slot.material
                )


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


class MeshResourceExporter:
    """Export a mesh resource from a blender mesh object"""
    def __init__(self, mesh_object):
        # blender mesh object
        self.object = mesh_object

        self.mesh_resource = None
        self.has_tangents = False
        self.vgroup_to_bone_mapping = dict()

    def init_mesh_bones_data(self, skeleton_node):
        """Find the mapping relation between vertex groups
        and bone id"""
        for bone_name, bone_id in skeleton_node.bone_name_to_id_map.items():
            group = self.object.vertex_groups.get(bone_name)
            if group is not None:
                self.vgroup_to_bone_mapping[group.index] = bone_id

    def export_mesh(self, escn_file, export_settings):
        """Saves a mesh into the escn file """
        # Check if it exists so we don't bother to export it twice
        mesh = self.object.data
        mesh_id = escn_file.get_internal_resource(mesh)

        if mesh_id is not None:
            return mesh_id

        self.mesh_resource = ArrayMeshResource(mesh.name)

        self.make_arrays(
            escn_file,
            export_settings,
        )

        mesh_id = escn_file.add_internal_resource(self.mesh_resource, mesh)
        assert mesh_id is not None

        return mesh_id

    def make_arrays(self, escn_file, export_settings):
        """Generates arrays of positions, normals etc"""
        armature_data = get_modifier_armature_data(self.object)
        if armature_data is not None:
            original_pose_position = armature_data.pose_position
            armature_data.pose_position = 'REST'
            bpy.context.scene.update()

        if not export_settings['use_mesh_modifiers']:
            for modifier in self.object.modifiers:
                if not isinstance(modifier, bpy.types.ArmatureModifier):
                    modifier.show_render = False

        mesh = self.object.to_mesh(bpy.context.scene,
                                   True,
                                   "RENDER")

        # if the original mesh has an object link material,
        # the new created mesh would use it as data link material,
        # seems a bug of Blender,
        # here is a simple fix, not sure if it is robust enough..
        for idx in range(len(mesh.materials)):
            mesh.materials[idx] = self.object.data.materials[idx]

        # Prepare the mesh for export
        triangulate_mesh(mesh)

        # godot engine supports two uv channels
        uv_layer_count = min(len(mesh.uv_textures), 2)

        if mesh.uv_textures:
            self.has_tangents = True
            try:
                mesh.calc_tangents()
            except RuntimeError:
                # This fails if the mesh is a single vertex (and presumably an
                # edge). Since this won't be rendered by visualserver (the only
                # user of the tangents), we'll just disable tangents and hope
                # for the best....
                self.has_tangents = False
        else:
            mesh.calc_normals_split()
            self.has_tangents = False

        # Separate by materials into single-material surfaces
        self.generate_surfaces(
            escn_file,
            export_settings,
            mesh
        )

        bpy.data.meshes.remove(mesh)

        if armature_data is not None:
            armature_data.pose_position = original_pose_position
            bpy.context.scene.update()

    @staticmethod
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

    @staticmethod
    def validate_morph_mesh_modifiers(mesh_object):
        """Check whether a mesh has modifiers not
        compatible with shape key"""
        # this black list is not complete
        modifiers_not_supported = (
            bpy.types.SubsurfModifier,
        )
        for modifier in mesh_object.modifiers:
            if isinstance(modifier, modifiers_not_supported):
                return False
        return True

    @staticmethod
    def intialize_surfaces_morph_data(surfaces):
        """Initialize a list of empty morph for surfaces"""
        surfaces_morph_list = [VerticesArrays() for _ in range(len(surfaces))]

        for index, morph in enumerate(surfaces_morph_list):
            morph.vertices = [None] * len(surfaces[index].vertex_data.vertices)

        return surfaces_morph_list

    def export_morphs(self, export_settings, surfaces):
        """Export shape keys in mesh node and append them to surfaces"""
        if export_settings['use_mesh_modifiers']:
            if not self.validate_morph_mesh_modifiers(
                    self.object):
                logging.warning(
                    "Mesh object '%s' has modifiers "
                    "incompatible with shape key",
                    self.object.name
                )

        self.mesh_resource["blend_shape/names"] = Array(
            prefix="PoolStringArray(", suffix=')'
        )
        self.mesh_resource["blend_shape/mode"] = 0

        shape_keys_to_export = self.extract_shape_keys(
            self.object.data.shape_keys
        )
        for index, shape_key in shape_keys_to_export:
            self.mesh_resource["blend_shape/names"].append(
                '"{}"'.format(shape_key.name)
            )

            self.object.show_only_shape_key = True
            self.object.active_shape_key_index = index
            shape_key.value = 1.0

            shape_key_mesh = self.object.to_mesh(
                bpy.context.scene,
                True,
                "RENDER"
            )

            triangulate_mesh(shape_key_mesh)

            if self.has_tangents:
                shape_key_mesh.calc_tangents()
            else:
                shape_key_mesh.calc_normals_split()

            surfaces_morph_data = self.intialize_surfaces_morph_data(surfaces)

            for face in shape_key_mesh.polygons:
                surface_index = self.mesh_resource.get_surface_id(
                    face.material_index
                )

                surface = surfaces[surface_index]
                morph = surfaces_morph_data[surface_index]

                for loop_id in range(face.loop_total):
                    loop_index = face.loop_start + loop_id
                    new_vert = Vertex.create_from_mesh_loop(
                        shape_key_mesh,
                        loop_index,
                        self.has_tangents,
                        self.vgroup_to_bone_mapping
                    )

                    vertex_index = surface.vertex_index_map[loop_index]

                    morph.vertices[vertex_index] = new_vert

            for surf_index, surf in enumerate(surfaces):
                surf.morph_arrays.append(surfaces_morph_data[surf_index])

            bpy.data.meshes.remove(shape_key_mesh)

    def generate_surfaces(self, escn_file, export_settings, mesh):
        """Splits up the mesh into surfaces with a single material each.
        Within this, it creates the Vertex structure to contain all data about
        a single vertex
        """
        surfaces = []

        for face_index in range(len(mesh.polygons)):
            face = mesh.polygons[face_index]

            # Find a surface that matches the material, otherwise create a new
            # surface for it
            surface_index = self.mesh_resource.get_surface_id(
                face.material_index
            )
            if surface_index is None:
                surface_index = len(surfaces)
                self.mesh_resource.set_surface_id(
                    face.material_index, surface_index
                )
                surface = Surface()
                surface.id = surface_index
                surfaces.append(surface)
                if mesh.materials:
                    mat = mesh.materials[face.material_index]
                    if mat is not None:
                        surface.material = export_material(
                            escn_file,
                            export_settings,
                            mat
                        )

            surface = surfaces[surface_index]
            vertex_indices = []

            for loop_id in range(face.loop_total):
                loop_index = face.loop_start + loop_id

                new_vert = Vertex.create_from_mesh_loop(
                    mesh,
                    loop_index,
                    self.has_tangents,
                    self.vgroup_to_bone_mapping
                )

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

        if (export_settings['use_export_shape_key'] and
                self.object.data.shape_keys):
            self.export_morphs(export_settings, surfaces)

        has_bone = True if self.vgroup_to_bone_mapping else False
        for surface in surfaces:
            surface.vertex_data.has_bone = has_bone
            for vert_array in surface.morph_arrays:
                vert_array.has_bone = has_bone

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
        surface_lines = Array(
            prefix='[\n\t\t', seperator=',\n\t\t', suffix='\n\t]'
        )

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

            # totalw guaranteed to be not zero
            totalw = 0.0
            for index, weight in enumerate(weights):
                if index >= MAX_BONE_PER_VERTEX:
                    break
                totalw += weight[1]

            for i in range(MAX_BONE_PER_VERTEX):
                if i < len(weights):
                    bone_idx_array.append(weights[i][0])
                    bone_ws_array.append(weights[i][1]/totalw)
                else:
                    bone_idx_array.append(0)
                    bone_ws_array.append(0.0)

        return bone_idx_array, bone_ws_array

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
        surface_object['primitive'] = 4
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
        for bone in self.bones:
            tup = tup + (float(bone), )
        for weight in self.weights:
            tup = tup + (float(weight), )

        return tup

    @classmethod
    def create_from_mesh_loop(cls, mesh, loop_index, has_tangents,
                              gid_to_bid_map):
        """Create a vertex from a blender mesh loop"""
        new_vert = cls()

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
            if (vertex_group.group in gid_to_bid_map and
                    vertex_group.weight != 0.0):
                new_vert.bones.append(gid_to_bid_map[vertex_group.group])
                new_vert.weights.append(vertex_group.weight)

        if gid_to_bid_map and not new_vert.weights:
            # vertex not assign to any bones
            logging.warning(
                "No bone assigned vertex detected in mesh '%s' "
                "at local position %s.",
                mesh.name,
                str(mesh.vertices[loop.vertex_index].co)
            )

        return new_vert

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
