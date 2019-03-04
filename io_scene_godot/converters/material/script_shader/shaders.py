"""Class represents fragment shader and vertex shader"""
import re
import collections
import bpy
import mathutils
from .shader_functions import find_function_by_name
from ....structures import Array, ValidationError


def _clear_variable_name(raw_var_name):
    """Remove illegal charactors from given name and
    return the cleared one"""
    return re.sub(r'\W', '', raw_var_name)


class Variable:
    """A variable in material shader scripts"""

    def __init__(self, var_type, var_name):
        self.type = var_type
        self.name = var_name

    def __str__(self):
        """Convert to string"""
        return self.name


class Value:
    """A constant value in material shader scripts"""

    def __init__(self, type_str, data):
        self.type = type_str
        self.data = data

    @classmethod
    def create_from_blender_value(cls, blender_value):
        """Creaate a Value() from a blender object"""
        if isinstance(
                blender_value, (bpy.types.bpy_prop_array, mathutils.Vector)):
            tmp = list()
            for val in blender_value:
                tmp.append(val)

            return Value("vec{}".format(len(tmp)), tuple(tmp))

        if isinstance(blender_value, mathutils.Matrix):
            # godot mat is column major order
            mat = blender_value.transposed()
            column_vec_list = list()
            for vec in mat:
                column_vec_list.append(cls.create_from_blender_value(vec))

            return Value(
                "mat{}".format(len(column_vec_list)),
                tuple(column_vec_list)
            )

        return Value("float", blender_value)

    def __str__(self):
        """Convert to string"""
        if self.type.startswith(('vec', 'mat')):
            return "{}({})".format(
                self.type,
                ', '.join([str(x) for x in self.data])
            )
        return str(self.data)


class FragmentBSDFContainer:
    """Several attributes altogether represents
    blender shader output closure"""
    # 'roughness' mixing of mix_shader and add_shader, there are two
    # different 'roughness' among all the shaders. one is Oren Nayar
    # roughness term used in diffuse shader, the other one is ggx roughness
    # used in glossy, principle, etc.
    _ATTRIBUTES_META = collections.OrderedDict([
        ('albedo', 'vec3'),
        ('alpha', 'float'),
        ('sss_strength', 'float'),
        ('specular', 'float'),
        ('metallic', 'float'),
        ('roughness', 'float'),
        ('oren_nayar_roughness', 'float'),
        ('clearcoat', 'float'),
        ('clearcoat_gloss', 'float'),
        ('anisotropy', 'float'),
        ('transmission', 'float'),
        ('ior', 'float'),
        ('emission', 'vec3'),
        ('normal', 'vec3'),
        ('tangent', 'vec3'),
    ])

    def __init__(self):
        self._data = collections.OrderedDict()

    def get_attribute(self, attr_name):
        """Get a property value, if the property is empty return None"""
        return self._data.get(attr_name, None)

    def set_attribute(self, attr_name, attr_value):
        """Set a property, note that property value can be
        either Value() or Variable()"""
        self._data[attr_name] = attr_value

    @classmethod
    def attribute_names_iterable(cls):
        """Return an iteralble of all attribute names"""
        return cls._ATTRIBUTES_META.keys()

    @classmethod
    def attribute_type(cls, attr_name):
        """Return a type a given attribute"""
        return cls._ATTRIBUTES_META[attr_name]

    @classmethod
    def default(cls):
        """Default closure for unconnected socket"""
        new_closure = cls()
        new_closure.set_attribute('albedo', Value('vec3', (0.0, 0.0, 0.0)))
        return new_closure


