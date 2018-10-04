"""A set of node visitor functions to convert material node to shader script"""
import logging
import mathutils
from .shaders import (FragmentShader, VertexShader,
                      Value, Variable, FragmentBSDFContainer)
from .shader_functions import find_node_function
from ...structures import ValidationError


def visit_add_shader_node(shader, node):
    """apply addition to albedo and it may have HDR, alpha is added with
    its complementary, other attributes are averaged"""
    output = FragmentBSDFContainer()

    shader_socket_a = node.inputs[0]
    if shader_socket_a.is_linked:
        in_shader_a = shader.fetch_variable_from_socket(shader_socket_a)
    else:
        in_shader_a = FragmentBSDFContainer.default()

    shader_socket_b = node.inputs[1]
    if shader_socket_b.is_linked:
        in_shader_b = shader.fetch_variable_from_socket(shader_socket_b)
    else:
        in_shader_b = FragmentBSDFContainer.default()

    for attr_name in FragmentBSDFContainer.attribute_names_iterable():
        attr_a = in_shader_a.get_attribute(attr_name)
        attr_b = in_shader_b.get_attribute(attr_name)

        if attr_a and attr_b:
            attr_type = FragmentBSDFContainer.attribute_type(attr_name)
            if attr_name in ("normal", "tangent"):
                # don't mix normal and tangent, use default
                continue
            elif attr_name == "alpha":
                code_pattern = '{} = 1 - clamp(2 - {} - {}, 0.0, 1.0);'
            elif attr_name == "albedo":
                # HDR
                code_pattern = ('{} = {} + {};')
            else:
                code_pattern = '{} = mix({}, {}, 0.5);'
            added_attr = shader.define_variable(
                attr_type, node.name + '_' + attr_name
            )
            shader.append_code_line(
                code_pattern,
                (added_attr, attr_a, attr_b)
            )
            output.set_attribute(attr_name, added_attr)
        elif attr_a:
            output.set_attribute(attr_name, attr_a)
        elif attr_b:
            output.set_attribute(attr_name, attr_b)

    shader.assign_variable_to_socket(node.outputs[0], output)


def visit_mix_shader_node(shader, node):
    """simply a mix of each attribute, note that for unconnect shader input,
    albedo would default to black and alpha would default to 1.0."""
    output = FragmentBSDFContainer()

    in_fac_socket = node.inputs['Fac']
    in_fac = Value('float', in_fac_socket.default_value)
    if in_fac_socket.is_linked:
        in_fac = shader.fetch_variable_from_socket(in_fac_socket)

    in_shader_a = FragmentBSDFContainer.default()
    in_shader_socket_a = node.inputs[1]
    if in_shader_socket_a.is_linked:
        in_shader_a = shader.fetch_variable_from_socket(in_shader_socket_a)

    in_shader_b = FragmentBSDFContainer.default()
    in_shader_socket_b = node.inputs[2]
    if in_shader_socket_b.is_linked:
        in_shader_b = shader.fetch_variable_from_socket(in_shader_socket_b)

    for attribute_name in FragmentBSDFContainer.attribute_names_iterable():
        attr_a = in_shader_a.get_attribute(attribute_name)
        attr_b = in_shader_b.get_attribute(attribute_name)
        # if one shader input has alpha, the other one should default to have
        # alpha = 1.0
        if attribute_name == 'alpha' and attr_a and not attr_b:
            attr_b = Value('float', 1.0)
        if attribute_name == 'alpha' and attr_b and not attr_a:
            attr_a = Value('float', 1.0)

        if attr_a and attr_b:
            attr_type = FragmentBSDFContainer.attribute_type(attribute_name)
            if attribute_name in ("normal", "tangent"):
                # don't mix normal and tangent, use default
                continue
            mix_code_pattern = '{} = mix({}, {}, {});'
            attr_mixed = shader.define_variable(
                attr_type, node.name + '_' + attribute_name
            )
            shader.append_code_line(
                mix_code_pattern,
                (attr_mixed, attr_a, attr_b, in_fac)
            )
            output.set_attribute(attribute_name, attr_mixed)
        elif attr_a:
            output.set_attribute(attribute_name, attr_a)
        elif attr_b:
            output.set_attribute(attribute_name, attr_b)

    shader.assign_variable_to_socket(node.outputs[0], output)


