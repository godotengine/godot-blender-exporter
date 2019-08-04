"""Interface for material node tree exporter"""
import os
import logging
import textwrap
from shutil import copyfile
import bpy
import mathutils
from .shader_links import FragmentShaderLink
from .shader_functions import find_function_by_name
from .node_converters import (
    converter_factory, NodeConverterBase, ShadingFlags)
from ....structures import InternalResource, ExternalResource, ValidationError


class ScriptShaderResource(InternalResource):
    """Godot internal resource shader"""

    def __init__(self, name, shader_instance):
        super().__init__("Shader", name)
        self.shader = shader_instance

    def to_string(self):
        """Serialization"""
        self['code'] = '"{}"'.format(self.shader.generate_scripts())
        return InternalResource.to_string(self)


class ScriptShader:
    # pylint: disable-msg=too-many-instance-attributes
    """generator of the shader scripts"""

    SCRIPT_MAX_WIDTH = 80

    UNI_AABB_POS = 'AABB_POS'
    UNI_AABB_SIZE = 'AABB_SIZE'

    def __init__(self):
        self._render_mode = [
            'blend_mix',
            'depth_draw_always',
            'cull_back',
            'diffuse_burley',
            'specular_schlick_ggx',
        ]
        self._functions = set()
        self._global_vars_def_lines = list()
        self._uniform_code_lines = list()
        self._fragment_code_lines = list()
        self._vertex_code_lines = list()

        self._textures = dict()

        self.flags = ShadingFlags()

    def add_functions(self, functions):
        """append local converter functions to shader"""
        self._functions = self._functions.union(functions)

    def add_fragment_code(self, frag_code_list):
        """get local fragment code and append to shader"""
        self._fragment_code_lines.extend(frag_code_list)

    def add_fragment_output(self, output_shader_link):
        """link the node tree output with godot fragment output"""
        # pylint: disable-msg=too-many-branches
        # pylint: disable-msg=too-many-statements

        # hack: define those two variable at the begining
        self._fragment_code_lines.insert(0, "\n")
        if self.flags.inv_view_mat_used:
            self._fragment_code_lines.insert(
                0,
                "mat4 %s = inverse(INV_CAMERA_MATRIX)"
                % NodeConverterBase.INV_VIEW_MAT
            )

        if self.flags.inv_model_mat_used:
            self._fragment_code_lines.insert(
                0,
                "mat4 %s = inverse(WORLD_MATRIX)"
                % NodeConverterBase.INV_MODEL_MAT,
            )

        if self.flags.aabb_tex_coord_used:
            self._uniform_code_lines.append(
                "uniform vec3 %s" % self.UNI_AABB_POS)
            self._uniform_code_lines.append(
                "uniform vec3 %s" % self.UNI_AABB_SIZE)

            self._global_vars_def_lines.append(
                "varying smooth vec3 %s" % NodeConverterBase.AABB_UVW)

            self._vertex_code_lines.insert(
                0,
                "%s = mat3(vec3(1, 0, 0), vec3(0, 0, 1), vec3(0, -1, 0))\
                    * ((VERTEX - %s) * (1.0 / %s))"
                % (NodeConverterBase.AABB_UVW,
                   self.UNI_AABB_POS, self.UNI_AABB_SIZE)
            )

        for name in (
                FragmentShaderLink.ALBEDO, FragmentShaderLink.SSS_STRENGTH,
                FragmentShaderLink.SPECULAR, FragmentShaderLink.METALLIC,
                FragmentShaderLink.ROUGHNESS, FragmentShaderLink.CLEARCOAT,
                FragmentShaderLink.CLEARCOAT_GLOSS,
                FragmentShaderLink.EMISSION, FragmentShaderLink.NORMAL):
            # trival properties
            var = output_shader_link.get_property(name)
            if var is not None:
                self._fragment_code_lines.append(
                    '%s = %s' % (name.upper(), str(var))
                )

        transmission = output_shader_link.get_property(
            FragmentShaderLink.TRANSMISSION)
        transm_output_assign = \
            'TRANSMISSION = vec3(1.0, 1.0, 1.0) * %s;' % transmission
        # blender transmission is a float, however in godot
        # it's a vec3, here the conversion is done
        if self.flags.transmission_used and transmission is not None:
            self._fragment_code_lines.append(transm_output_assign)
        elif transmission is not None:
            self._fragment_code_lines.append(
                "// uncomment it when you need it")
            self._fragment_code_lines.append("// " + transm_output_assign)

        oren_nayar_roughness = output_shader_link.get_property(
            FragmentShaderLink.OREN_NAYAR_ROUGHNESS
        )
        if oren_nayar_roughness is not None:
            # oren nayar roughness is created from BsdfDiffuseNode
            # mostly we don't need it, disney model is better
            self._fragment_code_lines.append(
                "// uncomment it only when you set diffuse mode to oren nayar")
            self._fragment_code_lines.append(
                '// ROUGHNESS = %s;' % oren_nayar_roughness
            )

        tangent = output_shader_link.get_property(FragmentShaderLink.TANGENT)
        tgt_output_assign = \
            "TANGENT = normalize(cross(cross(%s, NORMAL), NORMAL));" % tangent
        binml_output_assign = "BINORMAL = cross(TANGENT, NORMAL);"
        if self.flags.uv_or_tangent_used and tangent is not None:
            self._fragment_code_lines.append(tgt_output_assign)
            self._fragment_code_lines.append(binml_output_assign)
        elif tangent is not None:
            self._fragment_code_lines.append(
                "// uncomment it when you are modifing TANGENT")
            self._fragment_code_lines.append("// " + tgt_output_assign)
            self._fragment_code_lines.append("// " + binml_output_assign)

        anisotropy = \
            output_shader_link.get_property(FragmentShaderLink.ANISOTROPY)
        ans_output_assign = "ANISOTROPY = %s;" % anisotropy
        if self.flags.uv_or_tangent_used and anisotropy is not None:
            self._fragment_code_lines.append(ans_output_assign)
        elif anisotropy is not None:
            self._fragment_code_lines.append(
                "// uncomment it when you have tangent(UV) set")
            self._fragment_code_lines.append("// " + ans_output_assign)

        alpha = output_shader_link.get_property(FragmentShaderLink.ALPHA)
        ior = output_shader_link.get_property(FragmentShaderLink.IOR)
        if self.flags.transparent and alpha is not None:
            if ior is not None and self.flags.glass:
                fresnel_func = find_function_by_name('refraction_fresnel')
                self._functions.add(fresnel_func)
                self._fragment_code_lines.append(
                    "refraction_fresnel(VERTEX, NORMAL, %s, %s)" %
                    (ior, alpha)
                )
                refraction_offset_id = 'refraction_offset'
                # just some magic random value, available for improvements
                self._uniform_code_lines.append(
                    'uniform vec2 %s = vec2(0.2, 0.2)' % refraction_offset_id
                )
                self._fragment_code_lines.append(
                    "EMISSION += textureLod(SCREEN_TEXTURE, SCREEN_UV - "
                    "NORMAL.xy * %s , ROUGHNESS).rgb * (1.0 - %s)" %
                    (refraction_offset_id, alpha)
                )
            else:
                self._fragment_code_lines.append(
                    "EMISSION += textureLod(SCREEN_TEXTURE, SCREEN_UV, "
                    "ROUGHNESS).rgb * (1.0 - %s)" % alpha
                )

            self._fragment_code_lines.append(
                "ALBEDO *= %s" % alpha
            )
            self._fragment_code_lines.append(
                'ALPHA = 1.0;'
            )

    def generate_scripts(self):
        """return the whole script in the format of string"""
        def generate_line_suffix(line):
            if line.startswith("//"):
                _suffix = "\n"
            elif line.endswith("\n"):
                _suffix = ""
            elif line.endswith(";"):
                _suffix = "\n"
            else:
                _suffix = ";\n"
            return _suffix

        def line_wrap(line, suffix):
            wrapped_lines = ""

            prefix = ""
            if line.startswith("\\"):
                prefix = "\\ "

            line_list = textwrap.wrap(line, self.SCRIPT_MAX_WIDTH)
            wrapped_lines += ("\t" + line_list[0] + "\n")
            for lline in line_list[1:-1]:
                wrapped_lines += ("\t\t" + prefix + lline + "\n")
            wrapped_lines += ("\t\t" + prefix + line_list[-1] + suffix)

            return wrapped_lines

        script = "shader_type spatial;\n"
        script += "render_mode " + ", ".join(self._render_mode) + ";\n"
        script += "\n"

        for line in self._uniform_code_lines:
            script += line + ";\n"

        for tex, tex_uniform in self._textures.items():
            script += "uniform sampler2D %s%s;\n" % (
                tex_uniform, tex.hint_str())
        script += "\n"

        for line in self._global_vars_def_lines:
            script += line
            script += ";\n"

        # determine the order, make it easy to work with testcases
        for func in sorted(self._functions, key=lambda x: x.name):
            script += func.code
            script += "\n"

        script += "void vertex () {\n"
        for line in self._vertex_code_lines:
            suffix = generate_line_suffix(line)
            if len(line) > self.SCRIPT_MAX_WIDTH:
                script += line_wrap(line, suffix)
            else:
                script += "\t" + line + suffix
        script += "}\n"
        script += "\n"

        script += "void fragment () {\n"
        for line in self._fragment_code_lines:
            suffix = generate_line_suffix(line)
            if len(line) > self.SCRIPT_MAX_WIDTH:
                script += line_wrap(line, suffix)
            else:
                script += "\t" + line + suffix
        script += "}\n"

        return script

    def update_texture(self, converter):
        """add converter textures into shader and update the texture info
        in converter"""
        for tex in converter.textures:
            if tex in self._textures:
                tex_uniform = self._textures[tex]
            else:
                tex_uniform = "texture_%d" % len(self._textures)
                self._textures[tex] = tex_uniform

            for idx, line in enumerate(converter.local_code):
                # replace tmp texture id with the uniform
                converter.local_code[idx] = \
                    line.replace(tex.tmp_identifier, tex_uniform)

    def get_images(self):
        """return a set of all the images used in shader"""
        image_set = set()
        for tex in self._textures:
            if tex.image is not None:
                image_set.add(tex.image)
        return image_set

    def get_image_texture_info(self):
        """return a list of tuple (image, texture uniform)"""
        image_uniform_tuples = list()
        for tex, uniform in self._textures.items():
            if tex.image is not None:
                image_uniform_tuples.append((tex.image, uniform))
        return image_uniform_tuples


