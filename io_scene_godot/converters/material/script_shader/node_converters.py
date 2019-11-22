"""a set of shader node converters responsible for generate"""
import logging
from collections import deque
import re
import bpy
import mathutils
from .shader_links import FragmentShaderLink
from .shader_functions import (
    find_node_function, find_function_by_name, node_has_function)


def blender_value_to_string(blender_value):
    """convert blender socket.default_value to shader script"""
    if isinstance(blender_value,
                  (bpy.types.bpy_prop_array, mathutils.Vector)):
        tmp = list()
        for val in blender_value:
            tmp.append(str(val))

        return "vec%d(%s)" % (len(tmp), ", ".join(tmp))

    if isinstance(blender_value, mathutils.Matrix):
        # godot mat is column major order
        mat = blender_value.transposed()
        column_vec_list = list()
        for vec in mat:
            column_vec_list.append(blender_value_to_string(vec))

        return "mat%d(%s)" % (
            len(column_vec_list),
            ", ".join(column_vec_list)
        )

    return "float(%s)" % blender_value


def socket_to_type_string(socket):
    """return a type string of a blender shader node socket"""
    if socket.type == 'RGBA':
        return 'vec4'

    if socket.type == 'VECTOR':
        return 'vec3'

    if socket.type == 'VALUE':
        return 'float'

    assert False, 'Unknown type %s' % socket.type
    return None


def filter_id_illegal_char(string):
    """filter out non-ascii char in string and convert all char
    to lower case"""
    return re.sub(r'\W', '', string).lower()


def is_normal_texture(image_texture_node):
    """check whether the texture in a TexImage node is normal texture"""
    assert image_texture_node.bl_idname == 'ShaderNodeTexImage'
    node_queue = deque()
    for link in image_texture_node.outputs['Color'].links:
        node_queue.append((link.to_node, link.to_socket))

    while node_queue:
        node, socket = node_queue.popleft()
        if (socket.name == 'Color' and
                node.bl_idname == 'ShaderNodeNormalMap'):
            return True
        for sock in node.outputs:
            for link in sock.links:
                node_queue.append((link.to_node, link.to_socket))

    return False


class Texture:
    """A texture"""

    def __init__(self, bl_image, identifier, hint_normal):
        # note that image could be None, it need to be safely handled
        self.image = bl_image
        self.hint_normal = hint_normal
        # identifier is the variable name in scripts
        self.tmp_identifier = identifier

    def __hash__(self):
        return hash((self.image, self.hint_normal))

    def hint_str(self):
        """form all the hints into a string"""
        if self.hint_normal:
            return ": hint_normal"
        return ""


class ShadingFlags:
    """flags used in compositing shader scripts from node"""

    def __init__(self):
        self.transparent = False
        self.glass = False
        self.inv_view_mat_used = False
        self.inv_model_mat_used = False
        self.uv_or_tangent_used = False
        self.transmission_used = False
        self.aabb_tex_coord_used = False