def visit_bsdf_node(shader, node):
    """Visitor for trivial bsdf nodes,
    output in the format of a FragmentBSDFContainer"""
    function = find_node_function(node)

    output = FragmentBSDFContainer()
    in_arguments = list()
    out_arguments = list()

    for socket_name in function.in_sockets:
        socket = node.inputs[socket_name]
        if socket.is_linked:
            var = shader.fetch_variable_from_socket(socket)
            in_arguments.append(var)
        else:
            input_value = Value.create_from_blender_value(
                socket.default_value)
            variable = shader.define_variable_from_socket(
                node, socket
            )
            shader.append_assignment_code(variable, input_value)
            in_arguments.append(variable)

    for attr_name in function.out_sockets:
        var_type = FragmentBSDFContainer.attribute_type(attr_name)
        new_var = shader.define_variable(
            var_type, node.name + '_output_' + attr_name
        )

        output.set_attribute(attr_name, new_var)
        out_arguments.append(new_var)

    shader.add_function_call(function, in_arguments, out_arguments)

    # normal and tangent don't go to bsdf functions
    normal_socket = node.inputs.get('Normal', None)
    tangent_socket = node.inputs.get('Tangent', None)
    # normal and tangent input to shader node is in view space
    for name, socket in (
            ('normal', normal_socket), ('tangent', tangent_socket)):
        if socket is not None and socket.is_linked:
            world_space_dir = shader.fetch_variable_from_socket(socket)
            # convert to y-up axis
            shader.zup_to_yup(world_space_dir)
            # convert direction to view space
            shader.world_to_view(world_space_dir)
            output.set_attribute(name, world_space_dir)

    if node.bl_idname in ('ShaderNodeBsdfGlass', 'ShaderNodeBsdfPrincipled'):
        shader.glass_effect = True

    shader.assign_variable_to_socket(node.outputs[0], output)


def visit_reroute_node(shader, node):
    """For reroute node, traversal it's child and cache the output result"""
    input_socket = node.inputs[0]
    if input_socket.is_linked:
        var = shader.fetch_variable_from_socket(input_socket)
    else:
        logging.warning(
            "'%s' has no input, at '%s'", node.bl_idname, node.name
        )
        var = Value('vec3', (1.0, 1.0, 1.0))

    for output_socket in node.outputs:
        shader.assign_variable_to_socket(output_socket, var)


def visit_bump_node(shader, node):
    """Convert bump node to shader script"""
    function = find_node_function(node)

    in_arguments = list()
    for socket in node.inputs:
        if socket.is_linked:
            var = shader.fetch_variable_from_socket(socket)
            if socket.identifier == 'Normal':
                # convert from model, z-up to view y-up
                # bump function is calculate in view space y-up
                shader.zup_to_yup(var)
                shader.world_to_view(var)
                in_arguments.append(var)
            else:
                in_arguments.append(var)
        else:
            if socket.identifier == 'Normal':
                in_arguments.append(Variable('vec3', 'NORMAL'))
            else:
                in_arguments.append(
                    Value.create_from_blender_value(socket.default_value)
                )

    in_arguments.append(Variable('vec3', 'VERTEX'))
    if node.invert:
        in_arguments.append(Value('float', 1.0))
    else:
        in_arguments.append(Value('float', 0.0))

    out_normal = shader.define_variable(
        'vec3', node.name + '_out_normal'
    )
    shader.add_function_call(function, in_arguments, [out_normal])

    if isinstance(shader, FragmentShader):
        # convert output normal to world_space
        shader.view_to_world(out_normal)
    shader.yup_to_zup(out_normal)

    shader.assign_variable_to_socket(node.outputs[0], out_normal)


def visit_normal_map_node(shader, node):
    """Convert normal map node to shader script, note that it can not
    be used in vertex shader"""
    if isinstance(shader, VertexShader):
        raise ValidationError(
            "'{}' not support in true displacement, at '{}'".format(
                node.bl_idname,
                node.name
            )
        )

    in_arguments = list()
    for socket in node.inputs:
        if socket.is_linked:
            in_arguments.append(
                shader.fetch_variable_from_socket(socket)
            )
        else:
            in_arguments.append(
                Value.create_from_blender_value(socket.default_value)
            )
    function = find_node_function(node)
    output_normal = shader.define_variable('vec3', node.name + '_out_normal')
    if node.space == 'TANGENT':
        in_arguments.append(Variable('vec3', 'NORMAL'))
        in_arguments.append(Variable('vec3', 'TANGENT'))
        in_arguments.append(Variable('vec3', 'BINORMAL'))
        shader.add_function_call(function, in_arguments, [output_normal])
        shader.view_to_world(output_normal)
        shader.yup_to_zup(output_normal)

    elif node.space == 'WORLD':
        in_arguments.append(Variable('vec3', 'NORMAL'))
        in_arguments.append(shader.invert_view_mat)
        shader.add_function_call(function, in_arguments, [output_normal])
        shader.yup_to_zup(output_normal)

    elif node.space == 'OBJECT':
        in_arguments.append(Variable('vec3', 'NORMAL'))
        in_arguments.append(shader.invert_view_mat)
        in_arguments.append(Variable('mat4', 'WORLD_MATRIX'))
        shader.add_function_call(function, in_arguments, [output_normal])
        shader.yup_to_zup(output_normal)

    shader.assign_variable_to_socket(node.outputs[0], output_normal)