def find_material_output_node(node_tree):
    """Find materia output node in the material node tree, if
    two output nodes found, raise error"""
    output_node = None
    for node in node_tree.nodes:
        if node.bl_idname == 'ShaderNodeOutputMaterial':
            if output_node is None:
                output_node = node
            else:
                logging.warning(
                    "More than one material output node find",
                )
    return output_node


def topology_sort(nodes):
    """topology sort all the nodes"""
    def find_zero_input_node(nodes_input_list):
        for node, inputs in nodes_input_list:
            if inputs == 0:
                return node
        return None

    sorted_node_list = list()

    nodes_input_count = dict()
    for node in nodes:
        cnt = 0
        for sock in node.inputs:
            if sock.is_linked and sock.links[0].is_valid:
                cnt += 1
        nodes_input_count[node] = cnt

    cur_node = find_zero_input_node(nodes_input_count.items())
    while cur_node is not None:
        sorted_node_list.append(cur_node)

        for sock in cur_node.outputs:
            for link in sock.links:
                if link.is_valid:
                    nodes_input_count[link.to_node] -= 1

        # made cur_node -1, so prevent it from being found
        # as zero input
        nodes_input_count[cur_node] = -1

        cur_node = find_zero_input_node(nodes_input_count.items())

    return sorted_node_list


