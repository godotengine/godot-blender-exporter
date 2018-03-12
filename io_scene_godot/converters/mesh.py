import logging
import bpy
import bmesh
import mathutils

from .material import export_material
from ..structures import Array, NodeTemplate, InternalResource
from . import physics


# ------------------------------- The Mesh -----------------------------------
def export_mesh_node(escn_file, export_settings, node, parent_path):
    """Exports a MeshInstance. If the mesh is not already exported, it will
    trigger the export of that mesh"""
    if node.data is None:
        return parent_path

    # If this mesh object has physics properties, we need to export them first
    # because they need to be higher in the scene-tree
    if physics.has_physics(node):
        parent_path = physics.export_physics_properties(
            escn_file, export_settings, node, parent_path
        )

    if node.hide_render:
        return parent_path

    else:
        armature = None
        if node.parent is not None and node.parent.type == "ARMATURE":
            armature = node.parent

        mesh_id = export_mesh(escn_file, export_settings, node, armature)  # We need to export the mesh

        mesh_node = NodeTemplate(node.name, "MeshInstance", parent_path)
        mesh_node.mesh = "SubResource({})".format(mesh_id)
        if not physics.is_physics_root(node):
            mesh_node.transform = node.matrix_local
        else:
            mesh_node.transform = mathutils.Matrix.Identity(4)
        escn_file.add_node(mesh_node)

        return parent_path + '/' + node.name


def export_mesh(escn_file, export_settings, node, armature):
    """Saves a mesh into the escn file """
    # Check if it exists so we don't bother to export it twice
    mesh = node.data
    mesh_id = escn_file.get_internal_resource(mesh)
    if mesh_id is not None:
        return mesh_id

    mesh_resource = InternalResource('ArrayMesh')

    mesh_lines = []
    mesh_materials = []
    make_arrays(node, armature, mesh_lines, mesh_materials)


    for i in range(len(mesh_lines)):
        mesh_resource.contents += "surfaces/" + str(i) + "={\n"
        if mesh_materials[i] is not None:
            mat_resource = export_material(escn_file, export_settings, mesh_materials[i])
            mesh_resource.contents += "\t" + "\"material\":" + mat_resource + ",\n"
        mesh_resource.contents += "\t" + "\"primitive\":4,\n"
        mesh_resource.contents += "\t" + "\"arrays\":[\n"
        for sline in mesh_lines[i]:
            mesh_resource.contents += "\t\t" + sline + "\n"
        mesh_resource.contents += "\t" + "],\n"
        mesh_resource.contents += "\t" + "\"morph_arrays\":[]\n"
        mesh_resource.contents += "}\n"

    mesh_id = escn_file.add_internal_resource(mesh_resource, mesh)
    assert mesh_id is not None

    return mesh_id


def make_arrays(node, armature, mesh_lines, ret_materials, skeyindex=-1):

    mesh = node.to_mesh(bpy.context.scene,
                        True,  # Apply Modifiers. TODO: make this an option
                        "RENDER")  # TODO: Review

    if True:  # Triangulate, always
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.triangulate(bm, faces=bm.faces)
        bm.to_mesh(mesh)
        bm.free()

    surfaces = []
    material_to_surface = {}

    mesh.update(calc_tessface=True)

    si = None
    #if armature is not None:
    #    si = self.skeleton_info[armature]

    # TODO: Implement automatic tangent detection
    has_tangents = True  # always use tangents, we are grown up now.

    has_colors = len(mesh.vertex_colors)

    uv_layer_count = len(mesh.uv_textures)
    if uv_layer_count > 2:
        uv_layer_count = 2

    if has_tangents and len(mesh.uv_textures):
        try:
            mesh.calc_tangents()
        except:
            logging.warning(
                "CalcTangets failed for mesh %s, no tangets will be "
                "exported.", mesh.name
            )
            mesh.calc_normals_split()
            has_tangents = False

    else:
        mesh.calc_normals_split()
        has_tangents = False

    for face_index in range(len(mesh.polygons)):
        face = mesh.polygons[face_index]

        if face.material_index not in material_to_surface:
            material_to_surface[face.material_index] = len(surfaces)
            surfaces.append(Surface())
            if mesh.materials:
                mat = mesh.materials[face.material_index]
                ret_materials.append(mat)
            else:
                ret_materials.append(None)

        surface = surfaces[material_to_surface[face.material_index]]
        vi = []

        for lt in range(face.loop_total):
            loop_index = face.loop_start + lt
            ml = mesh.loops[loop_index]
            mv = mesh.vertices[ml.vertex_index]

            v = Vertex()
            v.vertex = fix_vertex(mathutils.Vector(mv.co))

            for xt in mesh.uv_layers:
                v.uv.append(mathutils.Vector(xt.data[loop_index].uv))

            if has_colors:
                v.color = mathutils.Vector(
                    mesh.vertex_colors[0].data[loop_index].color)

            v.normal = fix_vertex(mathutils.Vector(ml.normal))

            if has_tangents:
                v.tangent = fix_vertex(mathutils.Vector(ml.tangent))
                v.bitangent = fix_vertex(mathutils.Vector(ml.bitangent))

            tup = v.get_tup()
            idx = 0
            # Do not optmize if using shapekeys
            if skeyindex == -1 and tup in surface.vertex_map:
                idx = surface.vertex_map[tup]
            else:
                idx = len(surface.vertices)
                surface.vertices.append(v)
                surface.vertex_map[tup] = idx

            vi.append(idx)

        if len(vi) > 2:  # Only triangles and above
            surface.indices.append(vi)

    for s in surfaces:
        mesh_lines.append(s.generate_lines(has_tangents, has_colors, uv_layer_count, armature))

    bpy.data.meshes.remove(mesh)