class NodeConverterBase:
    # pylint: disable-msg=too-many-instance-attributes
    """helper class which wraps a blender shader node and
    able to generate fragment/vertex script from the node"""

    # please set the flag when use them!
    INV_MODEL_MAT = "INV_MODEL_MAT"
    INV_VIEW_MAT = "INV_VIEW_MAT"
    AABB_UVW = "AABB_UVW"

    def __init__(self, index, bl_node):
        self.in_sockets_map = dict()
        self.out_sockets_map = dict()

        self._defined_ids = set()

        self.functions = set()
        self.textures = list()
        self.local_code = list()
        self.input_definitions = list()
        self.output_definitions = list()

        self.input_definitions.append("// input sockets handling")
        self.output_definitions.append("// output sockets definitions")
        self.local_code.append("\n")

        # flags
        self.flags = ShadingFlags()

        self.bl_node = bl_node
        self._id_prefix = "node%s_" % index

        self.variable_count = 0
        self.input_var_count = 0
        self.output_var_count = 0

    def is_valid(self) -> bool:
        """if this segment is valid"""
        return True

    def generate_socket_id_str(self, socket):
        """generate a variable name for given socket"""
        if socket.is_output:
            socket_prefix = 'out%d_' % self.output_var_count
            self.output_var_count += 1
        else:
            socket_prefix = 'in%d_' % self.input_var_count
            self.input_var_count += 1
        return self._id_prefix + socket_prefix + \
            filter_id_illegal_char(socket.name)

    def generate_shader_id_str(self, socket, shader_prop_name):
        """generate a variable name for property of ShaderLink"""
        if socket.is_output:
            socket_prefix = 'out%d_' % self.output_var_count
            self.output_var_count += 1
        else:
            socket_prefix = 'in%d_' % self.input_var_count
            self.input_var_count += 1
        ret_id = self._id_prefix + filter_id_illegal_char(
            socket.name + '_' + socket_prefix + shader_prop_name)
        return ret_id

    def generate_variable_id_str(self, hint):
        """generate variable name for tmp variable"""
        var_prefix = "var%s_" % self.variable_count
        self.variable_count += 1
        return self._id_prefix + var_prefix + filter_id_illegal_char(hint)

    def generate_tmp_texture_id(self, hashable_key):
        """generate a temp variable for texture, later it would be replaced
        by uniform var"""
        var_prefix = "tex%s_" % hash(hashable_key)
        return self._id_prefix + filter_id_illegal_char(var_prefix)

    def generate_socket_assignment(self, to_socket_id, to_socket_type,
                                   from_socket_id, from_socket_type):
        # pylint: disable-msg=too-many-return-statements
        """assign a socket variable to another, it handles type conversion"""
        if to_socket_type == from_socket_type:
            return "%s = %s" % (to_socket_id, from_socket_id)

        if to_socket_type == 'VALUE' and from_socket_type == 'VECTOR':
            return "%s = dot(%s, vec3(0.333333, 0.333333, 0.333333))" \
                % (to_socket_id, from_socket_id)

        if to_socket_type == 'VALUE' and from_socket_type == 'RGBA':
            return "%s = dot(%s.rgb, vec3(0.2126, 0.7152, 0.0722))" \
                % (to_socket_id, from_socket_id)

        if to_socket_type == 'VECTOR' and from_socket_type == 'VALUE':
            return "%s = vec3(%s, %s, %s)" \
                % ((to_socket_id,) + (from_socket_id, ) * 3)

        if to_socket_type == 'RGBA' and from_socket_type == 'VALUE':
            return "%s = vec4(%s, %s, %s, %s)" \
                % ((to_socket_id,) + (from_socket_id, ) * 4)

        if to_socket_type == 'RGBA' and from_socket_type == 'VECTOR':
            return "%s = vec4(%s, 1.0)" % (to_socket_id, from_socket_id)

        if to_socket_type == 'VECTOR' and from_socket_type == 'RGBA':
            return "%s = %s.rgb" % (to_socket_id, from_socket_id)

        assert False, "Cannot link sockets '%s' and '%s'" % (
            to_socket_id, from_socket_id)
        return ""

    def mix_frag_shader_link(self, input_a, input_b, output, fac):
        """mix two ShaderLink with factor 'fac', used only by
        AddShader and MixShader"""
        # simply a mix of each property,
        # except alpha is added with its complementary

        # note that for unconnected shader input,
        # albedo would default to black and alpha would default to 1.0,
        for pname in FragmentShaderLink.ALL_PROPERTIES:
            prop_a = input_a.get_property(pname)
            prop_b = input_b.get_property(pname)

            if pname == FragmentShaderLink.ALPHA:
                # any shader node has no ALPHA property
                # default to have alpha = 1.0
                if prop_a is not None and prop_b is None:
                    prop_b = '1.0'
                elif prop_b is not None and prop_a is None:
                    prop_a = '1.0'

            output_socket = self.bl_node.outputs[0]
            mix_result_id = self.generate_shader_id_str(output_socket, pname)
            if prop_a is not None and prop_b is not None:
                ptype = FragmentShaderLink.get_property_type(pname)
                self.local_code.append(
                    "%s = mix(%s, %s, %s)"
                    % (mix_result_id, prop_a, prop_b, fac)
                )

                output.set_property(pname, mix_result_id)
            elif prop_a is not None:
                output.set_property(pname, prop_a)
            elif prop_b is not None:
                output.set_property(pname, prop_b)

    def add_function_call(self, function, in_args, out_args):
        """add function invoking script"""
        self.functions.add(function)

        self.local_code.append(
            "%s(%s);" % (
                function.name,
                ', '.join([str(x) for x in in_args + out_args]),
            )
        )

    def yup_to_zup(self, var):
        """Convert a vec3 from y-up space to z-up space"""
        function = find_function_by_name("space_convert_yup_to_zup")
        self.add_function_call(function, [var], [])

    def zup_to_yup(self, var):
        """Convert a vec3 from z-up space to y-up space"""
        function = find_function_by_name("space_convert_zup_to_yup")
        self.add_function_call(function, [var], [])

    def view_to_model(self, var, is_direction=True):
        """Convert a vec3 from view space to model space,
        note that conversion is done in y-up space"""
        self.flags.inv_view_mat_used = True
        self.flags.inv_model_mat_used = True
        if is_direction:
            function = find_function_by_name(
                "dir_space_convert_view_to_model")
        else:
            function = find_function_by_name(
                "point_space_convert_view_to_model")
        self.add_function_call(
            function,
            [var, self.INV_MODEL_MAT, self.INV_VIEW_MAT],
            [])

    def model_to_view(self, var, is_direction=True):
        """Convert a vec3 from model space to view space,
        note that conversion is done in y-up space"""
        if is_direction:
            function = find_function_by_name(
                "dir_space_convert_model_to_view")
        else:
            function = find_function_by_name(
                "point_space_convert_model_to_view")
        self.add_function_call(
            function, [var, 'INV_CAMERA_MATRIX', 'WORLD_MATRIX'], []
        )

    def view_to_world(self, var, is_direction=True):
        """Convert a vec3 from view space to world space,
        note that it is done in y-up space"""
        self.flags.inv_view_mat_used = True
        if is_direction:
            function = find_function_by_name(
                "dir_space_convert_view_to_world")
        else:
            function = find_function_by_name(
                "point_space_convert_view_to_world")
        self.add_function_call(function, [var, self.INV_VIEW_MAT], [])

    def world_to_view(self, var, is_direction=True):
        """Convert a vec3 from world space to view space,
        note that it is done in y-up space"""
        if is_direction:
            function = find_function_by_name(
                "dir_space_convert_world_to_view")
        else:
            function = find_function_by_name(
                "point_space_convert_world_to_view")
        self.add_function_call(function, [var, 'INV_CAMERA_MATRIX'], [])

    def _initialize_value_in_socket(self, socket, blnode_to_converter_map):
        type_str = socket_to_type_string(socket)
        id_str = self.generate_socket_id_str(socket)
        self.in_sockets_map[socket] = id_str
        self._defined_ids.add(id_str)

        use_default_value = True
        if socket.is_linked:
            link = socket.links[0]
            from_node = link.from_node
            from_socket = link.from_socket
            from_converter = blnode_to_converter_map[from_node]
            if not from_converter.is_valid():
                logging.warning("input node '%s' not supported,"
                                "use default value for socket '%s'",
                                from_node.name, socket.name)
            else:
                use_default_value = False
                from_socket_id = from_converter.out_sockets_map[from_socket]
                inter_socket_assign_str = self.generate_socket_assignment(
                    id_str, socket.type, from_socket_id, from_socket.type)
                self.input_definitions.append(
                    "%s %s" % (type_str, inter_socket_assign_str)
                )

        if use_default_value:
            if socket.name == 'Normal':
                value_str = 'NORMAL'
            elif socket.name == 'Tangent':
                value_str = 'TANGENT'
            else:
                value_str = blender_value_to_string(socket.default_value)
            self.input_definitions.append(
                "%s %s = %s" % (type_str, id_str, value_str)
            )

    def _initialize_shader_in_socket(self, socket, blnode_to_converter_map):
        in_shader_link = None
        if socket.is_linked:
            link = socket.links[0]
            from_node = link.from_node
            from_socket = link.from_socket
            from_converter = blnode_to_converter_map[from_node]

            if from_socket.type == 'SHADER' and from_converter.is_valid():
                in_shader_link = from_converter.out_sockets_map[from_socket]
                self.in_sockets_map[socket] = in_shader_link

        if in_shader_link is None:
            # default only set albedo
            in_shader_link = FragmentShaderLink()
            in_shader_link.albedo = self.generate_shader_id_str(
                socket, FragmentShaderLink.ALBEDO)
            self.in_sockets_map[socket] = in_shader_link
            self.input_definitions.append(
                "vec3 %s = vec3(0.0, 0.0, 0.0)" % in_shader_link.albedo
            )

        for pname in FragmentShaderLink.ALL_PROPERTIES:
            from_prop_id = in_shader_link.get_property(pname)
            if from_prop_id is not None:
                cur_prop_id = self.generate_shader_id_str(socket, pname)
                self._defined_ids.add(cur_prop_id)
                cur_prop_type = FragmentShaderLink.get_property_type(pname)
                in_shader_link.set_property(pname, cur_prop_id)
                self.input_definitions.append(
                    "%s %s = %s" % (cur_prop_type, cur_prop_id, from_prop_id)
                )

    def initialize_inputs(self, blnode_to_converter_map):
        """initialize the input sockets variable through links
        or default_value"""
        for in_socket in self.bl_node.inputs:
            if in_socket.type != 'SHADER':
                self._initialize_value_in_socket(
                    in_socket, blnode_to_converter_map)
            else:
                self._initialize_shader_in_socket(
                    in_socket, blnode_to_converter_map)

    def initialize_outputs(self):
        """initialize definition of the output sockets"""
        # here not all the sockets are exported, because some of them
        # may not feasible to supported in godot. Here only export
        # those registed in `out_sockets_map`. Registering is done in
        # `parse_node_to_fragment` or `parse_node_to_vertex`
        id_to_define = list()
        for out_socket in self.bl_node.outputs:
            var = self.out_sockets_map.get(out_socket, None)
            if var is not None:
                if out_socket.type != 'SHADER':
                    id_str = var
                    type_str = socket_to_type_string(out_socket)
                    id_to_define.append((type_str, id_str))
                else:
                    for pname in FragmentShaderLink.ALL_PROPERTIES:
                        id_str = var.get_property(pname)
                        type_str = var.get_property_type(pname)
                        if id_str is not None:
                            id_to_define.append((type_str, id_str))

        for type_str, id_str in id_to_define:
            # don't define if they already in input sockets
            assert isinstance(id_str, str) and id_str.isidentifier()
            if id_str not in self._defined_ids:
                self._defined_ids.add(id_str)
                self.output_definitions.append(
                    "%s %s" % (type_str, id_str)
                )

    def parse_node_to_fragment(self):
        """Parse the node to generate fragment shader script"""
        assert False, 'Not implemented'

    def parse_node_to_vertex(self):
        """Parse the node to generate vertex shader script"""
        assert False, 'Not implemented'