class AxisAlignedBoundBox:
    """Helper class to convert vertex representation of blender
    bounding box to AABB representation"""

    def __init__(self, bl_bound_box):
        #
        #  2 ________ 6
        #   |\       |\
        #   |_\______|_\5
        #  3\ |1    7\ |
        #    \|_______\|
        #     0        4
        #

        # begining cornor
        pos_bl_space = (
            bl_bound_box[0][0],
            bl_bound_box[0][1],
            bl_bound_box[0][2],
        )
        # size from begining cornor to end cornor
        size_bl_space = (
            bl_bound_box[7][0] - bl_bound_box[3][0],
            bl_bound_box[3][1] - bl_bound_box[0][1],
            bl_bound_box[2][2] - bl_bound_box[3][2],
        )

        # convert from yup to zup
        self.position = mathutils.Vector(
            (pos_bl_space[0], pos_bl_space[2], -pos_bl_space[1]))
        # switch y-axis with z-axis
        self.size = mathutils.Vector(
            (size_bl_space[0], size_bl_space[2], size_bl_space[1]))

    @classmethod
    def get_from_object(cls, bl_object):
        """Remove all the deformation from the object and evaluate
        its bounding box"""
        armature = bl_object.find_armature()
        if armature is not None:
            armature_pose_backup = armature.data.pose_position
            armature.data.pose_position = "REST"

        aabb = cls(bl_object.bound_box)

        if armature is not None:
            armature.data.pose_position = armature_pose_backup

        return aabb


def export_image_name(image):
    """Generate name according to Blender image name and format"""
    if image.file_format in ('JPEG', 'JPEG2000'):
        valid_extension_names = ('.jpg', '.jpeg')
    else:
        valid_extension_names = ('.' + image.file_format.lower(), )

    if image.name.lower().endswith(valid_extension_names):
        return image.name

    # add extension information to image name, any one in the extension
    # names list is valid, for simplity just choose the first one
    return image.name + valid_extension_names[0]


