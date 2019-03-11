"""Interface for material node tree exporter"""
import os
import logging
import textwrap
from shutil import copyfile
import bpy
from .shader_links import FragmentShaderLink
from .shader_functions import find_function_by_name
from .node_converters import (
    converter_factory, NodeConverterBase, ShadingFlags)
from ....structures import InternalResource, ExternalResource, ValidationError


class ScriptShader:
    # pylint: disable-msg=too-many-instance-attributes
    """generator of the shader scripts"""

    SCRIPT_MAX_WIDTH = 80

    def __init__(self):
        self._render_mode = [
            'blend_mix',
            'depth_draw_always',
            'cull_back',
            'diffuse_burley',
            'specular_schlick_ggx',
        ]
        self._functions = set()
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

        # hack define those two variable at the begining
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
            # define an unifrom var
            refraction_offset = 'refraction_offset'
            self._uniform_code_lines.append(
                'uniform vec2 %s = vec2(0.2, 0.2)' % refraction_offset
            )
            if ior is not None and self.flags.glass:
                fresnel_func = find_function_by_name('refraction_fresnel')
                self._functions.add(fresnel_func)
                self._fragment_code_lines.append(
                    "refraction_fresnel(VERTEX, NORMAL, %s, %s)" %
                    (ior, alpha)
                )
            self._fragment_code_lines.append(
                "EMISSION += textureLod(SCREEN_TEXTURE, SCREEN_UV - "
                "NORMAL.xy * %s , ROUGHNESS).rgb * (1.0 - %s)" %
                (refraction_offset, alpha)
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
        return {tex.image for tex in self._textures}

    def get_image_texture_info(self):
        """return a list of tuple (image, texture uniform)"""
        return [(tex.image, uniform)
                for tex, uniform in self._textures.items()]


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


def breadth_first_search(begin_socket):
    """bfs the node tree from the given socket"""
    sorted_node_list = list()

    link_queue = list()
    if begin_socket.is_linked:
        link_queue.append(begin_socket.links[0])
    while link_queue:
        cur_link = link_queue.pop(0)
        if not cur_link.is_valid:
            continue

        cur_node = cur_link.from_node
        sorted_node_list.append(cur_node)

        for in_sock in cur_node.inputs:
            if in_sock.is_linked:
                for link in in_sock.links:
                    link_queue.append(link)

    return sorted_node_list


def export_texture(escn_file, export_settings, image):
    """Export texture image as an external resource"""
    resource_id = escn_file.get_external_resource(image)
    if resource_id is not None:
        return resource_id

    dst_dir_path = os.path.dirname(export_settings['path'])
    dst_path = dst_dir_path + os.sep + image.name

    if image.packed_file is not None:
        image_format = image.file_format
        image_name_lower = image.name.lower()

        if image_format in ('JPEG', 'JPEG2000'):
            # jpg and jpeg are same thing
            if not image_name_lower.endswith('.jpg') and \
                    not image_name_lower.endswith('.jpeg'):
                dst_path = dst_path + '.jpg'
        elif not image_name_lower.endswith('.' + image_format.lower()):
            dst_path = dst_path + '.' + image_format.lower()
        image.filepath_raw = dst_path
        image.save()
    else:
        if image.filepath_raw.startswith("//"):
            src_path = bpy.path.abspath(image.filepath_raw)
        else:
            src_path = image.filepath_raw
        copyfile(src_path, dst_path)

    img_resource = ExternalResource(dst_path, "Texture")
    return escn_file.add_external_resource(img_resource, image)


def export_script_shader(escn_file, export_settings,
                         bl_node_mtl, gd_shader_mtl):
    """Export cycles material to godot shader script"""
    shader = ScriptShader()

    exportable = False
    mtl_output_node = find_material_output_node(bl_node_mtl.node_tree)
    surface_output_socket = mtl_output_node.inputs['Surface']
    if surface_output_socket.is_linked:
        frag_node_list = breadth_first_search(surface_output_socket)

        node_to_converter_map = dict()
        for idx, node in enumerate(reversed(frag_node_list)):
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

        surface_in_socket = surface_output_socket.links[0].from_socket
        root_converter = node_to_converter_map[frag_node_list[0]]
        if root_converter.is_valid():
            exportable = True
            shader.add_fragment_output(
                root_converter.out_sockets_map[surface_in_socket]
            )

    if not exportable:
        raise ValidationError(
            "Blender material '%s' not able to export as Shader Material"
            % bl_node_mtl.name
        )

    shader_resource = InternalResource('Shader', bl_node_mtl.node_tree.name)
    shader_resource['code'] = '"{}"'.format(shader.generate_scripts())
    resource_id = escn_file.add_internal_resource(
        shader_resource, bl_node_mtl.node_tree
    )
    gd_shader_mtl['shader'] = "SubResource(%d)" % resource_id

    for image in shader.get_images():
        export_texture(escn_file, export_settings, image)

    for image, image_unifrom in shader.get_image_texture_info():
        shader_param_key = 'shader_param/%s' % image_unifrom
        resource_id = escn_file.get_external_resource(image)
        gd_shader_mtl[shader_param_key] = "ExtResource(%d)" % resource_id