class BaseShader:
    """Shared methods in vertex shader and fragment shader"""
    def __init__(self, formated_array, global_ref):
        # array of code
        self.code_array = formated_array

        # reference of global scripts,
        # used to create uniform, add function
        self.global_ref = global_ref

        # maintain a mapping from all output sockets
        # to already calculated var
        self._socket_to_var_map = dict()
        # use to create unique variable name
        self._variable_count = 0

    def append_code_line(self, code_pattern, variables=()):
        """Format a line of code string and append it to codes"""
        assert code_pattern[-1] == ';'
        self.code_array.append(
            code_pattern.format(*tuple([str(x) for x in variables]))
        )

    def append_code_lines_left(self, lines):
        """Format a line of code string and append it to codes"""
        for i, line in enumerate(lines):
            assert line[-1] == ';'
            self.code_array.insert(i, line)

    def append_comment_line(self, comment):
        """Add a line of comment"""
        self.code_array.append(
            '// ' + comment
        )

    def append_empty_line(self):
        """Add an empty linef"""
        self.code_array.append("")

    def _append_defination_code(self, var_to_define):
        definition_str = '{} {};'.format(
            var_to_define.type, str(var_to_define)
        )
        self.code_array.append(definition_str)

    def define_variable(self, var_type, var_base_name):
        """Create a unique variable, and define it in the shader script"""
        self._variable_count += 1
        raw_var_name = 'var{}_{}'.format(
            self._variable_count,
            var_base_name,
        )
        var_name = _clear_variable_name(raw_var_name)
        new_var = Variable(var_type, var_name)
        self._append_defination_code(new_var)
        return new_var

    def define_variable_from_socket(self, node, socket):
        """Create a unique variable, variable name and type generate
        from socket, and also define it in the shader script"""
        if socket.type == 'RGBA':
            var_type = 'vec4'
        elif socket.type == 'VECTOR':
            var_type = 'vec3'
        elif socket.type == 'VALUE':
            var_type = 'float'
        else:
            raise ValidationError(
                "socket '{}' at '{}' is incorrectly connected".format(
                    socket.identifier, node.name
                )
            )

        self._variable_count += 1
        raw_var_name = 'var{}_{}'.format(
            self._variable_count,
            socket.identifier
        )
        var_name = _clear_variable_name(raw_var_name)
        new_var = Variable(var_type, var_name)
        self._append_defination_code(new_var)
        return new_var

    def append_assignment_code(self, var_to_write, var_to_read):
        """Assign a variable or value to another variable"""
        assignment_str = '{} = {};'.format(
            str(var_to_write), str(var_to_read)
        )
        self.code_array.append(assignment_str)

    def is_socket_cached(self, input_socket):
        """Return bool indicating whether an input socket
        has a variable cached"""
        if input_socket.links[0].from_socket in self._socket_to_var_map:
            return True
        return False

    def fetch_variable_from_socket(self, input_socket):
        """Given a input socket, return the variable assigned to that
        socket, note that the variable is actually from the output socket
        at the other side of the link"""
        socket_link = input_socket.links[0]
        var_from_link = self._socket_to_var_map[socket_link.from_socket]

        if socket_link.from_socket.type == socket_link.to_socket.type:
            return var_from_link

        # if the type of two sockets are not matched,
        # insert an implicit conversion
        return self._implicit_socket_convert(
            var_from_link,
            socket_link.from_socket.type,
            socket_link.to_socket.type,
        )

    def assign_variable_to_socket(self, output_socket, variable):
        """Assign an output socket with a variable for later use"""
        self._socket_to_var_map[output_socket] = variable

    def _implicit_socket_convert(self, src_variable,
                                 from_socket_type, to_socket_type):
        """Implicitly convert variable type between a pair of socket with
        different type. It is performed when you link two socket with
        different color in node editor"""
        if (to_socket_type == 'VALUE' and
                from_socket_type in ('VECTOR', 'RGBA')):
            converted_var = self.define_variable(
                'float', 'converted_' + str(src_variable)
            )
            if from_socket_type == 'VECTOR':
                src_variable = Value('vec4', (src_variable, 1.0))

            function = find_function_by_name('node_rgb_to_bw')
            self.add_function_call(function, [src_variable], [converted_var])
            return converted_var

        if to_socket_type == 'VECTOR' and from_socket_type == 'VALUE':
            return Value('vec3', (src_variable,) * 3)

        if to_socket_type == 'RGBA' and from_socket_type == 'VALUE':
            return Value('vec4', (src_variable,) * 4)

        if to_socket_type == 'RGBA' and from_socket_type == 'VECTOR':
            converted_var = self.define_variable(
                'vec4', 'converted_' + str(src_variable)
            )
            self.append_code_line(
                ('{} = vec4(clamp({}, vec3(0.0, 0.0, 0.0),'
                 'vec3(1.0, 1.0, 1.0)).xyz, 1.0);'),
                (converted_var, src_variable)
            )
            return converted_var

        if to_socket_type == 'VECTOR' and from_socket_type == 'RGBA':
            converted_var = self.define_variable(
                'vec3', 'converted_' + str(src_variable)
            )
            self.append_code_line(
                '{} = {}.xyz;', (converted_var, src_variable)
            )
            return converted_var

        raise ValidationError(
            "Cannot link two sockets with type '{}' and '{}'".format(
                from_socket_type, to_socket_type
            )
        )

    @staticmethod
    def _function_call_type_check(argument_var_list, param_type_list):
        assert len(argument_var_list) == len(param_type_list)
        for index, var in enumerate(argument_var_list):
            assert var.type == param_type_list[index]

    def add_function_call(self, function, in_arguments, out_arguments):
        """Call function in shader scripts"""
        self.global_ref.add_function(function)

        # runtime check to make sure generated scripts is valid
        self._function_call_type_check(in_arguments, function.in_param_types)
        self._function_call_type_check(out_arguments, function.out_param_types)

        invoke_str = '{}({}, {});'.format(
            function.name,
            ', '.join([str(x) for x in in_arguments]),
            ', '.join([str(x) for x in out_arguments])
        )
        self.code_array.append(invoke_str)

    def zup_to_yup(self, var_to_convert):
        """Convert a vec3 from z-up space to y-up space"""
        assert var_to_convert.type == 'vec3'
        self.append_comment_line("convert from z-up to y-up")
        self.append_code_line(
            '{} = mat3(vec3(1, 0, 0), vec3(0, 0, -1), vec3(0, 1, 0)) * {};',
            (var_to_convert, var_to_convert)
        )

    def yup_to_zup(self, var_to_convert):
        """Convert a vec3 from y-up space to z-up space"""
        assert var_to_convert.type == 'vec3'
        self.append_comment_line("convert from y-up to z-up")
        self.append_code_line(
            '{} = mat3(vec3(1, 0, 0), vec3(0, 0, 1), vec3(0, -1, 0)) * {};',
            (var_to_convert, var_to_convert)
        )

    def to_string(self):
        """Serialze"""
        return self.code_array.to_string()


