# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# ##### END GPL LICENSE BLOCK #####

# Script copyright (C) Juan Linietsky
# Contact Info: juan@godotengine.org

"""
This script is an exporter to Godot Engine

http://www.godotengine.org
"""

import os
import math
import bpy
import bmesh
from mathutils import Vector, Matrix, Color

from .encoders import CONVERSIONS

# sections (in this order)
S_EXTERNAL_RES = 0
S_INTERNAL_RES = 1
S_NODES = 2

CMP_EPSILON = 0.0001


# Used to correct spotlights and cameras, which in blender are Z-forwards and
# in Godot are Y-forwards
AXIS_CORRECT = Matrix.Rotation(math.radians(-90), 4, 'X')


def fix_vertex(vtx):
    """Changes a single position vector from y-up to z-up"""
    return Vector((vtx.x, vtx.z, -vtx.y))


class SectionHeading:
    def __init__(self, section_type, **kwargs):
        self._type = section_type
        for key in kwargs:
            self.__dict__[key] = kwargs[key]

    def generate_prop_list(self):
        out_str = ''
        attribs = vars(self)
        for var in attribs:
            if var.startswith('_'):
                continue  # Ignore hidden variables
            val = attribs[var]
            converter = CONVERSIONS.get(type(val))
            if converter is not None:
                val = converter(val)

            # Extra wrapper for str's
            if type(val) == str:
                val = '"{}"'.format(val)

            out_str += ' {}={}'.format(var, val)

        return out_str

    def to_string(self):
        return '[{} {}]\n'.format(self._type, self.generate_prop_list())


class NodeTemplate:
    def __init__(self, name, node_type, parent_path):
        self._heading = SectionHeading(
            "node",
            name=name,
            type=node_type,
            parent=parent_path,
        )

    def generate_prop_list(self):
        out_str = ''
        attribs = vars(self)
        for var in attribs:
            if var.startswith('_'):
                continue  # Ignore hidden variables
            val = attribs[var]
            converter = CONVERSIONS.get(type(val))
            if converter is not None:
                val = converter(val)
            out_str += '\n{} = {}'.format(var, val)

        return out_str

    def to_string(self):
        return '{}\n{}\n\n'.format(
            self._heading.to_string(),
            self.generate_prop_list()
        )


class Array(list):
    def __init__(self, prefix, seperator=', ', suffix=')', values=()):
        self.prefix = prefix
        self.seperator = seperator
        self.suffix = suffix
        super().__init__(values)
        
    def to_string(self):
        return "{}{}{}".format(
            self.prefix, 
            self.seperator.join([str(v) for v in self]), 
            self.suffix
        )
        

