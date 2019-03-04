from .visual_nodes import VisualNode, FragmentOutputNode
from .sockets import Socket, AbstractInSocket, AbstractOutSocket


def connects_visual_nodes(conn):
    return (isinstance(conn.from_node, VisualNode) and
            isinstance(conn.to_node, VisualNode))


def connects_fragment_output_node(conn):
    return (isinstance(conn.from_node, VisualNode) and
            isinstance(conn.to_node, FragmentOutputNode))


def connects_abstract_socket(conn):
    return (isinstance(conn.from_socket, AbstractOutSocket) or
            isinstance(conn.to_socket, AbstractOutSocket))


def find_closest_visual_node_in(begin) -> (VisualNode, Socket):
    conn_ref = begin
    while not isinstance(conn_ref.from_node, VisualNode):
        socket = conn_ref.from_socket
        if isinstance(socket, AbstractInSocket):
            conn_ref = socket.input_connection
        else:  # AbstractOutSocket
            conn_ref = socket.hidden_connection

    return conn_ref.from_node, conn_ref.from_socket


def find_all_visual_node_outs(begin) -> [(VisualNode, Socket)]:
    node_info_list = list()

    # bfs
    queue = list()
    queue.append(begin)
    while queue:
        cur_conn = queue.pop(0)

        if isinstance(cur_conn.to_node, VisualNode):
            node_info_list.append(
                cur_conn.to_node, cur_conn.to_socket
            )
        else:
            socket = cur_conn.to_socket
            if isinstance(socket, AbstractInSocket):
                queue.append(socket.hidden_connection)
            else:  # AbstractOutSocket
                for conn in socket.output_connections:
                    queue.append(conn)

    return node_info_list