class FragmentShader(BaseShader):
    """Fragment shader Script"""
    def __init__(self, global_ref):
        super().__init__(
            Array(
                prefix='\nvoid fragment() {\n\t',
                seperator='\n\t',
                suffix='\n}\n'
            ),
            global_ref
        )

        # flag would be set when glass_bsdf is used
        self.glass_effect = False

        self._invert_view_mat = None
        self._invert_model_mat = None

    @property
    def invert_view_mat(self):
        """Return inverted view matrix"""
        if self._invert_view_mat is None:
            self._invert_view_mat = Variable('mat4', 'inverted_view_matrix')
            self.append_code_lines_left([
                'mat4 {};'.format(str(self._invert_view_mat)),
                '{} = inverse({});'.format(
                    str(self._invert_view_mat),
                    str(Variable('mat4', 'INV_CAMERA_MATRIX'))
                )
            ])
        return self._invert_view_mat

    @property
    def invert_model_mat(self):
        """Return inverted model matrix"""
        if self._invert_model_mat is None:
            self._invert_model_mat = Variable('mat4', 'inverted_model_matrix')
            self.append_code_lines_left([
                'mat4 {};'.format(str(self._invert_model_mat)),
                '{} = inverse({});'.format(
                    str(self._invert_model_mat),
                    str(Variable('mat4', 'WORLD_MATRIX'))
                )
            ])
        return self._invert_model_mat

    def add_bsdf_surface(self, bsdf_output):
        """Link bsdf output to godot fragment builtin out qualifiers"""
        for name in ('albedo', 'sss_strength', 'specular', 'metallic',
                     'roughness', 'clearcoat', 'clearcoat_gloss', 'emission',
                     'normal'):
            var = bsdf_output.get_attribute(name)
            if var is not None:
                self.code_array.append(
                    '{} = {};'.format(name.upper(), str(var))
                )

        transmission_var = bsdf_output.get_attribute('transmission')
        if transmission_var is not None:
            self.append_code_line(
                'TRANSMISSION = vec3(1.0, 1.0, 1.0) * {};',
                (transmission_var,)
            )

        self.append_comment_line("uncomment it only when you set diffuse "
                                 "mode to oren nayar")
        self.append_comment_line(
            'ROUGHNESS = oren_nayar_rougness'
        )

        tangent = bsdf_output.get_attribute('tangent')
        anisotropy = bsdf_output.get_attribute('anisotropy')
        if tangent is not None and anisotropy is not None:
            self.append_code_line('ANISOTROPY = {};', (anisotropy,))
            self.append_code_line(
                'TANGENT = normalize(cross(cross({}, NORMAL), NORMAL));',
                (tangent,),
            )
            self.append_code_line('BINORMAL = cross(TANGENT, NORMAL);')

        alpha = bsdf_output.get_attribute('alpha')
        if alpha is not None:
            refraction_offset = self.global_ref.define_uniform(
                'float', 'refraction_offset'
            )
            if self.glass_effect:
                fresnel_func = find_function_by_name('refraction_fresnel')
                in_arguments = list()
                in_arguments.append(Variable('vec3', 'VERTEX'))
                in_arguments.append(Variable('vec3', 'NORMAL'))
                in_arguments.append(bsdf_output.get_attribute('ior'))
                self.add_function_call(
                    fresnel_func, in_arguments, [alpha]
                )
            self.append_code_line(
                'EMISSION += textureLod(SCREEN_TEXTURE, SCREEN_UV - '
                'NORMAL.xy * {}, ROUGHNESS).rgb * (1.0 - {});',
                (refraction_offset, alpha)
            )
            self.append_code_line(
                'ALBEDO *= {};',
                (alpha,),
            )
            self.append_code_line(
                'ALPHA = 1.0;'
            )

    def add_bump_displacement(self, displacement_output):
        """Add bump displacement to fragment shader"""
        # XXX: use tangent space if uv exists?
        function = find_function_by_name('node_bump')

        in_arguments = list()
        # default bump parameters
        in_arguments.append(Value('float', 1.0))
        in_arguments.append(Value('float', 0.1))
        in_arguments.append(displacement_output)
        in_arguments.append(Variable('vec3', 'NORMAL'))
        in_arguments.append(Variable('vec3', 'VERTEX'))
        in_arguments.append(Value('float', 0.0))

        out = Variable('vec3', 'NORMAL')
        self.add_function_call(function, in_arguments, [out])

    def view_to_model(self, var_to_convert, is_direction=True):
        """Convert a vec3 from view space to model space,
        note that conversion is done in y-up space"""
        assert var_to_convert.type == 'vec3'
        self.append_comment_line("convert from view space to model space")
        if is_direction:
            self.append_code_line(
                '{} = normalize({} * ({} * vec4({}, 0.0))).xyz;',
                (var_to_convert, self.invert_model_mat,
                 self.invert_view_mat, var_to_convert)
            )
        else:
            self.append_code_line(
                '{} = ({} * ({} * vec4({}, 1.0))).xyz;',
                (var_to_convert, self.invert_model_mat,
                 self.invert_view_mat, var_to_convert)
            )

    def model_to_view(self, var_to_convert, is_direction=True):
        """Convert a vec3 from model space to view space,
        note that conversion is done in y-up space"""
        assert var_to_convert.type == 'vec3'
        self.append_comment_line("convert from model space to view space")
        view_mat = Variable('mat4', 'INV_CAMERA_MATRIX')
        model_mat = Variable('mat4', 'WORLD_MATRIX')
        if is_direction:
            self.append_code_line(
                '{} = normalize({} * ({} * vec4({}, 0.0))).xyz;',
                (var_to_convert, view_mat, model_mat, var_to_convert)
            )
        else:
            self.append_code_line(
                '{} = ({} * ({} * vec4({}, 1.0))).xyz;',
                (var_to_convert, view_mat, model_mat, var_to_convert)
            )

    def view_to_world(self, var_to_convert, is_direction=True):
        """Convert a vec3 from view space to world space,
        note that it is done in y-up space"""
        assert var_to_convert.type == 'vec3'
        self.append_comment_line("convert from view space to world space")
        if is_direction:
            self.append_code_line(
                '{} = normalize({} * vec4({}, 0.0)).xyz;',
                (var_to_convert, self.invert_view_mat, var_to_convert)
            )
        else:
            self.append_code_line(
                '{} = ({} * vec4({}, 1.0)).xyz;',
                (var_to_convert, self.invert_view_mat, var_to_convert)
            )

    def world_to_view(self, var_to_convert, is_direction=True):
        """Convert a vec3 from world space to view space,
        note that it is done in y-up space"""
        assert var_to_convert.type == 'vec3'
        self.append_comment_line("convert from world space to view space")
        view_mat = Variable('mat4', 'INV_CAMERA_MATRIX')
        if is_direction:
            self.append_code_line(
                '{} = normalize({} * vec4({}, 0.0)).xyz;',
                (var_to_convert, view_mat, var_to_convert)
            )
        else:
            self.append_code_line(
                '{} = ({} * vec4({}, 1.0)).xyz;',
                (var_to_convert, view_mat, var_to_convert)
            )