class InvalidNodeConverter(NodeConverterBase):
    """converter for not supported shader nodes"""

    def is_valid(self):
        return False

    def parse_node_to_fragment(self):
        self.local_code.append("// Warn: node not supported")

    def parse_node_to_vertex(self):
        self.local_code.append("// Warn: node not supported")


class AddShaderConverter(NodeConverterBase):
    """Converter for ShaderNodeAddShader"""

    def parse_node_to_fragment(self):
        shader_socket_a = self.bl_node.inputs[0]
        in_shader_a = self.in_sockets_map[shader_socket_a]

        shader_socket_b = self.bl_node.inputs[1]
        in_shader_b = self.in_sockets_map[shader_socket_b]

        output_shader_link = FragmentShaderLink()
        self.mix_frag_shader_link(
            in_shader_a, in_shader_b, output_shader_link, 0.5)

        out_socket = self.bl_node.outputs[0]
        self.out_sockets_map[out_socket] = output_shader_link


class MixShaderConverter(NodeConverterBase):
    """Converter for ShaderNodeMixShader"""

    def parse_node_to_fragment(self):
        output = FragmentShaderLink()

        in_fac_socket = self.bl_node.inputs['Fac']
        in_fac = self.in_sockets_map[in_fac_socket]

        in_shader_socket_a = self.bl_node.inputs[1]
        in_shader_a = self.in_sockets_map[in_shader_socket_a]

        in_shader_socket_b = self.bl_node.inputs[2]
        in_shader_b = self.in_sockets_map[in_shader_socket_b]

        output_shader_link = FragmentShaderLink()
        self.mix_frag_shader_link(
            in_shader_a, in_shader_b, output_shader_link, in_fac)

        out_socket = self.bl_node.outputs[0]
        self.out_sockets_map[out_socket] = output_shader_link