def export_texture(escn_file, export_settings, image):
    """Export texture image as an external resource"""
    resource_id = escn_file.get_external_resource(image)
    if resource_id is not None:
        return resource_id

    dst_dir_path = os.path.dirname(export_settings['path'])
    dst_path = os.path.join(dst_dir_path, export_image_name(image))

    if image.packed_file is not None:
        image.filepath_raw = dst_path
        image.save()
    else:
        if image.filepath_raw.startswith("//"):
            src_path = bpy.path.abspath(image.filepath_raw)
        else:
            src_path = image.filepath_raw
        if os.path.normpath(src_path) != os.path.normpath(dst_path):
            copyfile(src_path, dst_path)

    img_resource = ExternalResource(dst_path, "Texture")
    return escn_file.add_external_resource(img_resource, image)


def parse_shader_node_tree(escn_file, export_settings, shader_node_tree):
    """Parse blender shader node tree"""
    shader = ScriptShader()

    exportable = False
    mtl_output_node = find_material_output_node(shader_node_tree)
    if mtl_output_node is not None:
        frag_node_list = topology_sort(shader_node_tree.nodes)

        node_to_converter_map = dict()
        for idx, node in enumerate(frag_node_list):
            if node == mtl_output_node:
                continue

            converter = converter_factory(idx, node)
            node_to_converter_map[node] = converter

            converter.initialize_inputs(node_to_converter_map)
            converter.parse_node_to_fragment()
            converter.initialize_outputs()

            shader.add_functions(converter.functions)
            # update texture before add local code
            shader.update_texture(converter)

            shader.add_fragment_code([
                "// node: '%s'" % node.name,
                "// type: '%s'" % node.bl_idname,
            ])
            # definitions first
            shader.add_fragment_code(converter.input_definitions)
            shader.add_fragment_code(converter.output_definitions)
            shader.add_fragment_code(converter.local_code)
            shader.add_fragment_code(["\n", "\n"])

            # flags are all True/False, here use '|=' instead of
            # 'or' assignment, just for convenience
            shader.flags.glass |= converter.flags.glass
            shader.flags.transparent |= converter.flags.transparent
            shader.flags.inv_model_mat_used \
                |= converter.flags.inv_model_mat_used
            shader.flags.inv_view_mat_used |= converter.flags.inv_view_mat_used
            shader.flags.transmission_used |= converter.flags.transmission_used
            shader.flags.uv_or_tangent_used \
                |= converter.flags.uv_or_tangent_used
            shader.flags.aabb_tex_coord_used \
                |= converter.flags.aabb_tex_coord_used

        surface_output_socket = mtl_output_node.inputs['Surface']
        if surface_output_socket.is_linked:
            surface_in_socket = surface_output_socket.links[0].from_socket
            root_converter = node_to_converter_map[surface_in_socket.node]
            if root_converter.is_valid():
                exportable = True
                shader.add_fragment_output(
                    root_converter.out_sockets_map[surface_in_socket]
                )

    if not exportable:
        return None

    # export used textures
    for image in shader.get_images():
        export_texture(escn_file, export_settings, image)

    return shader


def export_script_shader(escn_file, export_settings, bl_object,
                         bl_node_mtl, gd_shader_mtl):
    """Export cycles material to godot shader script"""
    shader_node_tree = bl_node_mtl.node_tree

    shader_rsc = None
    shader_rsc_id = escn_file.get_internal_resource(shader_node_tree)
    if shader_rsc_id is not None:
        shader_rsc = escn_file.internal_resources[shader_rsc_id - 1]
        assert shader_rsc.heading["id"] == shader_rsc_id
    else:
        shader = parse_shader_node_tree(escn_file, export_settings,
                                        shader_node_tree)
        if shader is None:
            raise ValidationError(
                "Blender material '%s' not able to export as Shader Material"
                % bl_node_mtl.name
            )

        shader_rsc = ScriptShaderResource(shader_node_tree.name, shader)
        shader_rsc_id = escn_file.add_internal_resource(
            shader_rsc, shader_node_tree
        )

    gd_shader_mtl['shader'] = "SubResource(%d)" % shader_rsc_id

    shader = shader_rsc.shader
    # set object related uniforms
    if shader.flags.aabb_tex_coord_used:
        aabb = AxisAlignedBoundBox(bl_object.bound_box)
        gd_shader_mtl['shader_param/%s' % shader.UNI_AABB_POS] = aabb.position
        gd_shader_mtl['shader_param/%s' % shader.UNI_AABB_SIZE] = aabb.size

    # set texture uniforms
    for image, image_unifrom in shader.get_image_texture_info():
        shader_param_key = 'shader_param/%s' % image_unifrom
        img_rsc_id = escn_file.get_external_resource(image)
        gd_shader_mtl[shader_param_key] = "ExtResource(%d)" % img_rsc_id