def visit_texture_coord_node(shader, node):
    """Convert texture coordinate node to shader script"""
    if node.outputs['UV'].is_linked:
        shader.assign_variable_to_socket(
            node.outputs['UV'],
            Value("vec3", ('UV', 0.0)),
        )

    if isinstance(shader, FragmentShader):
        if node.outputs['Window'].is_linked:
            shader.assign_variable_to_socket(
                node.outputs['Window'],
                Value("vec3", ('SCREEN_UV', 0.0)),
            )
        if node.outputs['Camera'].is_linked:
            shader.assign_variable_to_socket(
                node.outputs['Camera'],
                Value("vec3", ('VERTEX.xy', '-VERTEX.z')),
            )

    view_mat = Variable('mat4', 'INV_CAMERA_MATRIX')
    world_mat = Variable('mat4', 'WORLD_MATRIX')
    normal = Variable('vec3', 'NORMAL')
    position = Variable('vec3', 'VERTEX')

    if node.outputs['Normal'].is_linked:
        normal_socket = node.outputs['Normal']
        output_normal = shader.define_variable_from_socket(
            node, normal_socket
        )
        shader.append_assignment_code(output_normal, normal)
        if isinstance(shader, FragmentShader):
            shader.view_to_model(output_normal)
        shader.yup_to_zup(output_normal)
        shader.assign_variable_to_socket(
            normal_socket, output_normal
        )

    if node.outputs['Object'].is_linked:
        obj_socket = node.outputs['Object']
        output_obj_pos = shader.define_variable_from_socket(
            node, obj_socket
        )
        shader.append_assignment_code(output_obj_pos, position)
        if isinstance(shader, FragmentShader):
            shader.view_to_model(output_obj_pos, False)
        shader.yup_to_zup(output_obj_pos)
        shader.assign_variable_to_socket(obj_socket, output_obj_pos)

    if node.outputs['Reflection'].is_linked:
        ref_socket = node.outputs['Reflection']
        reflect_output = shader.define_variable_from_socket(
            node, ref_socket
        )
        if isinstance(shader, FragmentShader):
            shader.append_code_line(
                ('{} = (inverse({}) * vec4('
                 'reflect(normalize({}), {}), 0.0)).xyz;'),
                (reflect_output, view_mat, position, normal)
            )
        else:
            shader.append_code_line(
                '{} = (reflect(normalize({}, {}), 0.0)).xyz;',
                (reflect_output, position, normal)
            )
        shader.yup_to_zup(reflect_output)
        shader.assign_variable_to_socket(ref_socket, reflect_output)

    if node.outputs['Generated'].is_linked:
        logging.warning(
            'Texture coordinates `Generated` not supported'
        )
        shader.assign_variable_to_socket(
            node.outputs['Generated'],
            Value('vec3', (1.0, 1.0, 1.0))
        )


def visit_rgb_node(shader, node):
    """Convert rgb input node to shader scripts"""
    output = node.outputs[0]
    shader.assign_variable_to_socket(
        output,
        Value.create_from_blender_value(output.default_value)
    )


def visit_image_texture_node(shader, node):
    """Store image texture as a uniform"""
    function = find_node_function(node)

    in_arguments = list()

    tex_coord = Value.create_from_blender_value(
        node.inputs[0].default_value)
    if node.inputs[0].is_linked:
        tex_coord = shader.fetch_variable_from_socket(node.inputs[0])

    if node.image is None:
        logging.warning(
            "Image Texture node '%s' has no image being set",
            node.name
        )

    if node.image is None or node.image not in shader.global_ref.textures:
        tex_image_var = shader.global_ref.define_uniform(
            "sampler2D", node.name + "texture_image"
        )
        shader.global_ref.add_image_texture(
            tex_image_var, node.image
        )
    else:
        tex_image_var = shader.global_ref.textures[node.image]

    in_arguments.append(tex_coord)
    in_arguments.append(tex_image_var)

    out_arguments = list()

    for socket in node.outputs:
        output_var = shader.define_variable_from_socket(
            node, socket
        )
        out_arguments.append(output_var)
        shader.assign_variable_to_socket(socket, output_var)

    shader.add_function_call(function, in_arguments, out_arguments)