class BsdfNodeConverter(NodeConverterBase):
    """Converter for all the BSDF nodes"""

    def parse_node_to_fragment(self):
        output_socket = self.bl_node.outputs[0]
        output_shader_link = FragmentShaderLink()
        self.out_sockets_map[output_socket] = output_shader_link

        if self.bl_node.bl_idname in ('ShaderNodeBsdfGlass',):
            self.flags.glass = True

        if self.bl_node.bl_idname in \
                ('ShaderNodeBsdfTransparent', 'ShaderNodeBsdfGlass'):
            self.flags.transparent = True

        tangent_socket = self.bl_node.inputs.get('Tangent', None)
        if tangent_socket is not None and tangent_socket.is_linked:
            self.flags.uv_or_tangent_used = True

        transmission_socket = self.bl_node.inputs.get('Transmission', None)
        if (transmission_socket is not None and
                transmission_socket.is_linked and
                transmission_socket.default_value == 0.0):
            self.flags.transmission_used = True

        function = find_node_function(self.bl_node)
        func_in_args = list()
        func_out_args = list()

        for socket_name in function.in_sockets:
            socket = self.bl_node.inputs[socket_name]
            func_in_args.append(self.in_sockets_map[socket])

        for prop_name in function.output_properties:
            var_id = self.generate_shader_id_str(output_socket, prop_name)
            output_shader_link.set_property(prop_name, var_id)
            func_out_args.append(var_id)

        self.add_function_call(function, func_in_args, func_out_args)

        # normal and tangent don't go to function
        normal_socket = self.bl_node.inputs.get('Normal', None)
        # normal and tangent input to shader node is in view space
        for pname, socket in (
                (FragmentShaderLink.NORMAL, normal_socket),
                (FragmentShaderLink.TANGENT, tangent_socket)):
            if socket is not None:
                socket_var = self.in_sockets_map[socket]
                if socket.is_linked:
                    # default value is in y-up, view space
                    # while value come from socket is z-up, model space
                    self.zup_to_yup(socket_var)
                    self.world_to_view(socket_var)
                output_shader_link.set_property(pname, socket_var)