class Surface:
    """A surface is a single part of a mesh (eg in blender, one mesh can have
    multiple materials. Godot calls these separate parts separate surfaces"""
    def __init__(self):
        self.vertices = []
        self.vertex_map = {}
        self.indices = []

    def calc_tangent_dp(self, vert):
        """Calculates the dot product of the tangent. I think this has
        something to do with normal mapping"""
        cross_product = vert.normal.cross(vert.tangent)
        dot_product = cross_product.dot(vert.bitangent)
        return 1.0 if dot_product > 0.0 else -1.0

    def generate_lines(self, has_tangents, has_colors, uv_layer_count, armature):
        surface_lines = []

        position_vals = Array("Vector3Array(", values=[v.vertex for v in self.vertices])
        normal_vals = Array("Vector3Array(", values=[v.normal for v in self.vertices])


        if has_tangents:
            tangent_vals = Array("FloatArray(")
            for vert in self.vertices:
                tangent_vals.extend(list(vert.tangent) + [self.calc_tangent_dp(vert)])
        else:
            tangent_vals = Array("null, ; No Tangents", "", "")

        if has_colors:
            color_vals = Array("ColorArray(")
            for vert in self.vertices:
                color_vals.extend(list(vert.color)+[1.0])
        else:
            color_vals = Array("null, ; no Vertex Colors", "", "")

        surface_lines.append(position_vals.to_string())
        surface_lines.append(normal_vals.to_string())
        surface_lines.append(tangent_vals.to_string())
        surface_lines.append(color_vals.to_string())

        # UV Arrays
        for i in range(2):  # Godot always expects two arrays for UV's
            if i >= uv_layer_count:
                # but if there aren't enough in blender, make one of them into null
                surface_lines.append("null, ; No UV"+str(i+1))
                continue
            uv_vals = Array("Vector2Array(", ", ", "),")
            for vert in self.vertices:
                uv_vals.extend([vert.uv[i].x, -vert.uv[i].y])

            surface_lines.append(uv_vals.to_string())

        # Bones and Weights
        # Export armature data (if armature exists)
        if armature is not None:
            # Skin Weights!
            float_values = "FloatArray("
            float_valuesw = "FloatArray("
            first = True
            for vert in self.vertices:
                #skin_weights_total += len(v.weights)
                weights = []
                for i in len(vert.bones):
                    weights += (vert.bones[i], vert.weights[i])

                weights = sorted(weights, key=lambda x: -x[1])
                totalw = 0.0
                for weight in weights:
                    totalw += weight[1]
                if totalw == 0.0:
                    totalw = 0.000000001

                for i in range(4):
                    if i > 0:
                        float_values += ","
                        float_valuesw += ","
                    if i < len(weights):
                        float_values += " {}".format(weights[i][0])
                        float_valuesw += " {}".format(weights[i][1]/totalw)
                    else:
                        float_values += " 0"
                        float_valuesw += " 0.0"

                if not first:
                    float_values += ","
                    float_valuesw += ","
                else:
                    first = False

            float_values += "),"
            surface_lines.append(float_values)
            float_valuesw += "),"
            surface_lines.append(float_valuesw)

        else:
            surface_lines.append("null, ; No Bones")
            surface_lines.append("null, ; No Weights")

        # Indices- each face is made of 3 verts, and these are the indices
        # in the vertex arrays. The backface is computed from the winding
        # order, hence v[2] before v[1]
        int_values = Array(
            "IntArray(", 
            values=[[v[0], v[2], v[1]] for v in self.indices]
        )
        surface_lines.append(int_values.to_string())

        return surface_lines


CMP_EPSILON = 0.0001


def fix_vertex(vtx):
    """Changes a single position vector from y-up to z-up"""
    return mathutils.Vector((vtx.x, vtx.z, -vtx.y))


class Vertex:
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
                 "uv2", "bones", "weights")

    def __init__(self):
        self.vertex = mathutils.Vector((0.0, 0.0, 0.0))
        self.normal = mathutils.Vector((0.0, 0.0, 0.0))
        self.tangent = None
        self.bitangent = None
        self.color = None
        self.uv = []
        self.uv2 = mathutils.Vector((0.0, 0.0))
        self.bones = []
        self.weights = []