def visit_mapping_node(shader, node):
    """Mapping node which apply transform onto point or direction"""
    function = find_node_function(node)

    rot_mat = node.rotation.to_matrix().to_4x4()
    loc_mat = mathutils.Matrix.Translation(node.translation)
    sca_mat = mathutils.Matrix((
        (node.scale[0], 0, 0),
        (0, node.scale[1], 0),
        (0, 0, node.scale[2]),
    )).to_4x4()

    in_vec = Value("vec3", (0.0, 0.0, 0.0))
    if node.inputs[0].is_linked:
        in_vec = shader.fetch_variable_from_socket(node.inputs[0])

    if node.vector_type == "TEXTURE":
        # Texture: Transform a texture by inverse
        # mapping the texture coordinate
        transform_mat = (loc_mat * rot_mat * sca_mat).inverted_safe()
    elif node.vector_type == "POINT":
        transform_mat = loc_mat * rot_mat * sca_mat
    else:  # node.vector_type in ("VECTOR", "NORMAL")
        # no translation for vectors
        transform_mat = rot_mat * sca_mat

    mat = Value.create_from_blender_value(transform_mat)
    clamp_min = Value.create_from_blender_value(node.min)
    clamp_max = Value.create_from_blender_value(node.max)
    use_min = Value("float", 1.0 if node.use_min else 0.0)
    use_max = Value("float", 1.0 if node.use_max else 0.0)

    in_arguments = list()
    in_arguments.append(in_vec)
    in_arguments.append(mat)
    in_arguments.append(clamp_min)
    in_arguments.append(clamp_max)
    in_arguments.append(use_min)
    in_arguments.append(use_max)

    out_vec = shader.define_variable_from_socket(
        node, node.outputs[0]
    )
    shader.add_function_call(function, in_arguments, [out_vec])

    if node.vector_type == "NORMAL":
        # need additonal normalize
        shader.append_code_line(
            '{} = normalize({});',
            (out_vec, out_vec)
        )
    shader.assign_variable_to_socket(node.outputs[0], out_vec)


def visit_converter_node(shader, node):
    """For genearl converter node, which has inputs and outputs and can be
    parsed as a shader function"""
    function = find_node_function(node)
    in_arguments = list()

    for socket in node.inputs:
        if socket.is_linked:
            # iput socket only has one link
            in_arguments.append(
                shader.fetch_variable_from_socket(socket)
            )
        else:
            input_value = Value.create_from_blender_value(
                socket.default_value)
            variable = shader.define_variable_from_socket(
                node, socket
            )
            shader.append_assignment_code(variable, input_value)
            in_arguments.append(variable)

    out_arguments = list()

    for socket in node.outputs:
        new_var = shader.define_variable_from_socket(node, socket)
        shader.assign_variable_to_socket(socket, new_var)
        out_arguments.append(new_var)

    shader.add_function_call(function, in_arguments, out_arguments)


def visit_tangent_node(shader, node):
    """Visit tangent node"""
    if node.direction_type != 'UV_MAP':
        logging.warning(
            'tangent space Radial not supported at %s',
            node.name
        )
    shader.assign_variable_to_socket(
        node.outputs[0], Variable('vec3', 'TANGENT')
    )


NODE_VISITOR_FUNCTIONS = {
    'ShaderNodeMapping': visit_mapping_node,
    'ShaderNodeTexImage': visit_image_texture_node,
    'ShaderNodeTexCoord': visit_texture_coord_node,
    'ShaderNodeRGB': visit_rgb_node,
    'ShaderNodeNormalMap': visit_normal_map_node,
    'ShaderNodeBump': visit_bump_node,
    'NodeReroute': visit_reroute_node,
    'ShaderNodeMixShader': visit_mix_shader_node,
    'ShaderNodeAddShader': visit_add_shader_node,
    'ShaderNodeTangent': visit_tangent_node,
}


def find_node_visitor(shader, node):
    """Return a visitor function for the node"""
    if node.bl_idname in NODE_VISITOR_FUNCTIONS:
        return NODE_VISITOR_FUNCTIONS[node.bl_idname]

    if node.outputs[0].identifier in ('Emission', 'BSDF', 'BSSRDF'):
        # for shader node output bsdf closure
        return visit_bsdf_node

    return visit_converter_node