class RerouteNodeConverter(NodeConverterBase):
    """Converter for NodeReroute"""

    def parse_node_to_fragment(self):
        """do nothing but assign output = input"""
        in_socket = self.bl_node.inputs[0]
        out_socket = self.bl_node.outputs[0]
        self.out_sockets_map[out_socket] = self.in_sockets_map[in_socket]


class BumpNodeConverter(NodeConverterBase):
    """Converter for ShaderNodeBump"""

    def parse_node_to_fragment(self):
        function = find_node_function(self.bl_node)

        in_arguments = list()
        for socket in self.bl_node.inputs:
            socket_var = self.in_sockets_map[socket]
            if socket.name == 'Normal' and socket.is_linked:
                self.zup_to_yup(socket_var)
                self.world_to_view(socket_var)
            in_arguments.append(socket_var)

        in_arguments.append('VERTEX')
        if self.bl_node.invert:
            in_arguments.append(1.0)
        else:
            in_arguments.append(0.0)

        out_socket = self.bl_node.outputs[0]
        out_normal = self.generate_socket_id_str(out_socket)
        self.out_sockets_map[out_socket] = out_normal

        self.add_function_call(function, in_arguments, [out_normal])
        self.view_to_world(out_normal)
        self.yup_to_zup(out_normal)


