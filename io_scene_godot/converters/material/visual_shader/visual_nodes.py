from mathutils import Vector
from .sockets import VisualNodeVec3Socket, VisualNodeScalarSocket, AbstractShaderInSocket
from ....structures import InternalResource


class VisualNode(InternalResource):
    def __init__(self, rsc_type, pos_tuple=(0, 0)):
        super().__init__(rsc_type)
        self._position = Vector(pos_tuple)

    def set_position(self, pos_tuple):
        self._position = Vector(pos_tuple)

    def get_position(self):
        return self._position


class ScalarFunc(VisualNode):
    # function index
    FUNC_SIN = 0
    FUNC_COS = 1
    FUNC_TAN = 2
    FUNC_ASIN = 3
    FUNC_ACOS = 4
    FUNC_ATAN = 5
    FUNC_SINH = 6
    FUNC_COSH = 7
    FUNC_TANH = 8
    FUNC_LOG = 9
    FUNC_EXP = 10
    FUNC_SQRT = 11
    FUNC_ABS = 12
    FUNC_SIGN = 13
    FUNC_FLOOR = 14
    FUNC_ROUND = 15
    FUNC_CEIL = 16
    FUNC_FRAC = 17
    FUNC_SATURATE = 18
    FUNC_NEGATE = 19

    SOCK_IN_ARG = VisualNodeScalarSocket(0)

    SOCK_OUT_RESULT = VisualNodeScalarSocket(0)

    def __init__(self, func):
        super().__init__("VisualShaderNodeScalarFunc")
        self['function'] = func


class ScalarOp(VisualNode):
    # function index
    OP_ADD = 0
    OP_SUB = 1
    OP_MUL = 2
    OP_DIV = 3
    OP_MOD = 4
    OP_POW = 5
    OP_MAX = 6
    OP_MIN = 7
    OP_ATAN2 = 8

    SOCK_IN_A = VisualNodeScalarSocket(0)
    SOCK_IN_B = VisualNodeScalarSocket(1)

    SOCK_OUT_RESULT = VisualNodeScalarSocket(0)

    def __init__(self, op):
        super().__init__("VisualShaderNodeScalarOp")
        self['operator'] = op


class ScalarInterp(VisualNode):
    SOCK_IN_A = VisualNodeScalarSocket(0)
    SOCK_IN_B = VisualNodeScalarSocket(1)
    SOCK_IN_C = VisualNodeScalarSocket(2)

    SOCK_OUT_RESULT = VisualNodeScalarSocket(0)

    def __init__(self):
        super().__init__("VisualShaderNodeScalarInterp")


class ScalarConstant(VisualNode):
    SOCK_OUT_VALUE = VisualNodeScalarSocket(0)

    def __init__(self, const_val):
        super().__init__("VisualShaderNodeScalarConstant")
        self['constant'] = const_val


class Vec3Interp(VisualNode):
    SOCK_IN_A = VisualNodeVec3Socket(0)
    SOCK_IN_B = VisualNodeVec3Socket(1)
    SOCK_IN_C = VisualNodeVec3Socket(2)

    SOCK_OUT_RESULT = VisualNodeVec3Socket(0)

    def __init__(self):
        super().__init__("VisualShaderNodeVectorInterp")


class Vec3Func(VisualNode):
    FUNC_NORMALIZE = 0
    FUNC_SATURATE = 1
    FUNC_NEGATE = 2
    FUNC_RECIPROCAL = 3
    FUNC_RGB2HSV = 4
    FUNC_HSV2RGB = 5

    SOCK_IN_ARG = VisualNodeVec3Socket(0)

    SOCK_OUT_RESULT = VisualNodeVec3Socket(0)

    def __init__(self, func):
        super().__init__("VisualShaderNodeVectorFunc")
        self['function'] = func


class Vec3Op(VisualNode):
    OP_ADD = 0
    OP_SUB = 1
    OP_MUL = 2
    OP_DIV = 3
    OP_MOD = 4
    OP_POW = 5
    OP_MAX = 6
    OP_MIN = 7
    OP_CROSS = 8

    SOCK_IN_A = VisualNodeVec3Socket(0)
    SOCK_IN_B = VisualNodeVec3Socket(1)

    SOCK_OUT_RESULT = VisualNodeVec3Socket(0)

    def __init__(self, op):
        super().__init__("VisualShaderNodeVectorOp")
        self['operator'] = op


class Vec3Constant(VisualNode):
    SOCK_OUT_VALUE = VisualNodeVec3Socket(0)

    def __init__(self, val_tuple):
        super().__init__("VisualShaderNodeVectorConstant")
        assert isinstance(val_tuple, tuple)
        assert len(val_tuple) == 3
        self['constant'] = "Vector3( %f, %f, %f )" % val_tuple


class FragmentOutputNode:
    def __init__(self, pos_x, pos_y):
        self.position = Vector((pos_x, pos_y))
        self.sock_in_surface = AbstractShaderInSocket(self)

        self.sock_in_surface.albedo = VisualNodeVec3Socket(0)
        self.sock_in_surface.metallic = VisualNodeScalarSocket(1)
        self.sock_in_surface.roughness = VisualNodeScalarSocket(2)
        self.sock_in_surface.specular = VisualNodeScalarSocket(3)
        self.sock_in_surface.emission = VisualNodeVec3Socket(4)
        self.sock_in_surface.ambient_occ = VisualNodeScalarSocket(5)
        self.sock_in_surface.normal = VisualNodeVec3Socket(6)
        # self.sock_in_surface.normal_map
        # self.sock_in_surface.normal_map_depth
        self.sock_in_surface.rim = VisualNodeScalarSocket(9)
        self.sock_in_surface.rim_tint = VisualNodeScalarSocket(10)
        self.sock_in_surface.clearcoat = VisualNodeScalarSocket(11)
        self.sock_in_surface.clearcoat_gloss = VisualNodeScalarSocket(12)
        self.sock_in_surface.anistrophy = VisualNodeScalarSocket(13)
        self.sock_in_surface.anistrophy_flow = VisualNodeVec3Socket(14)
        self.sock_in_surface.subsurface_scatter = VisualNodeScalarSocket(15)
        self.sock_in_surface.transmission = VisualNodeVec3Socket(16)
        self.sock_in_surface.alpha_scissor = VisualNodeScalarSocket(17)
        self.sock_in_surface.ao_light_effect = VisualNodeScalarSocket(18)

    def get_input_socket(self, socket_name):
        if socket_name == 'Surface':
            return self.sock_in_surface
        return None
