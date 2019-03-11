"""Data structure represents the link between 'SHADER' type sockets"""


class FragmentShaderLink:
    # pylint: disable-msg=too-many-instance-attributes
    """due to not able to make a closure for SHADER link as blender does,
    here aggregate godot fragment shader output to simulate"""
    ALBEDO = 'albedo'
    ALPHA = 'alpha'
    SSS_STRENGTH = 'sss_strength'
    SPECULAR = 'specular'
    METALLIC = 'metallic'
    ROUGHNESS = 'roughness'
    OREN_NAYAR_ROUGHNESS = 'oren_nayar_roughness'
    CLEARCOAT = 'clearcoat'
    CLEARCOAT_GLOSS = 'clearcoat_gloss'
    ANISOTROPY = 'anisotropy'
    TRANSMISSION = 'transmission'
    IOR = 'ior'
    EMISSION = 'emission'
    NORMAL = 'normal'
    TANGENT = 'tangent'

    TYPES = {
        ALBEDO: 'vec3',
        ALPHA: 'float',
        SSS_STRENGTH: 'float',
        SPECULAR: 'float',
        METALLIC: 'float',
        ROUGHNESS: 'float',
        OREN_NAYAR_ROUGHNESS: 'float',
        CLEARCOAT: 'float',
        CLEARCOAT_GLOSS: 'float',
        ANISOTROPY: 'float',
        TRANSMISSION: 'float',
        IOR: 'float',
        EMISSION: 'vec3',
        NORMAL: 'vec3',
        TANGENT: 'vec3',
    }

    ALL_PROPERTIES = (
        ALBEDO, ALPHA, SSS_STRENGTH, SPECULAR,
        METALLIC, ROUGHNESS, OREN_NAYAR_ROUGHNESS,
        CLEARCOAT, CLEARCOAT_GLOSS, ANISOTROPY,
        TRANSMISSION, IOR, EMISSION, NORMAL, TANGENT
    )

    def __init__(self):
        # default only has albedo
        self.albedo = None
        self.alpha = None
        self.sss_strength = None
        self.specular = None
        self.metallic = None
        self.roughness = None
        self.oren_nayar_roughness = None
        self.clearcoat = None
        self.clearcoat_gloss = None
        self.anisotropy = None
        self.transmission = None
        self.ior = None
        self.emission = None
        self.normal = None
        self.tangent = None

    def set_property(self, prop_name, new_var):
        """set an inner property of shader link"""
        setattr(self, prop_name, new_var)

    def get_property(self, prop_name):
        """get the value of an inner property"""
        return getattr(self, prop_name)

    @classmethod
    def get_property_type(cls, prop_name):
        """get property type in string format"""
        return cls.TYPES[prop_name]