class NormalMapNodeConverter(NodeConverterBase):
    """Converter for ShaderNodeNormalMap"""

    def parse_node_to_fragment(self):
        function = find_node_function(self.bl_node)

        in_arguments = list()
        for socket in self.bl_node.inputs:
            in_arguments.append(self.in_sockets_map[socket])

        output_socket = self.bl_node.outputs[0]
        output_normal = self.generate_socket_id_str(output_socket)
        self.out_sockets_map[output_socket] = output_normal
        if self.bl_node.space == 'TANGENT':
            in_arguments.append('NORMAL')
            in_arguments.append('TANGENT')
            in_arguments.append('BINORMAL')
            self.add_function_call(function, in_arguments, [output_normal])
            self.view_to_world(output_normal)
            self.yup_to_zup(output_normal)

        elif self.bl_node.space == 'WORLD':
            self.flags.inv_view_mat_used = True
            in_arguments.append('NORMAL')
            in_arguments.append(self.INV_VIEW_MAT)
            self.add_function_call(function, in_arguments, [output_normal])
            self.yup_to_zup(output_normal)

        elif self.bl_node.space == 'OBJECT':
            self.flags.inv_view_mat_used = True
            in_arguments.append('NORMAL')
            in_arguments.append(self.INV_VIEW_MAT)
            in_arguments.append('WORLD_MATRIX')
            self.add_function_call(function, in_arguments, [output_normal])
            self.yup_to_zup(output_normal)


class TexCoordNodeConverter(NodeConverterBase):
    """Converter for ShaderNodeTexCoord"""

    def parse_node_to_fragment(self):
        for socket in self.bl_node.outputs:
            if socket.is_linked:
                socket_id = self.generate_socket_id_str(socket)
                self.out_sockets_map[socket] = socket_id

        uv_socket = self.bl_node.outputs['UV']
        if uv_socket.is_linked:
            uv_id = self.out_sockets_map[uv_socket]
            self.local_code.append("%s = vec3(UV, 0.0)" % uv_id)

        window_socket = self.bl_node.outputs['Window']
        if window_socket.is_linked:
            window_id = self.out_sockets_map[window_socket]
            self.local_code.append("%s = vec3(SCREEN_UV, 0.0)" % window_id)

        camera_socket = self.bl_node.outputs['Camera']
        if camera_socket.is_linked:
            camera_id = self.out_sockets_map[camera_socket]
            self.local_code.append(
                "%s = vec3(VERTEX.xy, -VERTEX.z)" % camera_id)

        normal_socket = self.bl_node.outputs['Normal']
        if normal_socket.is_linked:
            normal_id = self.out_sockets_map[normal_socket]
            self.local_code.append('%s = NORMAL' % normal_id)
            self.view_to_model(normal_id)
            self.yup_to_zup(normal_id)

        obj_socket = self.bl_node.outputs['Object']
        if obj_socket.is_linked:
            object_id = self.out_sockets_map[obj_socket]
            self.local_code.append('%s = VERTEX' % object_id)
            self.view_to_model(object_id, False)
            self.yup_to_zup(object_id)
            self.out_sockets_map[obj_socket] = object_id

        ref_socket = self.bl_node.outputs['Reflection']
        if ref_socket.is_linked:
            reflect_id = self.out_sockets_map[ref_socket]
            self.local_code.append(
                '%s = reflect(normalize(VERTEX), NORMAL)'
                % reflect_id
            )
            self.view_to_model(reflect_id)
            self.yup_to_zup(reflect_id)
            self.out_sockets_map[ref_socket] = reflect_id

        generated_socket = self.bl_node.outputs['Generated']
        if generated_socket.is_linked:
            generated_id = self.out_sockets_map[generated_socket]
            self.flags.aabb_tex_coord_used = True
            self.local_code.append('%s = %s' % (generated_id, self.AABB_UVW))
            self.out_sockets_map[ref_socket] = generated_id


class RgbNodeConverter(NodeConverterBase):
    """Converter for ShaderNodeRGB"""

    def parse_node_to_fragment(self):
        rgb_socket = self.bl_node.outputs[0]
        rgb_id = self.generate_socket_id_str(rgb_socket)
        rgb_value_str = blender_value_to_string(rgb_socket.default_value)
        self.local_code.append("%s = %s" % (rgb_id, rgb_value_str))
        self.out_sockets_map[rgb_socket] = rgb_id


