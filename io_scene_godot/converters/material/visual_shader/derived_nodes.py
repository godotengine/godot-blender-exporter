# TODO import weakref, use weakref to help gc
from mathutils import Vector
from .sockets import (
    VisualNodeVec3Socket, VisualNodeScalarSocket,
    AbstractColorInSocket, AbstractColorOutSocket,
    AbstractShaderInSocket, AbstractShaderOutSocket,
    AbstractScalarInSocket, AbstractScalarOutSocket,
    AbstractVec3InSocket, AbstractVec3OutSocket,
    Connection)
from .visual_nodes import *


class TranslatedBlenderNode:
    def __init__(self):
        self.input_conns = list()
        self.output_conns = list()

    def get_input_socket(self, socket_name):
        assert False, "not implemented"

    def get_output_socket(self, socket_name):
        assert False, "not implemented"


class AbstractGroupNode(TranslatedBlenderNode):
    INNER_NODE_DISTANCE = (0, 200)
    INPUT_NODE_OFFSET = (-200, 0)

    def __init__(self, pos_x, pos_y):
        self.visual_nodes = list()
        self.inner_connections = set()

        self._position = (pos_x, pos_y)

        self._next_inner_node_pos = self._position
        self._next_input_node_pos = self._position + self.INPUT_NODE_OFFSET

    def set_default_value(self, node_socket, default_value):
        const_node = None
        if isinstance(node_socket, AbstractScalarInSocket):
            const_node = ScalarConstant(default_value)
            conn = Connection()
            conn.set_from_info(const_node, ScalarConstant.SOCK_OUT_VALUE)
            conn.set_to_info(self, node_socket)
            self.add_inner_connection(conn)
            self.add_default_input_node(const_node)
        elif isinstance(node_socket, AbstractVec3InSocket):
            const_node = Vec3Constant(
                tuple(default_value[0], default_value[1], default_value[2]))
            conn = Connection()
            conn.set_from_info(const_node, Vec3Constant.SOCK_OUT_VALUE)
            conn.set_to_info(self, node_socket)
            self.add_inner_connection(conn)
            self.add_default_input_node(const_node)
        else:  # color input
            rgb_value = \
                tuple(default_value[0], default_value[1], default_value[2])
            rgb_const_node = Vec3Constant(rgb_value)
            rgb_conn = Connection()
            rgb_conn.set_from_info(rgb_const_node, Vec3Constant.SOCK_OUT_VALUE)
            rgb_conn.set_to_info(self, node_socket)
            self.add_inner_connection(rgb_conn)
            self.add_default_input_node(rgb_const_node)

            alpha_value = default_value[3]
            alpha_const_node = ScalarConstant(alpha_value)
            alpha_conn = Connection()
            alpha_conn.set_from_info(
                alpha_const_node, Vec3Constant.SOCK_OUT_VALUE)
            alpha_conn.set_to_info(self, node_socket)
            self.add_inner_connection(alpha_conn)
            self.add_default_input_node(alpha_const_node)

    def add_default_input_node(self, const_node):
        const_node.set_position(self._next_input_node_pos)
        self._next_input_node_pos += self.INNER_NODE_DISTANCE \
            + self.INPUT_NODE_OFFSET
        self.visual_nodes.append(const_node)

    def add_inner_node(self, visual_node):
        visual_node.set_position(self._next_inner_node_pos)
        self._next_inner_node_pos += self.INNER_NODE_DISTANCE
        self.visual_nodes.append(visual_node)

    def add_inner_connection(self, connection):
        self.inner_connections.add(connection)

    def scalar_const_op_sock(self, op, const_val, socket_conn):
        scalar_node = ScalarConstant(const_val)
        op_node = ScalarOp(op)
        self.add_inner_node(scalar_node)
        self.add_inner_node(op_node)

        scalar_conn = Connection()
        scalar_conn.set_from_info(scalar_node, ScalarConstant.SOCK_OUT_VALUE)
        scalar_conn.set_to_info(op_node, ScalarOp.SOCK_IN_A)
        self.add_inner_connection(scalar_conn)

        socket_conn.set_to_info(op_node, ScalarOp.SOCK_IN_B)

        result_conn = Connection()
        result_conn.set_from_info(op_node, ScalarOp.SOCK_OUT_RESULT)
        self.add_inner_connection(result_conn)

        return result_conn

    def scalar_sock_op_const(self, op, socket_conn, const_val):
        scalar_node = ScalarConstant(const_val)
        op_node = ScalarOp(op)
        self.add_inner_node(scalar_node)
        self.add_inner_node(op_node)

        socket_conn.set_to_info(op_node, ScalarOp.SOCK_IN_A)

        scalar_conn = Connection()
        scalar_conn.set_from_info(scalar_node, ScalarConstant.SOCK_OUT_VALUE)
        scalar_conn.set_to_info(op_node, ScalarOp.SOCK_IN_B)
        self.add_inner_connection(scalar_conn)

        result_conn = Connection()
        result_conn.set_from_info(op_node, ScalarOp.SOCK_OUT_RESULT)
        self.add_inner_connection(result_conn)

        return result_conn

    def scalar_sock_op_sock(self, op, sock_conn_a, sock_conn_b):
        op_node = ScalarOp(op)
        self.add_inner_node(op_node)

        sock_conn_a.set_to_info(op_node, ScalarOp.SOCK_IN_A)

        sock_conn_b.set_to_info(op_node, ScalarOp.SOCK_IN_B)

        result_conn = Connection()
        result_conn.set_from_info(op_node, ScalarOp.SOCK_OUT_RESULT)
        self.add_inner_connection(result_conn)

        return result_conn

    def scalar_func(self, func, sock_conn):
        func_node = ScalarFunc(func)
        self.add_inner_node(func_node)

        sock_conn.set_to_info(func_node, ScalarFunc.SOCK_IN_ARG)

        result_conn = Connection()
        result_conn.set_from_info(func_node, ScalarFunc.SOCK_OUT_RESULT)
        self.add_inner_connection(result_conn)

        return result_conn

    def scalar_mix(self, arg_a, arg_b, arg_c):
        pass

    def vec3_sock_op_sock(self, op, sock_conn_a, sock_conn_b):
        op_node = Vec3Op(op)
        self.add_inner_node(op_node)

        sock_conn_a.set_to_node(op_node)
        sock_conn_a.set_to_socket(Vec3Op.SOCK_IN_A)

        sock_conn_b.set_to_node(op_node)
        sock_conn_b.set_to_socket(Vec3Op.SOCK_IN_B)

        result_conn = Connection()
        result_conn.set_from_info(op_node, Vec3Op.SOCK_OUT_RESULT)
        self.add_inner_connection(result_conn)

        return result_conn

    def vec3_mix(self, arg_a, arg_b, arg_c):
        def argument_parse(arg):
            if isinstance(arg, Connection):
                sock_conn = arg
            elif isinstance(arg, tuple):
                const_node = Vec3Constant(arg)
                self.add_inner_node(const_node)

                sock_conn = Connection()
                self.add_inner_connection(sock_conn)
                sock_conn.set_from_info(
                    const_node, Vec3Constant.SOCK_OUT_VALUE)
            return sock_conn

        mix_node = Vec3Interp()
        self.add_inner_node(mix_node)

        sock_conn_a = argument_parse(arg_a)
        sock_conn_b = argument_parse(arg_b)
        sock_conn_c = argument_parse(arg_c)
        sock_conn_a.set_to_node(mix_node)
        sock_conn_a.set_from_socket(Vec3Interp.SOCK_IN_A)
        sock_conn_b.set_to_node(mix_node)
        sock_conn_b.set_from_socket(Vec3Interp.SOCK_IN_B)
        sock_conn_c.set_to_node(mix_node)
        sock_conn_c.set_from_socket(Vec3Interp.SOCK_IN_C)
        self.add_inner_connection(sock_conn_a)
        self.add_inner_connection(sock_conn_b)
        self.add_inner_connection(sock_conn_c)

        result_conn = Connection()
        result_conn.set_from_info(mix_node, Vec3Interp.SOCK_OUT_RESULT)

        return result_conn


