class Connection:
    def __init__(self):
        self.from_node = None
        self.to_node = None
        self.from_socket = None
        self.to_socket = None

    def set_to_info(self, to_node, to_socket):
        assert self.to_node is None
        self.to_node = to_node
        self.to_socket = to_socket

    def set_from_info(self, from_node, from_socket):
        assert self.from_node is None
        self.from_node = from_node
        self.from_socket = from_socket

    def is_dual_connected(self):
        return (self.from_node is not None and
                self.to_node is not None)


class Socket:
    VEC3 = "vec3"
    SCALAR = "scalar"

    def __init__(self, socket_type):
        self._type = socket_type

    def get_type(self):
        return self._type


class VisualNodeVec3Socket(Socket):
    def __init__(self, socket_idx):
        super().__init__(Socket.VEC3)
        self._index = socket_idx

    def get_index(self):
        return self._index


class VisualNodeScalarSocket(Socket):
    def __init__(self, socket_idx):
        super().__init__(Socket.SCALAR)
        self._index = socket_idx

    def get_index(self):
        return self._index


class AbstractInSocket(Socket):
    def __init__(self, socket_type, node_ref):
        super().__init__(socket_type)
        self.node = node_ref
        self.hidden_connection = Connection()
        self.hidden_connection.set_from_info(self.node, self)
        self.input_connection = None

    def set_input(self, conn):
        assert self.input_connection is None
        conn.set_to_info(self.node, self)
        self.input_connection = conn


class AbstractOutSocket(Socket):
    def __init__(self, socket_type, node_ref):
        super().__init__(socket_type)
        self.node = node_ref
        self.hidden_connection = None
        self.output_connections = list()

    def set_hidden_connection(self, conn):
        self.hidden_connection = conn
        self.hidden_connection.set_to_info(self.node, self)

    def append_output(self, conn):
        conn.set_from_info(self.node, self)
        self.output_connections.append(conn)

    def is_valid(self):
        return self.hidden_connection is not None


class AbstractVec3InSocket(AbstractInSocket):
    def __init__(self, node_ref):
        super().__init__(self, Socket.VEC3)


class AbstractScalarInSocket(AbstractInSocket):
    def __init__(self, node_ref):
        super().__init__(self, Socket.SCALAR)


class AbstractColorInSocket:
    def __init__(self, node_ref):
        self.rgb = AbstractVec3InSocket(node_ref)
        self.alpha = AbstractScalarInSocket(node_ref)


class AbstractVec3OutSocket(AbstractOutSocket):
    def __init__(self, node_ref):
        super().__init__(self, Socket.VEC3)


class AbstractScalarOutSocket(AbstractOutSocket):
    def __init__(self, node_ref):
        super().__init__(self, Socket.SCALAR)


class AbstractColorOutSocket:
    def __init__(self, node_ref):
        self.rgb = AbstractVec3OutSocket(node_ref)
        self.alpha = AbstractScalarOutSocket(node_ref)


class AbstractShaderSocket:
    INNER_SOCKET_LIST = [
        "albedo",
        "emission",
        "anistrophy_flow",
        "transmission",
        "normal",

        "alpha",
        "metallic",
        "roughness",
        "specular",
        "ambient_occ",
        "rim",
        "rim_tint",
        "clearcoat",
        "clearcoat_gloss",
        "anistrophy",
        "subsurface_scatter",
        "alpha_scissor",
        "ao_light_effect",
    ]

    def get_inner_socket(self, socket_name):
        return getattr(self, socket_name)


class AbstractShaderInSocket(AbstractShaderSocket):
    def __init__(self, node_ref):
        self.albedo = AbstractVec3InSocket(node_ref)
        self.emission = AbstractVec3InSocket(node_ref)
        self.anistrophy_flow = AbstractVec3InSocket(node_ref)
        self.transmission = AbstractVec3InSocket(node_ref)
        self.normal = AbstractVec3InSocket(node_ref)

        self.alpha = AbstractScalarInSocket(node_ref)
        self.metallic = AbstractScalarInSocket(node_ref)
        self.roughness = AbstractScalarInSocket(node_ref)
        self.specular = AbstractScalarInSocket(node_ref)
        self.ambient_occ = AbstractScalarInSocket(node_ref)
        self.rim = AbstractScalarInSocket(node_ref)
        self.rim_tint = AbstractScalarInSocket(node_ref)
        self.clearcoat = AbstractScalarInSocket(node_ref)
        self.clearcoat_gloss = AbstractScalarInSocket(node_ref)
        self.anistrophy = AbstractScalarInSocket(node_ref)
        self.subsurface_scatter = AbstractScalarInSocket(node_ref)
        self.alpha_scissor = AbstractScalarInSocket(node_ref)
        self.ao_light_effect = AbstractScalarInSocket(node_ref)
        # self.normal_map
        # self.normal_map_depth


class AbstractShaderOutSocket(AbstractShaderSocket):
    def __init__(self, node_ref):
        self.albedo = AbstractVec3OutSocket(node_ref)
        self.emission = AbstractVec3OutSocket(node_ref)
        self.anistrophy_flow = AbstractVec3OutSocket(node_ref)
        self.transmission = AbstractVec3OutSocket(node_ref)
        self.normal = AbstractVec3OutSocket(node_ref)

        self.alpha = AbstractScalarOutSocket(node_ref)
        self.metallic = AbstractScalarOutSocket(node_ref)
        self.roughness = AbstractScalarOutSocket(node_ref)
        self.specular = AbstractScalarOutSocket(node_ref)
        self.ambient_occ = AbstractScalarOutSocket(node_ref)
        self.rim = AbstractScalarOutSocket(node_ref)
        self.rim_tint = AbstractScalarOutSocket(node_ref)
        self.clearcoat = AbstractScalarOutSocket(node_ref)
        self.clearcoat_gloss = AbstractScalarOutSocket(node_ref)
        self.anistrophy = AbstractScalarOutSocket(node_ref)
        self.subsurface_scatter = AbstractScalarOutSocket(node_ref)
        self.alpha_scissor = AbstractScalarOutSocket(node_ref)
        self.ao_light_effect = AbstractScalarOutSocket(node_ref)