class MixRgbNodeConverter(NodeConverterBase):
    """Converter for ShaderNodeMixRGB"""

    def parse_node_to_fragment(self):
        fac_socket = self.bl_node.inputs['Fac']
        color1_socket = self.bl_node.inputs['Color1']
        color2_socket = self.bl_node.inputs['Color2']

        fac_id = self.in_sockets_map[fac_socket]
        color1_id = self.in_sockets_map[color1_socket]
        color2_id = self.in_sockets_map[color2_socket]

        blend_type = self.bl_node.blend_type.lower()
        rgb_mix_func_name = 'node_mix_rgb_' + blend_type

        # clamp fac to (0, 1)
        self.local_code.append("%s = clamp(%s, 0.0, 1.0)" % (fac_id, fac_id))

        mix_func = find_function_by_name(rgb_mix_func_name)
        if mix_func is None:
            # TODO: support all the blend types
            warning_str = 'blend type %s not supported at %s, fall back to ' \
                'blend type MIX' % (self.bl_node.blend_type, self.bl_node.name)
            logging.warning(warning_str)
            # default blender type MIX
            mix_func = find_function_by_name('node_mix_rgb_mix')
            self.local_code.append("// " + warning_str)
        assert mix_func is not None

        out_color_socket = self.bl_node.outputs['Color']
        out_color_id = self.generate_socket_id_str(out_color_socket)

        in_args = (fac_id, color1_id, color2_id)
        out_args = (out_color_id,)
        self.add_function_call(mix_func, in_args, out_args)

        if self.bl_node.use_clamp:
            self.local_code.append("%s = clamp(%s, vec4(0.0), vec4(1.0))" % (out_color_id, out_color_id))

        self.out_sockets_map[out_color_socket] = out_color_id


class ValueNodeConverter(NodeConverterBase):
    """Converter for ShaderNodeValue"""

    def parse_node_to_fragment(self):
        value_socket = self.bl_node.outputs['Value']
        value_id = self.generate_socket_id_str(value_socket)
        value_str = blender_value_to_string(value_socket.default_value)
        self.out_sockets_map[value_socket] = "%s = %s" % (value_id, value_str)


class ImageTextureNodeConverter(NodeConverterBase):
    """Converter for ShaderNodeTexImage"""

    def parse_node_to_fragment(self):
        function = find_node_function(self.bl_node)

        in_arguments = list()
        tex_coord_socket = self.bl_node.inputs[0]
        tex_coord = self.in_sockets_map[tex_coord_socket]
        if not tex_coord_socket.is_linked:
            self.local_code.append("%s = vec3(UV, 0.0)" % tex_coord)

        tex_var = self.generate_tmp_texture_id(self.bl_node.name)
        if self.bl_node.image is not None:
            is_normal = is_normal_texture(self.bl_node)
        else:
            is_normal = False
        self.textures.append(
            Texture(self.bl_node.image, tex_var, is_normal)
        )

        in_arguments.append(tex_coord)
        in_arguments.append(tex_var)

        out_arguments = list()

        for socket in self.bl_node.outputs:
            output_var = self.generate_socket_id_str(socket)
            self.out_sockets_map[socket] = output_var
            out_arguments.append(output_var)

        self.add_function_call(function, in_arguments, out_arguments)


class MappingNodeConverter(NodeConverterBase):
    """Converter for ShaderNodeMapping"""

    def parse_node_to_fragment(self):
        function = find_node_function(self.bl_node)

        rot_mat = self.bl_node.rotation.to_matrix().to_4x4()
        loc_mat = mathutils.Matrix.Translation(self.bl_node.translation)
        sca_mat = mathutils.Matrix((
            (self.bl_node.scale[0], 0, 0),
            (0, self.bl_node.scale[1], 0),
            (0, 0, self.bl_node.scale[2]),
        )).to_4x4()

        in_vec = self.in_sockets_map[self.bl_node.inputs[0]]

        if self.bl_node.vector_type == "TEXTURE":
            # Texture: Transform a texture by inverse
            # mapping the texture coordinate
            transform_mat = (loc_mat @ rot_mat @ sca_mat).inverted_safe()
        elif self.bl_node.vector_type == "POINT":
            transform_mat = loc_mat @ rot_mat @ sca_mat
        else:  # node.vector_type in ("VECTOR", "NORMAL")
            # no translation for vectors
            transform_mat = rot_mat @ sca_mat

        mat = blender_value_to_string(transform_mat)
        clamp_min = blender_value_to_string(self.bl_node.min)
        clamp_max = blender_value_to_string(self.bl_node.max)
        use_min = 1.0 if self.bl_node.use_min else 0.0
        use_max = 1.0 if self.bl_node.use_max else 0.0

        in_arguments = list()
        in_arguments.append(in_vec)
        in_arguments.append(mat)
        in_arguments.append(clamp_min)
        in_arguments.append(clamp_max)
        in_arguments.append(use_min)
        in_arguments.append(use_max)

        output_socket = self.bl_node.outputs[0]
        out_vec = self.generate_socket_id_str(output_socket)
        self.out_sockets_map[output_socket] = out_vec

        self.add_function_call(function, in_arguments, [out_vec])
        if self.bl_node.vector_type == "NORMAL":
            # need additonal normalize
            self.local_code.append(
                '%s = normalize(%s)' % (out_vec, out_vec)
            )