class VertexShader(BaseShader):
    """Vertex shader scripts"""
    def __init__(self, global_ref):
        super().__init__(
            Array(
                prefix='\nvoid vertex() {\n\t',
                seperator='\n\t',
                suffix='\n}\n'
            ),
            global_ref
        )


class ShaderGlobals:
    """Global space of shader material, maintains uniforms, functions
    and rendering configures."""
    def __init__(self):
        # render mode and render type is also
        # placed here
        self.uniform_codes = Array(
            prefix='',
            seperator='\n',
            suffix='\n'
        )

        # cache function names to avoid duplicated
        # function code being added
        self.function_name_set = set()
        self.function_codes = Array(
            prefix='',
            seperator='\n',
            suffix='\n'
        )

        self.textures = dict()

        self._render_mode = Array(
            prefix='render_mode ',
            seperator=',',
            suffix=';'
        )

        self._set_render_mode()
        self._uniform_var_count = 0

        self.fragment_shader = FragmentShader(self)
        self.vertex_shader = VertexShader(self)

    def _set_render_mode(self):
        self._render_mode.extend([
            'blend_mix',
            'depth_draw_always',
            'cull_back',
            'diffuse_burley',
            'specular_schlick_ggx',
        ])

    def add_function(self, function):
        """Add function body to global codes"""
        if function.name not in self.function_name_set:
            self.function_name_set.add(function.name)
            self.function_codes.append(function.code)

    def define_uniform(self, uni_type, uni_base_name, hint=None):
        """Define an uniform variable"""
        self._uniform_var_count += 1
        raw_var_name = 'uni{}_{}'.format(
            self._uniform_var_count,
            uni_base_name,
        )
        var_name = _clear_variable_name(raw_var_name)
        new_var = Variable(uni_type, var_name)
        if hint is not None:
            def_str = 'uniform {} {} : {};'.format(uni_type, var_name, hint)
        else:
            def_str = 'uniform {} {};'.format(uni_type, var_name)
        self.uniform_codes.append(def_str)
        return new_var

    def add_image_texture(self, uniform_var, image):
        """Define a uniform referring to the texture sampler
        and store the image object"""
        # store image
        if image is not None:
            self.textures[image] = uniform_var

    def to_string(self):
        """Serialization"""
        return '\n'.join([
            "shader_type spatial;",  # shader type is spatial for 3D scene
            self._render_mode.to_string(),
            self.uniform_codes.to_string(),
            self.function_codes.to_string(),
            self.vertex_shader.to_string(),
            self.fragment_shader.to_string(),
        ])