class GodotExporter:

    def validate_id(self, d):
        if d.find("id-") == 0:
            return "z{}".format(d)
        return d

    def new_resource_id(self):
        self.last_res_id += 1
        return self.last_res_id

    def new_external_resource_id(self):
        self.last_ext_res_id += 1
        return self.last_ext_res_id

    class Vertex:

        def close_to(self, v):
            if self.vertex - v.vertex.length() > CMP_EPSILON:
                return False
            if self.normal - v.normal.length() > CMP_EPSILON:
                return False
            if self.uv - v.uv.length() > CMP_EPSILON:
                return False
            if self.uv2 - v.uv2.length() > CMP_EPSILON:
                return False

            return True

        def get_tup(self):
            tup = (self.vertex.x, self.vertex.y, self.vertex.z, self.normal.x,
                   self.normal.y, self.normal.z)
            for t in self.uv:
                tup = tup + (t.x, t.y)
            if self.color is not None:
                tup = tup + (self.color.x, self.color.y, self.color.z)
            if self.tangent is not None:
                tup = tup + (self.tangent.x, self.tangent.y, self.tangent.z)
            if self.bitangent is not None:
                tup = tup + (self.bitangent.x, self.bitangent.y,
                             self.bitangent.z)
            for t in self.bones:
                tup = tup + (float(t), )
            for t in self.weights:
                tup = tup + (float(t), )

            return tup

        __slots__ = ("vertex", "normal", "tangent", "bitangent", "color", "uv",
                     "uv2", "bones", "weights")

        def __init__(self):
            self.vertex = Vector((0.0, 0.0, 0.0))
            self.normal = Vector((0.0, 0.0, 0.0))
            self.tangent = None
            self.bitangent = None
            self.color = None
            self.uv = []
            self.uv2 = Vector((0.0, 0.0))
            self.bones = []
            self.weights = []

    def writel(self, section, indent, text):
        if section not in self.sections:
            self.sections[section] = []
        line = "{}{}".format(indent * "\t", text)
        self.sections[section].append(line)

    def purge_empty_nodes(self):
        sections = {}
        for k, v in self.sections.items():
            if not (len(v) == 2 and v[0][1:] == v[1][2:]):
                sections[k] = v
        self.sections = sections

    def export_image(self, image):
        img_id = self.image_cache.get(image)
        if img_id:
            return img_id

        imgpath = image.filepath
        if imgpath.startswith("//"):
            imgpath = bpy.path.abspath(imgpath)

        try:
            imgpath = os.path.relpath(imgpath, os.path.dirname(self.path)).replace("\\", "/")
        except:
            # TODO: Review, not sure why it fails - maybe try bpy.paths.abspath
            pass

        imgid = str(self.new_external_resource_id())

        self.image_cache[image] = imgid
        self.writel(S_EXTERNAL_RES, 0, '[ext_resource path="' + imgpath + '" type="Texture" id=' + imgid + ']')
        return imgid

    def export_material(self, material, double_sided_hint=True):
        material_id = self.material_cache.get(material)
        if material_id:
            return material_id

        material_id = str(self.new_resource_id())
        self.material_cache[material] = material_id

        self.writel(S_INTERNAL_RES, 0, '\n[sub_resource type="SpatialMaterial" id=' + material_id + ']\n')
        return material_id

    class Surface:
        def __init__(self):
            self.vertices = []
            self.vertex_map = {}
            self.indices = []

    def make_arrays(self, node, armature, mesh_lines, ret_materials, skeyindex=-1):

        mesh = node.to_mesh(self.scene, self.config["use_mesh_modifiers"],
                            "RENDER")  # TODO: Review
        self.temp_meshes.add(mesh)

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
        if armature is not None:
            si = self.skeleton_info[armature]

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
                self.operator.report(
                    {"WARNING"},
                    "CalcTangets failed for mesh \"{}\", no tangets will be "
                    "exported.".format(mesh.name))
                mesh.calc_normals_split()
                has_tangents = False

        else:
            mesh.calc_normals_split()
            has_tangents = False

        for fi in range(len(mesh.polygons)):
            f = mesh.polygons[fi]

            if f.material_index not in material_to_surface:
                material_to_surface[f.material_index] = len(surfaces)
                surfaces.append(self.Surface())

                try:
                    # TODO: Review, understand why it throws
                    mat = mesh.materials[f.material_index]
                except:
                    mat = None

                if mat is not None:
                    ret_materials.append(self.export_material(
                        mat, mesh.show_double_sided))
                else:
                    ret_materials.append(None)

            surface = surfaces[material_to_surface[f.material_index]]
            vi = []

            for lt in range(f.loop_total):
                loop_index = f.loop_start + lt
                ml = mesh.loops[loop_index]
                mv = mesh.vertices[ml.vertex_index]

                v = self.Vertex()
                v.vertex = fix_vertex(Vector(mv.co))

                for xt in mesh.uv_layers:
                    v.uv.append(Vector(xt.data[loop_index].uv))

                if has_colors:
                    v.color = Vector(
                        mesh.vertex_colors[0].data[loop_index].color)

                v.normal = fix_vertex(Vector(ml.normal))

                if has_tangents:
                    v.tangent = fix_vertex(Vector(ml.tangent))
                    v.bitangent = fix_vertex(Vector(ml.bitangent))

                if armature is not None:
                    wsum = 0.0

                    for vg in mv.groups:
                        if vg.group >= len(node.vertex_groups):
                            continue
                        name = node.vertex_groups[vg.group].name

                        if name in si["bone_index"]:
                            # TODO: Try using 0.0001 since Blender uses
                            #       zero weight
                            if vg.weight > 0.001:
                                v.bones.append(si["bone_index"][name])
                                v.weights.append(vg.weight)
                                wsum += vg.weight
                    if wsum == 0.0:
                        if not self.wrongvtx_report:
                            self.operator.report(
                                {"WARNING"},
                                "Mesh for object \"{}\" has unassigned "
                                "weights. This may look wrong in exported "
                                "model.".format(node.name))
                            self.wrongvtx_report = True

                        # TODO: Explore how to deal with zero-weight bones,
                        #       which remain local
                        v.bones.append(0)
                        v.weights.append(1)

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

        def calc_tangent_dp(vert):
            cr = v.normal.cross(v.tangent)
            dp = cr.dot(v.bitangent)
            return 1.0 if dp > 0.0 else -1.0
        

        for s in surfaces:
            surface_lines = []

            # Vertices
            position_vals = Array("Vector3Array(", ", ", "),")
            [position_vals.extend(list(v.vertex)) for v in s.vertices]
            surface_lines.append(position_vals.to_string())

            # Normals Array
            normal_vals = Array("Vector3Array(", ", ", "),")
            [normal_vals.extend(list(v.normal)) for v in s.vertices]
            surface_lines.append(normal_vals.to_string())

            if has_tangents:
                tangent_vals = Array("FloatArray(", ", ", "),")
                for v in s.vertices:
                    tangent_vals.extend(list(v.tangent) + [calc_tangent_dp(v)])
                surface_lines.append(tangent_vals.to_string())
            else:
                surface_lines.append("null, ; No Tangents")

            # Color Arrays
            if has_colors:
                color_vals = Array("ColorArray(", ", ", "),")
                [color_vals.extend(list(v.color)+[1.0]) for v in s.vertices]
                surface_lines.append(color_vals.to_string())
            else:
                surface_lines.append("null, ; No Colors")

            # UV Arrays
            for i in range(2):  # Godot always expects two arrays for UV's
                if i >= uv_layer_count:
                    # but if there aren't enough in blender, make one of them into null
                    surface_lines.append("null, ; No UV"+str(i+1))
                    continue
                uv_vals = Array("Vector2Array(", ", ", "),")
                for v in s.vertices:
                    uv_vals.extend([v.uv[i].x, -v.uv[i].y])
                surface_lines.append(uv_vals.to_string())

            # Bones and Weights
            # Export armature data (if armature exists)
            if armature is not None:
                # Skin Weights!
                float_values = "FloatArray("
                float_valuesw = "FloatArray("
                first = True
                for v in s.vertices:
                    skin_weights_total += len(v.weights)
                    w = []
                    for i in len(v.bones):
                        w += (v.bones[i], v.weights[i])

                    w = sorted(w, key=lambda x: -x[1])
                    totalw = 0.0
                    for x in w:
                        totalw += x[1]
                    if totalw == 0.0:
                        totalw = 0.000000001

                    for i in range(4):
                        if i > 0:
                            float_values += ","
                            float_valuesw += ","
                        if i < len(w):
                            float_values += " {}".format(w[i][0])
                            float_valuesw += " {}".format(w[i][1]/totalw)
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
            int_values = Array("IntArray(", ", ", "),")
            [int_values.extend([v[0], v[2], v[1]]) for v in s.indices]
            surface_lines.append(int_values.to_string())
            
            mesh_lines.append(surface_lines)

    def export_mesh(self, node, armature=None, skeyindex=-1, skel_source=None,
                    custom_name=None):
        mesh = node.data

        if node.data in self.mesh_cache:
            return self.mesh_cache[mesh]

        morph_target_arrays = []
        morph_target_names = []

        if (mesh.shape_keys is not None and len(
                mesh.shape_keys.key_blocks)):
            values = []
            for k in range(0, len(mesh.shape_keys.key_blocks)):
                shape = node.data.shape_keys.key_blocks[k]
                values += [shape.value]
                shape.value = 0.0

            for k in range(0, len(mesh.shape_keys.key_blocks)):
                shape = node.data.shape_keys.key_blocks[k]
                node.show_only_shape_key = True
                node.active_shape_key_index = k
                shape.value = 1.0
                mesh.update()
                p = node.data
                v = node.to_mesh(bpy.context.scene, True, "RENDER")
                self.temp_meshes.add(v)
                node.data = v
                node.data.update()

                morph_target_lines = []
                md = self.make_arrays(node, None, morph_target_lines, [], k)

                morph_target_names.append(shape.name)
                morph_target_arrays.append(morph_target_lines)

                node.data = p
                node.data.update()
                shape.value = 0.0

            node.show_only_shape_key = False
            node.active_shape_key_index = 0

        mesh_lines = []
        mesh_materials = []
        self.make_arrays(node, armature, mesh_lines, mesh_materials)

        mesh_id = str(self.new_resource_id())
        self.mesh_cache[mesh] = mesh_id

        self.writel(S_INTERNAL_RES, 0, '\n[sub_resource type="ArrayMesh" id='+mesh_id+']\n')

        for i in range(len(mesh_lines)):
            self.writel(S_INTERNAL_RES, 0, "surfaces/" + str(i) + "={")
            if mesh_materials[i] is not None:
                self.writel(S_INTERNAL_RES, 1, "\"material\":SubResource(" + str(mesh_materials[i])+"),")
            self.writel(S_INTERNAL_RES, 1, "\"primitive\":4,")
            self.writel(S_INTERNAL_RES, 1, "\"arrays\":[")
            for sline in mesh_lines[i]:
                self.writel(S_INTERNAL_RES, 2, sline)
            self.writel(S_INTERNAL_RES, 1, "],")
            self.writel(S_INTERNAL_RES, 1, "\"morph_arrays\":[]")
            self.writel(S_INTERNAL_RES, 0, "}")

        return mesh_id

    def export_mesh_node(self, node, parent_path):
        if node.data is None:
            return

        mesh_node = NodeTemplate(node.name, "MeshInstance", parent_path)
        armature = None
        armcount = 0
        for n in node.modifiers:
            if n.type == "ARMATURE":
                armcount += 1

        """ Armature should happen just by direct relationship, since godot supports it the same way as Blender now
        if (node.parent is not None):
            if (node.parent.type == "ARMATURE"):
                armature = node.parent
                if (armcount > 1):
                    self.operator.report(
                        {"WARNING"}, "Object \"{}\" refers "
                        "to more than one armature! "
                        "This is unsupported.".format(node.name))
                if (armcount == 0):
                    self.operator.report(
                        {"WARNING"}, "Object \"{}\" is child "
                        "of an armature, but has no armature modifier.".format(
                            node.name))

        if (armcount > 0 and not armature):
            self.operator.report(
                {"WARNING"},
                "Object \"{}\" has armature modifier, but is not a child of "
                "an armature. This is unsupported.".format(node.name))
        """

        if node.data.shape_keys is not None:
            sk = node.data.shape_keys
            if sk.animation_data:
                for d in sk.animation_data.drivers:
                    if d.driver:
                        for v in d.driver.variables:
                            for t in v.targets:
                                if (t.id is not None and
                                        t.id.name in self.scene.objects):
                                    self.armature_for_morph[
                                        node] = self.scene.objects[t.id.name]

        meshdata = self.export_mesh(node, armature)

        mesh_node.mesh = "SubResource({})".format(meshdata)
        mesh_node.transform = node.matrix_local
        self.writel(S_NODES, 0, mesh_node.to_string())


        """
        Rest of armature/morph stuff
        close_controller = False

        if ("skin_id" in meshdata):
            close_controller = True
            self.writel(
                S_NODES, il, "<instance_controller url=\"#{}\">".format(
                    meshdata["skin_id"]))
            for sn in self.skeleton_info[armature]["skeleton_nodes"]:
                self.writel(
                    S_NODES, il + 1, "<skeleton>#{}</skeleton>".format(sn))
        elif ("morph_id" in meshdata):
            self.writel(
                S_NODES, il, "<instance_controller url=\"#{}\">".format(
                    meshdata["morph_id"]))
            close_controller = True
        elif (armature is None):
            self.writel(S_NODES, il, "<instance_geometry url=\"#{}\">".format(
                meshdata["id"]))

        if (len(meshdata["material_assign"]) > 0):
            self.writel(S_NODES, il + 1, "<bind_material>")
            self.writel(S_NODES, il + 2, "<technique_common>")
            for m in meshdata["material_assign"]:
                self.writel(
                    S_NODES, il + 3,
                    "<instance_material symbol=\"{}\" target=\"#{}\"/>".format(
                        m[1], m[0]))

            self.writel(S_NODES, il + 2, "</technique_common>")
            self.writel(S_NODES, il + 1, "</bind_material>")

        if (close_controller):
            self.writel(S_NODES, il, "</instance_controller>")
        else:
            self.writel(S_NODES, il, "</instance_geometry>")
        """

    """
    def export_armature_bone(self, bone, il, si):
        is_ctrl_bone = (
            bone.name.startswith("ctrl") and
            self.config["use_exclude_ctrl_bones"])
        if (bone.parent is None and is_ctrl_bone is True):
            self.operator.report(
                {"WARNING"}, "Root bone cannot be a control bone.")
            is_ctrl_bone = False

        if (is_ctrl_bone is False):
            boneid = self.new_id("bone")
            boneidx = si["bone_count"]
            si["bone_count"] += 1
            bonesid = "{}-{}".format(si["id"], boneidx)
            if (bone.name in self.used_bones):
                if (self.config["use_anim_action_all"]):
                    self.operator.report(
                        {"WARNING"}, "Bone name \"{}\" used in more than one "
                        "skeleton. Actions might export wrong.".format(
                            bone.name))
            else:
                self.used_bones.append(bone.name)

            si["bone_index"][bone.name] = boneidx
            si["bone_ids"][bone] = boneid
            si["bone_names"].append(bonesid)
            self.writel(
                S_NODES, il, "<node id=\"{}\" sid=\"{}\" name=\"{}\" "
                "type=\"JOINT\">".format(boneid, bonesid, bone.name))

        if (is_ctrl_bone is False):
            il += 1

        xform = bone.matrix_local
        if (is_ctrl_bone is False):
            si["bone_bind_poses"].append(
                    (si["armature_xform"] * xform).inverted_safe())

        if (bone.parent is not None):
            xform = bone.parent.matrix_local.inverted_safe() * xform
        else:
            si["skeleton_nodes"].append(boneid)

        if (is_ctrl_bone is False):
            self.writel(
                S_NODES, il, "<matrix sid=\"transform\">{}</matrix>".format(
                    mat4_to_string(xform)))

        for c in bone.children:
            self.export_armature_bone(c, il, si)

        if (is_ctrl_bone is False):
            il -= 1
            self.writel(S_NODES, il, "</node>")

    def export_armature_node(self, node, il, parent_path):
        if (node.data is None):
            return

        self.skeletons.append(node)

        armature = node.data
        self.skeleton_info[node] = {
            "bone_count": 0,
            "id": self.new_id("skelbones"),
            "name": node.name,
            "bone_index": {},
            "bone_ids": {},
            "bone_names": [],
            "bone_bind_poses": [],
            "skeleton_nodes": [],
            "armature_xform": node.matrix_world
        }

        for b in armature.bones:
            if (b.parent is not None):
                continue
            self.export_armature_bone(b, il, self.skeleton_info[node])

        if (node.pose):
            for b in node.pose.bones:
                for x in b.constraints:
                    if (x.type == "ACTION"):
                        self.action_constraints.append(x.action)
    """
    def export_camera_node(self, node, parent_path):
        if node.data is None:
            return

        cam_node = NodeTemplate(node.name, "Camera", parent_path)
        camera = node.data

        cam_node.far = camera.clip_end
        cam_node.near = camera.clip_start

        if camera.type == "PERSP":
            cam_node.projection = 0
            cam_node.fov = math.degrees(camera.angle)
        else:
            cam_node.projection = 1
            cam_node.size = camera.ortho_scale * 0.5

        cam_node.transform = node.matrix_local * AXIS_CORRECT
        self.writel(S_NODES, 0, cam_node.to_string())

    def export_lamp_node(self, node, parent_path):
        if node.data is None:
            return

        light = node.data

        if light.type == "POINT":
            light_node = NodeTemplate(node.name, "OmniLight", parent_path)
            light_node.omni_range = light.distance
            light_node.shadow_enabled = light.shadow_method != "NOSHADOW"

            if not light.use_sphere:
                print("WARNING: Ranged light without sphere enabled: {}".format(node.name))

        elif light.type == "SPOT":
            light_node = NodeTemplate(node.name, "SpotLight", parent_path)
            light_node.spot_range = light.distance
            light_node.spot_angle = math.degrees(light.spot_size/2)
            light_node.spot_angle_attenuation = 0.2/(light.spot_blend + 0.01)
            light_node.shadow_enabled = light.shadow_method != "NOSHADOW"

            if not light.use_sphere:
                print("WARNING: Ranged light without sphere enabled: {}".format(node.name))

        elif light.type == "SUN":
            light_node = NodeTemplate(node.name, "DirectionalLight", parent_path)
            light_node.shadow_enabled = light.shadow_method != "NOSHADOW"
        else:
            print("WARNING: Unknown light type. Use Point, Spot or Sun: {}".format(node.name))

        # Properties common to all lights
        light_node.light_color = Color(light.color)
        light_node.transform = node.matrix_local * AXIS_CORRECT
        light_node.light_negative = light.use_negative
        light_node.light_specular = 1.0 if light.use_specular else 0.0
        light_node.light_energy = light.energy

        self.writel(S_NODES, 0, light_node.to_string())

    def export_empty_node(self, node, parent_path):
        empty_node = NodeTemplate(node.name, "Spatial", parent_path)
        empty_node.transform = node.matrix_local
        self.writel(S_NODES, 0, empty_node.to_string())

    """
    def export_curve(self, curve):
        splineid = self.new_id("spline")

        self.writel(
            S_GEOM, 1, "<geometry id=\"{}\" name=\"{}\">".format(
                splineid, curve.name))
        self.writel(S_GEOM, 2, "<spline closed=\"0\">")

        points = []
        interps = []
        handles_in = []
        handles_out = []
        tilts = []

        for cs in curve.splines:

            if (cs.type == "BEZIER"):
                for s in cs.bezier_points:
                    points.append(s.co[0])
                    points.append(s.co[1])
                    points.append(s.co[2])

                    handles_in.append(s.handle_left[0])
                    handles_in.append(s.handle_left[1])
                    handles_in.append(s.handle_left[2])

                    handles_out.append(s.handle_right[0])
                    handles_out.append(s.handle_right[1])
                    handles_out.append(s.handle_right[2])

                    tilts.append(s.tilt)
                    interps.append("BEZIER")
            else:

                for s in cs.points:
                    points.append(s.co[0])
                    points.append(s.co[1])
                    points.append(s.co[2])
                    handles_in.append(s.co[0])
                    handles_in.append(s.co[1])
                    handles_in.append(s.co[2])
                    handles_out.append(s.co[0])
                    handles_out.append(s.co[1])
                    handles_out.append(s.co[2])
                    tilts.append(s.tilt)
                    interps.append("LINEAR")

        self.writel(S_GEOM, 3, "<source id=\"{}-positions\">".format(splineid))
        position_values = ""
        for x in points:
            position_values += " {}".format(x)
        self.writel(
            S_GEOM, 4, "<float_array id=\"{}-positions-array\" "
            "count=\"{}\">{}</float_array>".format(
                splineid, len(points), position_values))
        self.writel(S_GEOM, 4, "<technique_common>")
        self.writel(
            S_GEOM, 4, "<accessor source=\"#{}-positions-array\" "
            "count=\"{}\" stride=\"3\">".format(splineid, len(points) / 3))
        self.writel(S_GEOM, 5, "<param name=\"X\" type=\"float\"/>")
        self.writel(S_GEOM, 5, "<param name=\"Y\" type=\"float\"/>")
        self.writel(S_GEOM, 5, "<param name=\"Z\" type=\"float\"/>")
        self.writel(S_GEOM, 4, "</accessor>")
        self.writel(S_GEOM, 3, "</source>")

        self.writel(
            S_GEOM, 3, "<source id=\"{}-intangents\">".format(splineid))
        intangent_values = ""
        for x in handles_in:
            intangent_values += " {}".format(x)
        self.writel(
            S_GEOM, 4, "<float_array id=\"{}-intangents-array\" "
            "count=\"{}\">{}</float_array>".format(
                splineid, len(points), intangent_values))
        self.writel(S_GEOM, 4, "<technique_common>")
        self.writel(
            S_GEOM, 4, "<accessor source=\"#{}-intangents-array\" "
            "count=\"{}\" stride=\"3\">".format(splineid, len(points) / 3))
        self.writel(S_GEOM, 5, "<param name=\"X\" type=\"float\"/>")
        self.writel(S_GEOM, 5, "<param name=\"Y\" type=\"float\"/>")
        self.writel(S_GEOM, 5, "<param name=\"Z\" type=\"float\"/>")
        self.writel(S_GEOM, 4, "</accessor>")
        self.writel(S_GEOM, 3, "</source>")

        self.writel(S_GEOM, 3, "<source id=\"{}-outtangents\">".format(
            splineid))
        outtangent_values = ""
        for x in handles_out:
            outtangent_values += " {}".format(x)
        self.writel(
            S_GEOM, 4, "<float_array id=\"{}-outtangents-array\" "
            "count=\"{}\">{}</float_array>".format(
                splineid, len(points), outtangent_values))
        self.writel(S_GEOM, 4, "<technique_common>")
        self.writel(
            S_GEOM, 4, "<accessor source=\"#{}-outtangents-array\" "
            "count=\"{}\" stride=\"3\">".format(splineid, len(points) / 3))
        self.writel(S_GEOM, 5, "<param name=\"X\" type=\"float\"/>")
        self.writel(S_GEOM, 5, "<param name=\"Y\" type=\"float\"/>")
        self.writel(S_GEOM, 5, "<param name=\"Z\" type=\"float\"/>")
        self.writel(S_GEOM, 4, "</accessor>")
        self.writel(S_GEOM, 3, "</source>")

        self.writel(
            S_GEOM, 3, "<source id=\"{}-interpolations\">".format(splineid))
        interpolation_values = ""
        for x in interps:
            interpolation_values += " {}".format(x)
        self.writel(
            S_GEOM, 4, "<Name_array id=\"{}-interpolations-array\" "
            "count=\"{}\">{}</Name_array>"
            .format(splineid, len(interps), interpolation_values))
        self.writel(S_GEOM, 4, "<technique_common>")
        self.writel(
            S_GEOM, 4, "<accessor source=\"#{}-interpolations-array\" "
            "count=\"{}\" stride=\"1\">".format(splineid, len(interps)))
        self.writel(S_GEOM, 5, "<param name=\"INTERPOLATION\" type=\"name\"/>")
        self.writel(S_GEOM, 4, "</accessor>")
        self.writel(S_GEOM, 3, "</source>")

        self.writel(S_GEOM, 3, "<source id=\"{}-tilts\">".format(splineid))
        tilt_values = ""
        for x in tilts:
            tilt_values += " {}".format(x)
        self.writel(
            S_GEOM, 4,
            "<float_array id=\"{}-tilts-array\" count=\"{}\">{}</float_array>"
            .format(splineid, len(tilts), tilt_values))
        self.writel(S_GEOM, 4, "<technique_common>")
        self.writel(
            S_GEOM, 4, "<accessor source=\"#{}-tilts-array\" "
            "count=\"{}\" stride=\"1\">".format(splineid, len(tilts)))
        self.writel(S_GEOM, 5, "<param name=\"TILT\" type=\"float\"/>")
        self.writel(S_GEOM, 4, "</accessor>")
        self.writel(S_GEOM, 3, "</source>")

        self.writel(S_GEOM, 3, "<control_vertices>")
        self.writel(
            S_GEOM, 4,
            "<input semantic=\"POSITION\" source=\"#{}-positions\"/>"
            .format(splineid))
        self.writel(
            S_GEOM, 4,
            "<input semantic=\"IN_TANGENT\" source=\"#{}-intangents\"/>"
            .format(splineid))
        self.writel(
            S_GEOM, 4, "<input semantic=\"OUT_TANGENT\" "
            "source=\"#{}-outtangents\"/>".format(splineid))
        self.writel(
            S_GEOM, 4, "<input semantic=\"INTERPOLATION\" "
            "source=\"#{}-interpolations\"/>".format(splineid))
        self.writel(
            S_GEOM, 4, "<input semantic=\"TILT\" source=\"#{}-tilts\"/>"
            .format(splineid))
        self.writel(S_GEOM, 3, "</control_vertices>")

        self.writel(S_GEOM, 2, "</spline>")
        self.writel(S_GEOM, 1, "</geometry>")

        return splineid
    def export_curve_node(self, node, il):
        if (node.data is None):
            return

        curveid = self.export_curve(node.data)

        self.writel(S_NODES, il, "<instance_geometry url=\"#{}\">".format(
            curveid))
        self.writel(S_NODES, il, "</instance_geometry>")
    """

    def export_node(self, node, parent_path):
        if node not in self.valid_nodes:
            return

        prev_node = bpy.context.scene.objects.active
        bpy.context.scene.objects.active = node

        node_name = node.name

        if node.type == "MESH":
            self.export_mesh_node(node, parent_path)

        # elif (node.type == "CURVE"):
        #    self.export_curve_node(node, il)
        # elif (node.type == "ARMATURE"):
        #    self.export_armature_node(node, il, node_name, parent_path)
        elif node.type == "CAMERA":
            self.export_camera_node(node, parent_path)
        elif node.type == "LAMP":
            self.export_lamp_node(node, parent_path)
        elif node.type == "EMPTY":
            self.export_empty_node(node, parent_path)
        else:
            print("WARNING: Unknown object type. Treating as empty: {}".format(node.name))
            self.export_empty_node(node, parent_path)

        if parent_path == ".":
            parent_path = node_name
        else:
            parent_path = parent_path+"/"+node_name

        for x in node.children:
            self.export_node(x, parent_path)

        bpy.context.scene.objects.active = prev_node

    def is_node_valid(self, node):
        if node.type not in self.config["object_types"]:
            return False

        if self.config["use_active_layers"]:
            valid = False
            for i in range(20):
                if node.layers[i] and self.scene.layers[i]:
                    valid = True
                    break
            if not valid:
                return False

        if self.config["use_export_selected"] and not node.select:
            return False

        return True

    def export_scene(self):

        print("exporting scene "+str(len(self.scene.objects)))
        for obj in self.scene.objects:
            print("OBJ: "+obj.name)
            if obj in self.valid_nodes:
                continue
            if self.is_node_valid(obj):
                n = obj
                while n is not None:
                    if n not in self.valid_nodes:
                        self.valid_nodes.append(n)
                        print("VALID: "+n.name)
                    n = n.parent

        self.writel(S_NODES, 0, '\n[node name="scene" type="Spatial"]\n')

        for obj in self.scene.objects:
            if obj in self.valid_nodes and obj.parent is None:
                self.export_node(obj, ".")

    """
    def export_animation_transform_channel(self, target, keys, matrices=True):
        frame_total = len(keys)
        anim_id = self.new_id("anim")
        self.writel(S_ANIM, 1, "<animation id=\"{}\">".format(anim_id))
        source_frames = ""
        source_transforms = ""
        source_interps = ""

        for k in keys:
            source_frames += " {}".format(k[0])
            if (matrices):
                source_transforms += " {}".format(mat4_to_string(k[1]))
            else:
                source_transforms += " {}".format(k[1])

            source_interps += " LINEAR"

        # Time Source
        self.writel(S_ANIM, 2, "<source id=\"{}-input\">".format(anim_id))
        self.writel(
            S_ANIM, 3, "<float_array id=\"{}-input-array\" "
            "count=\"{}\">{}</float_array>".format(
                anim_id, frame_total, source_frames))
        self.writel(S_ANIM, 3, "<technique_common>")
        self.writel(
            S_ANIM, 4, "<accessor source=\"#{}-input-array\" "
            "count=\"{}\" stride=\"1\">".format(anim_id, frame_total))
        self.writel(S_ANIM, 5, "<param name=\"TIME\" type=\"float\"/>")
        self.writel(S_ANIM, 4, "</accessor>")
        self.writel(S_ANIM, 3, "</technique_common>")
        self.writel(S_ANIM, 2, "</source>")

        if (matrices):
            # Transform Source
            self.writel(
                S_ANIM, 2, "<source id=\"{}-transform-output\">".format(
                    anim_id))
            self.writel(
                S_ANIM, 3, "<float_array id=\"{}-transform-output-array\" "
                "count=\"{}\">{}</float_array>".format(
                    anim_id, frame_total * 16, source_transforms))
            self.writel(S_ANIM, 3, "<technique_common>")
            self.writel(
                S_ANIM, 4,
                "<accessor source=\"#{}-transform-output-array\" count=\"{}\" "
                "stride=\"16\">".format(anim_id, frame_total))
            self.writel(
                S_ANIM, 5, "<param name=\"TRANSFORM\" type=\"float4x4\"/>")
            self.writel(S_ANIM, 4, "</accessor>")
            self.writel(S_ANIM, 3, "</technique_common>")
            self.writel(S_ANIM, 2, "</source>")
        else:
            # Value Source
            self.writel(
                S_ANIM, 2,
                "<source id=\"{}-transform-output\">".format(anim_id))
            self.writel(
                S_ANIM, 3, "<float_array id=\"{}-transform-output-array\" "
                "count=\"{}\">{}</float_array>".format(
                    anim_id, frame_total, source_transforms))
            self.writel(S_ANIM, 3, "<technique_common>")
            self.writel(
                S_ANIM, 4, "<accessor source=\"#{}-transform-output-array\" "
                "count=\"{}\" stride=\"1\">".format(anim_id, frame_total))
            self.writel(S_ANIM, 5, "<param name=\"X\" type=\"float\"/>")
            self.writel(S_ANIM, 4, "</accessor>")
            self.writel(S_ANIM, 3, "</technique_common>")
            self.writel(S_ANIM, 2, "</source>")

        # Interpolation Source
        self.writel(
            S_ANIM, 2, "<source id=\"{}-interpolation-output\">".format(
                anim_id))
        self.writel(
            S_ANIM, 3, "<Name_array id=\"{}-interpolation-output-array\" "
            "count=\"{}\">{}</Name_array>".format(
                anim_id, frame_total, source_interps))
        self.writel(S_ANIM, 3, "<technique_common>")
        self.writel(
            S_ANIM, 4, "<accessor source=\"#{}-interpolation-output-array\" "
            "count=\"{}\" stride=\"1\">".format(anim_id, frame_total))
        self.writel(S_ANIM, 5, "<param name=\"INTERPOLATION\" type=\"Name\"/>")
        self.writel(S_ANIM, 4, "</accessor>")
        self.writel(S_ANIM, 3, "</technique_common>")
        self.writel(S_ANIM, 2, "</source>")

        self.writel(S_ANIM, 2, "<sampler id=\"{}-sampler\">".format(anim_id))
        self.writel(
            S_ANIM, 3,
            "<input semantic=\"INPUT\" source=\"#{}-input\"/>".format(anim_id))
        self.writel(
            S_ANIM, 3, "<input semantic=\"OUTPUT\" "
            "source=\"#{}-transform-output\"/>".format(anim_id))
        self.writel(
            S_ANIM, 3, "<input semantic=\"INTERPOLATION\" "
            "source=\"#{}-interpolation-output\"/>".format(anim_id))
        self.writel(S_ANIM, 2, "</sampler>")
        if (matrices):
            self.writel(
                S_ANIM, 2, "<channel source=\"#{}-sampler\" "
                "target=\"{}/transform\"/>".format(anim_id, target))
        else:
            self.writel(
                S_ANIM, 2, "<channel source=\"#{}-sampler\" "
                "target=\"{}\"/>".format(anim_id, target))
        self.writel(S_ANIM, 1, "</animation>")

        return [anim_id]

    def export_animation(self, start, end, allowed=None):
        # TODO: Blender -> Collada frames needs a little work
        #       Collada starts from 0, blender usually from 1.
        #       The last frame must be included also

        frame_orig = self.scene.frame_current

        frame_len = 1.0 / self.scene.render.fps
        frame_sub = 0
        if (start > 0):
            frame_sub = start * frame_len

        tcn = []
        xform_cache = {}
        blend_cache = {}

        # Change frames first, export objects last, boosts performance
        for t in range(start, end + 1):
            self.scene.frame_set(t)
            key = t * frame_len - frame_sub

            for node in self.scene.objects:
                if (node not in self.valid_nodes):
                    continue
                if (allowed is not None and not (node in allowed)):
                    if (node.type == "MESH" and node.data is not None and
                        (node in self.armature_for_morph) and (
                            self.armature_for_morph[node] in allowed)):
                        pass
                    else:
                        continue
                if (node.type == "MESH" and node.data is not None and
                    node.data.shape_keys is not None and (
                        node.data in self.mesh_cache) and len(
                            node.data.shape_keys.key_blocks)):
                    target = self.mesh_cache[node.data]["morph_id"]
                    for i in range(len(node.data.shape_keys.key_blocks)):

                        if (i == 0):
                            continue

                        name = "{}-morph-weights({})".format(target, i - 1)
                        if (not (name in blend_cache)):
                            blend_cache[name] = []

                        blend_cache[name].append(
                            (key, node.data.shape_keys.key_blocks[i].value))

                if (node.type == "MESH" and node.parent and
                        node.parent.type == "ARMATURE"):
                    # In Collada, nodes that have skin modifier must not export
                    # animation, animate the skin instead
                    continue

                if (len(node.constraints) > 0 or
                        node.animation_data is not None):
                    # If the node has constraints, or animation data, then
                    # export a sampled animation track
                    name = self.validate_id(node.name)
                    if (not (name in xform_cache)):
                        xform_cache[name] = []

                    mtx = node.matrix_world.copy()
                    if (node.parent):
                        mtx = node.parent.matrix_world.inverted_safe() * mtx

                    xform_cache[name].append((key, mtx))

                if (node.type == "ARMATURE"):
                    # All bones exported for now
                    for bone in node.data.bones:
                        if((bone.name.startswith("ctrl") and
                                self.config["use_exclude_ctrl_bones"])):
                            continue

                        bone_name = self.skeleton_info[node]["bone_ids"][bone]

                        if (not (bone_name in xform_cache)):
                            xform_cache[bone_name] = []

                        posebone = node.pose.bones[bone.name]
                        parent_posebone = None

                        mtx = posebone.matrix.copy()
                        if (bone.parent):
                            if (self.config["use_exclude_ctrl_bones"]):
                                current_parent_posebone = bone.parent
                                while (current_parent_posebone.name
                                        .startswith("ctrl") and
                                        current_parent_posebone.parent):
                                    current_parent_posebone = (
                                        current_parent_posebone.parent)
                                parent_posebone = node.pose.bones[
                                    current_parent_posebone.name]
                            else:
                                parent_posebone = node.pose.bones[
                                    bone.parent.name]
                            parent_invisible = False

                            for i in range(3):
                                if (parent_posebone.scale[i] == 0.0):
                                    parent_invisible = True

                            if (not parent_invisible):
                                mtx = (
                                    parent_posebone.matrix
                                    .inverted_safe() * mtx)

                        xform_cache[bone_name].append((key, mtx))

        self.scene.frame_set(frame_orig)

        # Export animation XML
        for nid in xform_cache:
            tcn += self.export_animation_transform_channel(
                nid, xform_cache[nid], True)
        for nid in blend_cache:
            tcn += self.export_animation_transform_channel(
                nid, blend_cache[nid], False)

        return tcn

    def export_animations(self):
        tmp_mat = []
        for s in self.skeletons:
            tmp_bone_mat = []
            for bone in s.pose.bones:
                tmp_bone_mat.append(Matrix(bone.matrix_basis))
                bone.matrix_basis = Matrix()
            tmp_mat.append([Matrix(s.matrix_local), tmp_bone_mat])

        self.writel(S_ANIM, 0, "<library_animations>")

        if (self.config["use_anim_action_all"] and len(self.skeletons)):

            cached_actions = {}

            for s in self.skeletons:
                if s.animation_data and s.animation_data.action:
                    cached_actions[s] = s.animation_data.action.name

            self.writel(S_ANIM_CLIPS, 0, "<library_animation_clips>")

            for x in bpy.data.actions[:]:
                if x.users == 0 or x in self.action_constraints:
                    continue
                if (self.config["use_anim_skip_noexp"] and
                        x.name.endswith("-noexp")):
                    continue

                bones = []
                # Find bones used
                for p in x.fcurves:
                    dp = p.data_path
                    base = "pose.bones[\""
                    if dp.startswith(base):
                        dp = dp[len(base):]
                        if (dp.find("\"") != -1):
                            dp = dp[:dp.find("\"")]
                            if (dp not in bones):
                                bones.append(dp)

                allowed_skeletons = []
                for i, y in enumerate(self.skeletons):
                    if (y.animation_data):
                        for z in y.pose.bones:
                            if (z.bone.name in bones):
                                if (y not in allowed_skeletons):
                                    allowed_skeletons.append(y)
                        y.animation_data.action = x

                        y.matrix_local = tmp_mat[i][0]
                        for j, bone in enumerate(s.pose.bones):
                            bone.matrix_basis = Matrix()

                tcn = self.export_animation(int(x.frame_range[0]), int(
                    x.frame_range[1] + 0.5), allowed_skeletons)
                framelen = (1.0 / self.scene.render.fps)
                start = x.frame_range[0] * framelen
                end = x.frame_range[1] * framelen
                self.writel(
                    S_ANIM_CLIPS, 1, "<animation_clip name=\"{}\" "
                    "start=\"{}\" end=\"{}\">".format(x.name, start, end))
                for z in tcn:
                    self.writel(S_ANIM_CLIPS, 2,
                                "<instance_animation url=\"#{}\"/>".format(z))
                self.writel(S_ANIM_CLIPS, 1, "</animation_clip>")
                if (len(tcn) == 0):
                    self.operator.report(
                        {"WARNING"}, "Animation clip \"{}\" contains no "
                        "tracks.".format(x.name))

            self.writel(S_ANIM_CLIPS, 0, "</library_animation_clips>")

            for i, s in enumerate(self.skeletons):
                if (s.animation_data is None):
                    continue
                if s in cached_actions:
                    s.animation_data.action = bpy.data.actions[
                        cached_actions[s]]
                else:
                    s.animation_data.action = None
                    for j, bone in enumerate(s.pose.bones):
                        bone.matrix_basis = tmp_mat[i][1][j]

        else:
            self.export_animation(self.scene.frame_start, self.scene.frame_end)

        self.writel(S_ANIM, 0, "</library_animations>")
    """
    def export(self):

        self.export_scene()
        self.purge_empty_nodes()

        # if (self.config["use_anim"]):
        #    self.export_animations()

        try:
            out_file = open(self.path, "wb")
        except:
            return False

        # TODO count nodes and resources written for proper steps, though
        # this is kinda useless on import anyway
        master_heading = SectionHeading("gd_scene", load_steps=1, format=2)
        out_file.write(bytes(master_heading.to_string(), "UTF-8"))

        if S_EXTERNAL_RES in self.sections:
            for external in self.sections[S_EXTERNAL_RES]:
                out_file.write(bytes(external + "\n", "UTF-8"))

        if S_INTERNAL_RES in self.sections:
            for internal in self.sections[S_INTERNAL_RES]:
                out_file.write(bytes(internal + "\n", "UTF-8"))

        for node in self.sections[S_NODES]:
            out_file.write(bytes(node + "\n", "UTF-8"))

        return True

    __slots__ = ("operator", "scene", "last_res_id", "last_ext_res_id",
                 "sections", "path", "mesh_cache", "curve_cache",
                 "material_cache", "image_cache", "skeleton_info", "config",
                 "valid_nodes", "armature_for_morph", "used_bones",
                 "wrongvtx_report", "skeletons", "action_constraints",
                 "temp_meshes")

    def __init__(self, path, kwargs, operator):
        self.operator = operator
        self.scene = bpy.context.scene
        self.last_res_id = 0
        self.last_ext_res_id = 0
        self.sections = {}
        self.path = path
        self.mesh_cache = {}
        self.temp_meshes = set()
        self.curve_cache = {}
        self.material_cache = {}
        self.image_cache = {}
        self.skeleton_info = {}
        self.config = kwargs
        self.valid_nodes = []
        self.armature_for_morph = {}
        self.used_bones = []
        self.wrongvtx_report = False
        self.skeletons = []
        self.action_constraints = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        for mesh in self.temp_meshes:
            bpy.data.meshes.remove(mesh)


def save(operator, context, filepath="", use_selection=False, **kwargs):
    with GodotExporter(filepath, kwargs, operator) as exp:
        exp.export()

    return {"FINISHED"}
