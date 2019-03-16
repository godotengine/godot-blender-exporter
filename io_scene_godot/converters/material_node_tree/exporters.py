"""Interface for node tree exporter"""
import os
import logging
from shutil import copyfile
import bpy
from .shaders import ShaderGlobals
from .node_vistors import find_node_visitor
from ...structures import InternalResource, ExternalResource


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


def export_texture(escn_file, export_settings, image):
    """Export texture image as an external resource"""
    resource_id = escn_file.get_external_resource(image)
    if resource_id is not None:
        return resource_id

    dst_dir_path = os.path.dirname(export_settings['path'])
    dst_path = dst_dir_path + os.sep + image.name

    if image.packed_file is not None:
        # image is packed into .blend file
        image_extension = '.' + image.file_format.lower()
        if not image.name.endswith(image_extension):
            dst_path = dst_path + image_extension
        image.filepath_raw = dst_path
        image.save()
    else:
        if image.filepath_raw.startswith("//"):
            src_path = bpy.path.abspath(image.filepath_raw)
        else:
            src_path = image.filepath_raw
        if os.path.abspath(src_path) != os.path.abspath(dst_path):
            copyfile(src_path, dst_path)

    img_resource = ExternalResource(dst_path, "Texture")
    return escn_file.add_external_resource(img_resource, image)


def traversal_tree_from_socket(shader, root_socket):
    """Deep frist traversal the node tree from a root socket"""
    if shader.is_socket_cached(root_socket):
        return shader.fetch_variable_from_socket(root_socket)

    def get_unvisited_depend_node(node):
        """Return an unvisited node linked to the current node"""
        for socket in node.inputs:
            if socket.is_linked and not shader.is_socket_cached(socket):
                return socket.links[0].from_node
        return None

    stack = list()
    cur_node = root_socket.links[0].from_node

    while stack or cur_node is not None:
        while True:
            next_node = get_unvisited_depend_node(cur_node)
            if next_node is None:
                break
            stack.append(cur_node)
            cur_node = next_node

        visitor = find_node_visitor(shader, cur_node)
        shader.append_comment_line("node: {}".format(cur_node.name))
        shader.append_comment_line("type: {}".format(cur_node.bl_idname))
        visitor(shader, cur_node)
        shader.append_empty_line()

        if stack:
            cur_node = stack.pop()
        else:
            cur_node = None

    return shader.fetch_variable_from_socket(root_socket)


def export_node_tree(escn_file, export_settings, cycle_mat, shader_mat):
    """Export cycles material to godot shader script"""
    shader_globals = ShaderGlobals()
    fragment_shader = shader_globals.fragment_shader
    vertex_shader = shader_globals.vertex_shader

    mat_output_node = find_material_output_node(cycle_mat.node_tree)
    if mat_output_node is not None:
        surface_socket = mat_output_node.inputs['Surface']
        displacement_socket = mat_output_node.inputs['Displacement']

        if surface_socket.is_linked:
            fragment_shader.add_bsdf_surface(
                traversal_tree_from_socket(
                    fragment_shader, surface_socket
                )
            )

        if displacement_socket.is_linked:
            fragment_shader.add_bump_displacement(
                traversal_tree_from_socket(
                    fragment_shader, displacement_socket
                )
            )

    shader_resource = InternalResource('Shader', cycle_mat.node_tree.name)
    shader_resource['code'] = '"{}"'.format(shader_globals.to_string())
    resource_id = escn_file.add_internal_resource(
        shader_resource, cycle_mat.node_tree
    )
    shader_mat['shader'] = "SubResource({})".format(resource_id)

    for image, uniform_var in shader_globals.textures.items():
        resource_id = export_texture(escn_file, export_settings, image)
        shader_param_key = 'shader_param/{}'.format(str(uniform_var))
        shader_mat[shader_param_key] = "ExtResource({})".format(resource_id)