class TangentNodeConverter(NodeConverterBase):
    """Converter for ShaderNodeTangent"""

    def parse_node_to_fragment(self):
        if self.bl_node.direction_type != 'UV_MAP':
            logging.warning(
                'tangent space Radial not supported at %s',
                self.bl_node.name
            )

        self.flags.uv_or_tangent_used = True

        tangent_socket = self.bl_node.outputs[0]
        tangent_id = self.generate_socket_id_str(tangent_socket)
        self.out_sockets_map[tangent_socket] = tangent_id

        self.local_code.append(
            '%s = TANGENT' % tangent_id
        )


class UvmapNodeConverter(NodeConverterBase):
    """Converter for ShaderNodeUVMap"""

    def parse_node_to_fragment(self):
        self.flags.uv_or_tangent_used = True

        uv_socket = self.bl_node.outputs['UV']
        uv_id = self.generate_socket_id_str(uv_socket)
        self.out_sockets_map[uv_socket] = uv_id

        self.local_code.append(
            '%s = vec3(UV, 0.0)' % uv_id
        )

        logging.warning(
            "'%s' use the active UV map, make sure the correct "
            "one is selected, at '%s",
            self.bl_node.bl_idname, self.bl_node.name
        )


class GeneralNodeConverter(NodeConverterBase):
    """Converter for general converter node, they all use functions"""

    def parse_node_to_fragment(self):
        function = find_node_function(self.bl_node)
        in_arguments = list()

        for socket in self.bl_node.inputs:
            in_arguments.append(
                self.in_sockets_map[socket]
            )

        out_arguments = list()
        for socket in self.bl_node.outputs:
            socket_id = self.generate_socket_id_str(socket)
            self.out_sockets_map[socket] = socket_id
            out_arguments.append(socket_id)

        self.add_function_call(function, in_arguments, out_arguments)


NODE_CONVERTERS = {
    'ShaderNodeMapping': MappingNodeConverter,
    'ShaderNodeTexImage': ImageTextureNodeConverter,
    'ShaderNodeTexCoord': TexCoordNodeConverter,
    'ShaderNodeRGB': RgbNodeConverter,
    'ShaderNodeMixRGB': MixRgbNodeConverter,
    'ShaderNodeNormalMap': NormalMapNodeConverter,
    'ShaderNodeBump': BumpNodeConverter,
    'NodeReroute': RerouteNodeConverter,
    'ShaderNodeMixShader': MixShaderConverter,
    'ShaderNodeAddShader': AddShaderConverter,
    'ShaderNodeTangent': TangentNodeConverter,
    'ShaderNodeUVMap': UvmapNodeConverter,
    'ShaderNodeValue': ValueNodeConverter,
}


def converter_factory(idx, node):
    """Return a visitor function for the node"""
    if node.bl_idname in NODE_CONVERTERS:
        return NODE_CONVERTERS[node.bl_idname](idx, node)

    if (node.outputs and
            node.outputs[0].identifier in ('Emission', 'BSDF', 'BSSRDF')):
        # for shader node output bsdf closure
        return BsdfNodeConverter(idx, node)

    if node_has_function(node):
        return GeneralNodeConverter(idx, node)

    return InvalidNodeConverter(idx, node)
