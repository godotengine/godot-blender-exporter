from .derived_nodes import *
from .sockets import (
    Connection,
    AbstractColorInSocket, AbstractColorOutSocket,
    AbstractShaderInSocket, AbstractShaderOutSocket)


def convert_link(link, node_map):
    connections = list()

    gd_from_node = node_map[link.from_node]
    gd_to_node = node_map[link.to_node]

    from_socket_type = link.from_socket.type
    to_socket_type = link.to_socket.type
    # skip invalid link
    if (from_socket_type == 'SHADER' and to_socket_type != 'SHADER' or
            from_socket_type != 'SHADER' and to_socket_type == 'SHADER'):
        return connections

    from_sock = gd_from_node.get_output_socket(link.from_socket.name)
    to_sock = gd_to_node.get_input_socket(link.to_socket.name)

    if from_sock is None or to_sock is None:
        return connections

    if isinstance(to_sock, AbstractShaderInSocket):
        assert isinstance(from_sock, AbstractShaderOutSocket)
        for socket_name in AbstractShaderOutSocket.INNER_SOCKET_LIST:
            inner_from_socket = from_sock.get_inner_socket(socket_name)
            inner_to_socket = to_sock.get_inner_socket(socket_name)
            if inner_from_socket.is_valid():
                conn = Connection()
                inner_from_socket.append_output(conn)
                inner_to_socket.set_input(conn)
                connections.append(conn)

    elif isinstance(to_sock, AbstractColorInSocket):
        if isinstance(from_sock, AbstractColorOutSocket):
            rgb_conn = Connection()
            from_sock.rgb.append_output(rgb_conn)
            to_sock.rgb.set_input(rgb_conn)
            connections.append(rgb_conn)

            alpha_conn = Connection()
            from_sock.alpha.append_output(alpha_conn)
            to_sock.alpha.set_input(alpha_conn)
            connections.append(alpha_conn)
        else:
            conn = Connection()
            from_sock.append_output(conn)
            to_sock.rgb.set_input(conn)
            connections.append(conn)
    else:
        conn = Connection()
        from_sock.append_output(conn)
        to_sock.set_input(conn)
        connections.append(conn)

    return connections


def convert_node(shader_node):
    node_position_x = shader_node.location.x
    node_position_y = -shader_node.location.y

    converted_node = None

    if shader_node.bl_idname == 'ShaderNodeBsdfPrincipled':
        converted_node = PrincipledBsdfNode(node_position_x, node_position_y)
    elif shader_node.bl_idname == 'MaterialOutput':
        converted_node = FragmentOutputNode(node_position_x, node_position_y)

    if isinstance(converted_node, AbstractGroupNode):
        for socket in shader_node.inputs:
            if socket.type != 'SHADER' and not socket.is_linked:
                converted_node_socket = converted_node.get_input_socket(
                    socket.name)
                converted_node.set_default_value(
                    converted_node_socket, socket.default_value)

    return converted_node
