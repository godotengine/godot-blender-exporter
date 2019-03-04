from ....structures import InternalResource, Array
from .converters import convert_node, convert_link
from .visual_nodes import VisualNode
from .derived_nodes import AbstractGroupNode, FragmentOutputNode
from .connection_utils import (connects_abstract_socket,
                               connects_fragment_output_node,
                               connects_visual_nodes,
                               find_closest_visual_node_in,
                               find_all_visual_node_outs)


class VisualShader(InternalResource):
    def __init__(self, name):
        super().__init__('VisualShader', name)
        # no idea why start from 2..
        self.next_node_id = 2
        self.node_id_map = dict()
        self.connection_quad_set = set()

        self['node/fragment/connections'] = Array('PoolIntArray')

    def set_frag_node_resource(self, escn_file, visual_node):
        assert id(visual_node) not in self.node_id_map
        node_id = self.next_node_id
        self.next_node_id += 1

        self.node_id_map[id(visual_node)] = node_id
        node_prefix = 'node/fragment/%d' % node_id
        rsc_id = escn_file.add_internal_resource(visual_node, id(visual_node))
        self[node_prefix + '/node'] = 'SubResource( %d )' % rsc_id
        self[node_prefix + '/position'] = visual_node.get_position()

    def set_frag_output_node(self, node):
        self['node/fragment/0/position'] = node.get_position()

    def add_fragment_node(self, escn_file, node):
        if isinstance(node, VisualNode):
            self.set_frag_node_resource(escn_file, node)
        elif isinstance(node, FragmentOutputNode):
            self.set_frag_output_node(node)
        elif isinstance(node, AbstractGroupNode):
            for vs_node in node.visual_nodes:
                self.set_frag_node_resource(escn_file, vs_node)

            for conn in node.inner_connections:
                if connects_visual_nodes(conn):
                    self.add_fragment_connection(node)

    def add_fragment_connection(self, conn):
        if connects_abstract_socket(conn):
            from_node, from_socket = find_closest_visual_node_in(conn)
            to_info_list = find_all_visual_node_outs(conn)
            for to_node, to_socket in to_info_list:
                if isinstance(to_node, FragmentOutputNode):
                    conn_quad = tuple(
                        self.node_id_map[id(from_node)],
                        from_socket.get_index(),
                        0,
                        to_socket.get_index()
                    )
                else:
                    conn_quad = tuple(
                        self.node_id_map[id(from_node)],
                        from_socket.get_index(),
                        self.node_id_map[id(to_node)],
                        to_socket.get_index()
                    )

                if conn_quad not in self.connection_quad_set:
                    self.connection_quad_set.add(conn_quad)
                    self['node/fragment/connections'].extends(conn_quad)

        else:
            if connects_visual_nodes(conn):
                conn_quad = tuple(
                    self.node_id_map[id(conn.from_node)],
                    conn.from_socket.get_index(),
                    self.node_id_map[id(conn.to_node)],
                    conn.to_socket.get_index()
                )
            elif connects_fragment_output_node(conn):
                conn_quad = tuple(
                    self.node_id_map[id(conn.from_node)],
                    conn.from_socket.get_index(),
                    0,
                    conn.to_socket.get_index()
                )
            else:
                assert False

            if conn_quad not in self.connection_quad_set:
                self.connection_quad_set.add(conn_quad)
                self['node/fragment/connections'].extends(conn_quad)


def export_visual_shader(escn_file, export_settings, bl_node_mtl, gd_mtl):
    visual_shader_rsc = VisualShader(bl_node_mtl.node_tree.name)

    # mapping from blender shader node to godot visual node
    vert_node_map = dict()

    frag_node_map = dict()
    for shader_node in bl_node_mtl.node_tree.nodes:
        gd_node = convert_node(shader_node)
        frag_node_map[shader_node] = gd_node
        visual_shader_rsc.add_fragment_node(escn_file, gd_node)

    frag_connections = list()
    for link in bl_node_mtl.node_tree.links:
        # multiple connections may created from single link
        frag_connections.extend(convert_link(link, frag_node_map))

    for conn in frag_connections:
        visual_shader_rsc.add_fragment_connection(conn)

    resource_id = escn_file.add_internal_resource(
        visual_shader_rsc, bl_node_mtl.node_tree
    )

    gd_mtl['shader'] = "SubResource({})".format(resource_id)