class PrincipledBsdfNode(AbstractGroupNode):
    def __init__(self, pos_x, pos_y):
        super().__init__(pos_x, pos_y)

        self.sock_in_color = AbstractColorInSocket(self)
        self.sock_in_subsurface = AbstractScalarInSocket(self)
        self.sock_in_subsurface_color = AbstractColorInSocket(self)
        self.sock_in_metallic = AbstractScalarInSocket(self)
        self.sock_in_specular = AbstractScalarInSocket(self)
        self.sock_in_roughness = AbstractScalarInSocket(self)
        self.sock_in_clearcoat = AbstractScalarInSocket(self)
        self.sock_in_clearcoat_rougness = AbstractScalarInSocket(self)
        self.sock_in_anisotrophy = AbstractScalarInSocket(self)
        self.sock_in_transmission = AbstractScalarInSocket(self)
        self.sock_in_ior = AbstractScalarInSocket(self)

        self.sock_out_bsdf = AbstractShaderOutSocket(self)

        saturated_metallic = self.scalar_func(
            ScalarFunc.FUNC_SATURATE,
            self.sock_in_metallic.hidden_connection)
        saturated_transmission = self.scalar_func(
            ScalarFunc.FUNC_SATURATE,
            self.sock_in_transmission.hidden_connection)

        # metallic compliment against 1.0
        conn_metallic_cmp = self.scalar_const_op_sock(
            ScalarOp.OP_SUB, 1.0, saturated_metallic)
        # transmission compliment against 1.0
        conn_transmission_cmp = self.scalar_const_op_sock(
            ScalarOp.OP_SUB, 1.0, saturated_metallic)

        # subsurface = subsurface_in * (1.0 - metallic);
        sss_strength = self.scalar_sock_op_sock(
            ScalarOp.OP_MUL,
            self.sock_in_subsurface.hidden_connection,
            conn_metallic_cmp)

        # albedo = mix(color.rgb, subsurface_color.rgb, subsurface);
        out_albedo = self.vec3_mix(
            self.sock_in_color.rgb.hidden_connection,
            self.sock_in_subsurface_color.rgb.hidden_connection,
            sss_strength)
        out_clearcoat = self.scalar_sock_op_sock(
            ScalarOp.OP_MUL,
            self.sock_in_clearcoat.hidden_connection,
            saturated_transmission
        )
        out_clearcoat_glossy = self.scalar_const_op_sock(
            ScalarOp.OP_SUB, 1.0,
            self.sock_in_clearcoat_rougness.hidden_connection
        )
        out_transmission = self.scalar_sock_op_sock(
            ScalarOp.OP_MUL, saturated_transmission, saturated_metallic
        )

        self.sock_out_bsdf.albedo.set_hidden_connection(out_albedo)
        self.sock_out_bsdf.subsurface_scatter.set_hidden_connection(
            sss_strength)
        self.sock_out_bsdf.metallic.set_hidden_connection(saturated_metallic)
        self.sock_out_bsdf.specular.set_hidden_connection(
            self.sock_in_specular.hidden_connection
        )
        self.sock_out_bsdf.roughness.set_hidden_connection(
            self.sock_in_roughness.hidden_connection
        )
        self.sock_out_bsdf.clearcoat.set_hidden_connection(out_clearcoat)
        self.sock_out_bsdf.clearcoat_gloss.set_hidden_connection(
            out_clearcoat_glossy
        )
        self.sock_out_bsdf.anistrophy.set_hidden_connection(
            self.sock_in_anisotrophy.hidden_connection
        )
        self.sock_out_bsdf.transmission.set_hidden_connection(
            out_transmission
        )

    def get_input_socket(self, socket_name):
        input_socket_map = {
            'Base Color': self.sock_in_color,
            'Subsurface': self.sock_in_subsurface,
            'Subsurface Color': self.sock_in_subsurface_color,
            'Metallic': self.sock_in_metallic,
            'Specular': self.sock_in_specular,
            'Roughness': self.sock_in_roughness,
            'Anisotropic': self.sock_in_anisotrophy,
            'Clearcoat': self.sock_in_clearcoat,
            'Clearcoat Roughness': self.sock_in_clearcoat_rougness,
            'IOR': self.sock_in_ior,
            'Transmission': self.sock_in_transmission,
        }
        return input_socket_map.get(socket_name, None)

    def get_output_socket(self, socket_name):
        if socket_name == 'BSDF':
            return self.sock_out_bsdf
        return None
