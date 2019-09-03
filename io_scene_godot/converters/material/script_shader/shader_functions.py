"""Prewritten shader scripts for node in material node tree,
reference: 'https://developer.blender.org/diffusion/B/browse/
master/source/blender/gpu/shaders/gpu_shader_material.glsl'"""
import re
from .shader_links import FragmentShaderLink
from ....structures import ValidationError

FUNCTION_HEAD_PATTERN = re.compile(
    (r'void\s+([a-zA-Z]\w*)\s*\(((\s*((in|inout|out)\s+)?'
     r'(vec2|vec3|vec4|float|mat4|sampler2D)\s+[a-zA-Z]\w*\s*,?)*)\)'),
)


class ShaderFunction:
    """Shader function for a blender node"""

    def __init__(self, code):
        # at most one group
        self.code = code
        self.in_param_types = list()
        self.out_param_types = list()

        matched_group = FUNCTION_HEAD_PATTERN.findall(code)[0]
        self.name = matched_group[0]
        parameters_str = matched_group[1]

        for param_str in parameters_str.strip().split(','):
            tokens = tuple([x.strip() for x in param_str.split()])
            if tokens[0] == 'out':
                self.out_param_types.append(tokens[1])
            else:  # 'in', 'inout'
                self.in_param_types.append(tokens[0])

    def __hash__(self):
        return hash(self.name)


class BsdfShaderFunction(ShaderFunction):
    """Function for bsdf shader node, has additional information of
    input and output socket"""

    def __init__(self, code, input_sockets, output_properties):
        super().__init__(code)
        # linked socket ids of material node
        self.in_sockets = tuple(input_sockets)
        self.output_properties = tuple(output_properties)


# Shader function nameing convention:
#
# The approach adopted by this addon to export material node is to
# convert it to a shader function. In order to simplify the mapping
# from Blender node to shader function, there is a naming convention
# for all the node functions.
#
# Blender node all have a entry `bl_idname` which is in the format
# of `ShaderNodexxx`. For an arbitrary Blender node, we drop the prefix
# in its `bl_idname` and convert it to snake case as the corresponding
# function name.
#
#   e.g. Blender node 'ShaderNodeBsdfPrincipled',
#           it's function name is node_bsdf_principled
#
# You may notice some Blender node has options like `space`, `operation`.
# In that case, if we want to convert node with differnet options to
# different functions, we are append the lowercased option string to the
# end of a function name.
#
#   e.g. Blender node 'ShaderNodeMath' with `operation` set as 'ADD',
#     `clamp` not checked. It's function name is 'node_math_add_no_clamp'.

FUNCTION_LIBS = [
    # bsdf shader node functions
    BsdfShaderFunction(
        code="""
void node_bsdf_principled(vec4 color, float subsurface, vec4 subsurface_color,
        float metallic, float specular, float roughness, float clearcoat,
        float clearcoat_roughness, float anisotropy, float transmission,
        float IOR, out vec3 albedo, out float sss_strength_out,
        out float metallic_out, out float specular_out,
        out float roughness_out, out float clearcoat_out,
        out float clearcoat_gloss_out, out float anisotropy_out,
        out float transmission_out, out float ior) {
    metallic = clamp(metallic, 0.0, 1.0);
    transmission = clamp(transmission, 0.0, 1.0);

    subsurface = subsurface * (1.0 - metallic);

    albedo = mix(color.rgb, subsurface_color.rgb, subsurface);
    sss_strength_out = subsurface;
    metallic_out = metallic;
    specular_out = pow((IOR - 1.0)/(IOR + 1.0), 2)/0.08;
    roughness_out = roughness;
    clearcoat_out = clearcoat * (1.0 - transmission);
    clearcoat_gloss_out = 1.0 - clearcoat_roughness;
    anisotropy_out = clamp(anisotropy, 0.0, 1.0);
    transmission_out = (1.0 - transmission) * (1.0 - metallic);
    ior = IOR;
}
""",
        input_sockets=[
            "Base Color",
            "Subsurface",
            "Subsurface Color",
            "Metallic",
            "Specular",
            "Roughness",
            "Clearcoat",
            "Clearcoat Roughness",
            "Anisotropic",
            "Transmission",
            "IOR",
        ],
        output_properties=[
            FragmentShaderLink.ALBEDO,
            FragmentShaderLink.SSS_STRENGTH,
            FragmentShaderLink.METALLIC,
            FragmentShaderLink.SPECULAR,
            FragmentShaderLink.ROUGHNESS,
            FragmentShaderLink.CLEARCOAT,
            FragmentShaderLink.CLEARCOAT_GLOSS,
            FragmentShaderLink.ANISOTROPY,
            FragmentShaderLink.TRANSMISSION,
            FragmentShaderLink.IOR,
        ]
    ),

    BsdfShaderFunction(
        code="""
void node_emission(vec4 emission_color, float strength,
        out vec3 emission_out, out float alpha_out) {
    emission_out = emission_color.rgb * strength;
    alpha_out = emission_color.a;
}
""",
        input_sockets=["Color", "Strength"],
        output_properties=[
            FragmentShaderLink.EMISSION,
            FragmentShaderLink.ALPHA,
        ]
    ),

    BsdfShaderFunction(
        code="""
void node_bsdf_diffuse(vec4 color, float roughness, out vec3 albedo,
        out float specular_out, out float oren_nayar_roughness_out) {
    albedo = color.rgb;
    specular_out = 0.5;
    oren_nayar_roughness_out = roughness;
}
""",
        input_sockets=[
            "Color",
            "Roughness",
        ],
        output_properties=[
            FragmentShaderLink.ALBEDO,
            FragmentShaderLink.SPECULAR,
            FragmentShaderLink.OREN_NAYAR_ROUGHNESS,
        ]
    ),

    BsdfShaderFunction(
        code="""
void node_bsdf_glossy(vec4 color, float roughness, out vec3 albedo,
        out float metallic_out, out float roughness_out) {
    albedo = color.rgb;
    roughness_out = roughness;
    metallic_out = 1.0;
}
""",
        input_sockets=[
            "Color",
            "Roughness",
        ],
        output_properties=[
            FragmentShaderLink.ALBEDO,
            FragmentShaderLink.METALLIC,
            FragmentShaderLink.ROUGHNESS,
        ]
    ),

    BsdfShaderFunction(
        code="""
void node_bsdf_transparent(vec4 color, out float alpha) {
    alpha = clamp(1.0 - dot(color.rgb, vec3(0.3333334)), 0.0, 1.0);
}
""",
        input_sockets=['Color'],
        output_properties=[FragmentShaderLink.ALPHA],
    ),

    BsdfShaderFunction(
        code="""
void node_bsdf_glass(vec4 color, float roughness, float IOR, out vec3 albedo,
        out float alpha, out float specular_out, out float roughness_out,
        out float transmission_out, out float ior) {
    albedo = color.rgb;
    alpha = 0.0;
    specular_out = pow((IOR - 1.0)/(IOR + 1.0), 2)/0.08;
    roughness_out = roughness;
    transmission_out = 0.0;
    ior = IOR;
}
""",
        input_sockets=[
            "Color",
            "Roughness",
            "IOR",
        ],
        output_properties=[
            FragmentShaderLink.ALBEDO,
            FragmentShaderLink.ALPHA,
            FragmentShaderLink.SPECULAR,
            FragmentShaderLink.ROUGHNESS,
            FragmentShaderLink.TRANSMISSION,
            FragmentShaderLink.IOR,
        ]
    ),

    # trivial converter node functions
    ShaderFunction(code="""
void node_rgb_to_bw(vec4 color, out float result) {
    result = color.r * 0.2126 + color.g * 0.7152 + color.b * 0.0722;
}
"""),

    ShaderFunction(code="""
void node_separate_xyz(vec3 in_vec, out float x, out float y, out float z) {
    x = in_vec.x;
    y = in_vec.y;
    z = in_vec.z;
}
"""),

    ShaderFunction(code="""
void node_separate_rgb(vec4 color, out float r, out float g, out float b) {
    r = color.r;
    g = color.g;
    b = color.b;
}
"""),

    ShaderFunction(code="""
void node_combine_rgb(float r, float g, float b, out vec4 color) {
    color = vec4(r, g, b, 1.0);
}
"""),

    ShaderFunction(code="""
void node_mix_rgb_mix(float fac, vec4 in_color1, vec4 in_color2,
                      out vec4 out_color) {
    out_color = mix(in_color1, in_color2, fac);
    out_color.a = in_color1.a;
}
"""),

    ShaderFunction(code="""
void node_mix_rgb_add(float fac, vec4 in_color1, vec4 in_color2,
                      out vec4 out_color) {
    out_color = mix(in_color1, in_color1 + in_color2, fac);
    out_color.a = in_color1.a;
}
"""),

    ShaderFunction(code="""
void node_mix_rgb_subtract(float fac, vec4 in_color1, vec4 in_color2,
                           out vec4 out_color) {
    out_color = mix(in_color1, in_color1 - in_color2, fac);
    out_color.a = in_color1.a;
}
"""),

    ShaderFunction(code="""
void node_mix_rgb_multiply(float fac, vec4 in_color1, vec4 in_color2,
                           out vec4 out_color) {
    out_color = mix(in_color1, in_color1 * in_color2, fac);
    out_color.a = in_color1.a;
}
"""),

    ShaderFunction(code="""
void node_mix_rgb_divide(float fac, vec4 in_color1, vec4 in_color2,
                         out vec4 out_color) {
    float fac_cpl = 1.0 - fac;
    out_color = in_color1;
    if (in_color2.r != 0.0) {
        out_color.r = fac_cpl * in_color1.r +  fac * in_color1.r / in_color2.r;
    }
    if (in_color2.g != 0.0) {
        out_color.g = fac_cpl * in_color1.g +  fac * in_color1.g / in_color2.g;
    }
    if (in_color2.b != 0.0) {
        out_color.b = fac_cpl * in_color1.b +  fac * in_color1.b / in_color2.b;
    }
}
"""),

    ShaderFunction(code="""
void node_mix_rgb_difference(float fac, vec4 in_color1, vec4 in_color2,
                             out vec4 out_color) {
    out_color = mix(in_color1, abs(in_color1 - in_color2), fac);
    out_color.a = in_color1.a;
}
"""),

    ShaderFunction(code="""
void node_mix_rgb_darken(float fac, vec4 in_color1, vec4 in_color2,
                         out vec4 out_color) {
    out_color.rgb = min(in_color1.rgb, in_color2.rgb * fac);
    out_color.a = in_color1.a;
}
"""),

    ShaderFunction(code="""
void node_mix_rgb_lighten(float fac, vec4 in_color1, vec4 in_color2,
                          out vec4 out_color) {
    out_color.rgb = max(in_color1.rgb, in_color2.rgb * fac);
    out_color.a = in_color1.a;
}
"""),

    ShaderFunction(code="""
void node_bump(float strength, float dist, float height, vec3 normal,
               vec3 surf_pos, float invert, out vec3 out_normal) {
    if (invert != 0.0) {
        dist *= -1.0;
    }
    vec3 dPdx = dFdx(surf_pos);
    vec3 dPdy = dFdy(surf_pos);

    /* Get surface tangents from normal. */
    vec3 Rx = cross(dPdy, normal);
    vec3 Ry = cross(normal, dPdx);

    /* Compute surface gradient and determinant. */
    float det = dot(dPdx, Rx);
    float absdet = abs(det);

    float dHdx = dFdx(height);
    float dHdy = dFdy(height);
    vec3 surfgrad = dHdx * Rx + dHdy * Ry;

    strength = max(strength, 0.0);

    out_normal = normalize(absdet * normal - dist * sign(det) * surfgrad);
    out_normal = normalize(strength * out_normal + (1.0 - strength) * normal);
}
"""),

    ShaderFunction(code="""
void node_normal_map_tangent(float strength, vec4 color, vec3 normal,
        vec3 tangent, vec3 binormal, out vec3 out_normal) {
    vec3 signed_color = vec3(2.0, -2.0, 2.0) * (color.xzy - vec3(0.5));
    vec3 tex_normal = signed_color.x * tangent +
                      signed_color.y * binormal +
                      signed_color.z * normal;
    out_normal = strength * tex_normal + (1.0 - strength) * normal;
}
"""),

    ShaderFunction(code="""
void node_normal_map_world(float strength, vec4 color, vec3 view_normal,
        mat4 inv_view_mat, out vec3 out_normal) {
    vec3 tex_normal = vec3(2.0, -2.0, -2.0) * (color.xzy - vec3(0.5));
    vec3 world_normal = (inv_view_mat * vec4(view_normal, 0.0)).xyz;
    out_normal = strength * tex_normal + (1.0 - strength) * world_normal;
}
"""),

    ShaderFunction(code="""
void node_normal_map_object(float strength, vec4 color, vec3 view_normal,
        mat4 inv_view_mat, mat4 model_mat, out vec3 out_normal) {
    vec3 signed_color = vec3(2.0, -2.0, -2.0) * (color.xzy - vec3(0.5));
    vec3 tex_normal = (model_mat * vec4(signed_color, 0.0)).xyz;
    vec3 world_normal = (inv_view_mat * vec4(view_normal, 0.0)).xyz;
    out_normal = strength * tex_normal + (1.0 - strength) * world_normal;
}
"""),

    ShaderFunction(code="""
void node_tex_image(vec3 co, sampler2D ima, out vec4 color, out float alpha) {
    color = texture(ima, co.xy);
    alpha = color.a;
}
"""),

    ShaderFunction(code="""
void node_gamma(vec4 color, float gamma, out vec4 out_color) {
    out_color = color
    if (out_color.r > 0.0) {
        out_color.r = pow(color.r, gamma);
    }
    if (out_color.g > 0.0) {
        out_color.g = pow(color.g, gamma);
    }
    if (out_color.b > 0.0) {
        out_color.b = pow(color.b, gamma);
    }
}
"""),

    ShaderFunction(code="""
void node_mapping(vec3 vec, mat4 mat, vec3 minvec, vec3 maxvec, float domin,
        float domax, out vec3 outvec) {
    outvec = (mat * vec4(vec, 1.0)).xyz;
    if (domin == 1.0) {
        outvec = max(outvec, minvec);
    }
    if (domax == 1.0) {
        outvec = min(outvec, maxvec);
    }
}
"""),

    ShaderFunction(code="""
void node_math_add_no_clamp(float value1, float value2, out float result) {
    result = value1 +  value2;
}
"""),

    ShaderFunction(code="""
void node_math_subtract_no_clamp(float value1, float value2,
        out float result) {
    result = value1 - value2;
}
"""),

    ShaderFunction(code="""
void node_math_multiply_no_clamp(float value1, float value2,
        out float result) {
    result = value1 * value2;
}
"""),

    ShaderFunction(code="""
void node_math_divide_no_clamp(float value1, float value2, out float result) {
    if (value2 == 0.0)
        result = 0.0;
    else
        result = value1 / value2;
}
"""),

    ShaderFunction(code="""
void node_math_power_no_clamp(float val1, float val2, out float outval) {
    outval = pow(val1, val2);
}
"""),

    ShaderFunction(code="""
void node_math_logarithm_no_clamp(float val1, float val2, out float outval) {
    if (val1 > 0.0  && val2 > 0.0)
        outval = log2(val1) / log2(val2);
    else
        outval = 0.0;
}
"""),

    ShaderFunction(code="""
void node_math_sqrt_no_clamp(float value1, float value2, out float result) {
    result = sqrt(value1);
}
"""),

    ShaderFunction(code="""
void node_math_absolute_no_clamp(float value1, float value2, out float result) {
    result = abs(value1);
}
"""),

    ShaderFunction(code="""
void node_math_minimum_no_clamp(float value1, float value2, out float result) {
    result = min(value1, value2);
}
"""),

    ShaderFunction(code="""
void node_math_maximum_no_clamp(float value1, float value2, out float result) {
    result = max(value1, value2);
}
"""),

    ShaderFunction(code="""
void node_math_less_than_no_clamp(float value1, float value2, out float result) {
    result = float(value1 < value2);
}
"""),

    ShaderFunction(code="""
void node_math_greater_than_no_clamp(float value1, float value2, out float result) {
    result = float(value1 > value2);
}
"""),

    ShaderFunction(code="""
void node_math_round_no_clamp(float value1, float value2, out float result) {
    result = round(value1);
}
"""),

    ShaderFunction(code="""
void node_math_floor_no_clamp(float value1, float value2, out float result) {
    result = floor(value1);
}
"""),

    ShaderFunction(code="""
void node_math_ceil_no_clamp(float value1, float value2, out float result) {
    result = ceil(value1);
}
"""),

    ShaderFunction(code="""
void node_math_fract_no_clamp(float value1, float value2, out float result) {
    result = fract(value1);
}
"""),

    ShaderFunction(code="""
void node_math_modulo_no_clamp(float value1, float value2, out float result) {
    result = mod(value1, value2);
}
"""),

    ShaderFunction(code="""
void node_math_sine_no_clamp(float value1, float value2, out float result) {
    result = sin(value1);
}
"""),

    ShaderFunction(code="""
void node_math_cosine_no_clamp(float value1, float value2, out float result) {
    result = cos(value1);
}
"""),

    ShaderFunction(code="""
void node_math_tangent_no_clamp(float value1, float value2, out float result) {
    result = tan(value1);
}
"""),

    ShaderFunction(code="""
void node_math_arcsine_no_clamp(float value1, float value2, out float result) {
    if (value1 < 0.0 || value1 > 1.0)
        result = 0.0;
    else
        result = asin(value1);
}
"""),

    ShaderFunction(code="""
void node_math_arccosine_no_clamp(float value1, float value2, out float result) {
    if (value1 < 0.0 || value1 > 1.0)
        result = 0.0;
    else
        result = acos(value1);
}
"""),

    ShaderFunction(code="""
void node_math_arctangent_no_clamp(float value1, float value2, out float result) {
    result = atan(value1);
}
"""),

    ShaderFunction(code="""
void node_math_arctan2_no_clamp(float value1, float value2, out float result) {
    result = atan(value1, value2);
}
"""),

    ShaderFunction(code="""
void node_math_add_clamp(float value1, float value2, out float result) {
    result = clamp(value1 + value2, 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_subtract_clamp(float value1, float value2, out float result) {
    result = clamp(value1 - value2, 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_multiply_clamp(float value1, float value2, out float result) {
    result = clamp(value1 * value2, 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_divide_clamp(float value1, float value2, out float result) {
    if (value2 == 0.0)
        result = 0.0;
    else
        result = clamp(value1 / value2, 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_power_clamp(float val1, float val2, out float outval) {
    outval = clamp(pow(val1, val2), 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_logarithm_clamp(float val1, float val2, out float outval) {
    if (val1 > 0.0  && val2 > 0.0)
        outval = clamp(log2(val1) / log2(val2), 0.0, 1.0);
    else
        outval = 0.0;
}
"""),

    ShaderFunction(code="""
void node_math_sqrt_clamp(float value1, float value2, out float result) {
    result = clamp(sqrt(value1), 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_absolute_clamp(float value1, float value2, out float result) {
    result = clamp(abs(value1), 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_minimum_clamp(float value1, float value2, out float result) {
    result = clamp(min(value1, value2), 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_maximum_clamp(float value1, float value2, out float result) {
    result = clamp(max(value1, value2), 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_less_than_clamp(float value1, float value2, out float result) {
    result = clamp(float(value1 < value2), 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_greater_than_clamp(float value1, float value2, out float result) {
    result = clamp(float(value1 > value2), 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_round_clamp(float value1, float value2, out float result) {
    result = clamp(round(value1), 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_floor_clamp(float value1, float value2, out float result) {
    result = clamp(floor(value1), 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_ceil_clamp(float value1, float value2, out float result) {
    result = clamp(ceil(value1), 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_fract_clamp(float value1, float value2, out float result) {
    result = clamp(fract(value1), 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_modulo_clamp(float value1, float value2, out float result) {
    result = clamp(mod(value1, value2), 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_sine_clamp(float value1, float value2, out float result) {
    result = clamp(sin(value1), 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_cosine_clamp(float value1, float value2, out float result) {
    result = clamp(cos(value1), 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_tangent_clamp(float value1, float value2, out float result) {
    result = clamp(tan(value1), 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_arcsine_clamp(float value1, float value2, out float result) {
    if (value1 < 0.0 || value1 > 1.0)
        result = 0.0;
    else
        result = clamp(asin(value1), 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_arccosine_clamp(float value1, float value2, out float result) {
    if (value1 < 0.0 || value1 > 1.0)
        result = 0.0;
    else
        result = clamp(acos(value1), 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_arctangent_clamp(float value1, float value2, out float result) {
    result = clamp(atan(value1), 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_math_arctan2_clamp(float value1, float value2, out float result) {
    result = clamp(atan(value1, value2), 0.0, 1.0);
}
"""),

    ShaderFunction(code="""
void node_vector_math_add(vec3 v1, vec3 v2, out vec3 outvec,
        out float outval) {
    outvec = v1 + v2;
    outval = (abs(outvec[0]) + abs(outvec[1]) + abs(outvec[2])) * 0.333333;
}
"""),

    ShaderFunction(code="""
void node_vector_math_subtract(vec3 v1, vec3 v2, out vec3 outvec,
        out float outval) {
    outvec = v1 - v2;
    outval = (abs(outvec[0]) + abs(outvec[1]) + abs(outvec[2])) * 0.333333;
}
"""),

    ShaderFunction(code="""
void node_vector_math_averate(vec3 v1, vec3 v2, out vec3 outvec,
        out float outval) {
    outvec = v1 + v2;
    outval = length(outvec);
    outvec = normalize(outvec);
}
"""),

    ShaderFunction(code="""
void node_vector_math_dot_product(vec3 v1, vec3 v2, out vec3 outvec,
        out float outval) {
    outvec = vec3(0);
    outval = dot(v1, v2);
}
"""),

    ShaderFunction(code="""
void node_vector_math_cross_product(vec3 v1, vec3 v2, out vec3 outvec,
        out float outval) {
    outvec = cross(v1, v2);
    outval = length(outvec);
    outvec /= outval;
}
"""),

    ShaderFunction(code="""
void node_vector_math_normalize(vec3 v, out vec3 outvec, out float outval) {
  outval = length(v);
  outvec = normalize(v);
}
"""),

    # non-node function:
    ShaderFunction(code="""
void space_convert_zup_to_yup(inout vec3 dir) {
    dir = mat3(vec3(1, 0, 0), vec3(0, 0, -1), vec3(0, 1, 0)) * dir;
}
"""),

    ShaderFunction(code="""
void space_convert_yup_to_zup(inout vec3 dir) {
    dir = mat3(vec3(1, 0, 0), vec3(0, 0, 1), vec3(0, -1, 0)) * dir;
}
"""),

    ShaderFunction(code="""
void dir_space_convert_view_to_model(inout vec3 dir,
        in mat4 inv_model_mat, in mat4 inv_view_mat) {
    dir = normalize( inv_model_mat * (inv_view_mat * vec4(dir, 0.0))).xyz;
}
"""),

    ShaderFunction(code="""
void point_space_convert_view_to_model(inout vec3 pos,
        in mat4 inv_model_mat, in mat4 inv_view_mat) {
    pos = (inv_model_mat * (inv_view_mat * vec4(pos, 1.0))).xyz;
}
"""),

    ShaderFunction(code="""
void dir_space_convert_model_to_view(inout vec3 dir,
        in mat4 view_mat, in mat4 model_mat) {
    dir = normalize(view_mat * (model_mat * vec4(dir, 0.0))).xyz;
}
"""),

    ShaderFunction(code="""
void point_space_convert_model_to_view(inout vec3 pos,
        in mat4 view_mat, in mat4 model_mat) {
    pos = (view_mat * (model_mat * vec4(pos, 1.0))).xyz;
}
"""),

    ShaderFunction(code="""
void dir_space_convert_view_to_world(inout vec3 dir, in mat4 inv_view_mat) {
    dir = normalize(inv_view_mat * vec4(dir, 0.0)).xyz;
}
"""),

    ShaderFunction(code="""
void point_space_convert_view_to_world(inout vec3 pos, in mat4 inv_view_mat) {
    pos = (inv_view_mat * vec4(pos, 1.0)).xyz;
}
"""),

    ShaderFunction(code="""
void dir_space_convert_world_to_view(inout vec3 dir, in mat4 view_mat) {
    dir = normalize(view_mat * vec4(dir, 0.0)).xyz;
}
"""),

    ShaderFunction(code="""
void point_space_convert_world_to_view(inout vec3 pos, in mat4 view_mat) {
    pos = (view_mat * vec4(dir, 1.0)).xyz;
}
"""),

    ShaderFunction(code="""
void refraction_fresnel(vec3 view_dir, vec3 normal, float ior, out float kr) {
// reference [https://www.scratchapixel.com/lessons/
// 3d-basic-rendering/introduction-to-shading/reflection-refraction-fresnel]
    float cosi = clamp(-1.0, 1.0, dot(view_dir, normal));
    float etai = 1.0, etat = ior;
    if (cosi > 0.0) {
        float tmp = etai;
        etai = etat;
        etat = tmp;
    }
    // Compute sini using Snell's law
    float sint = etai / etat * sqrt(max(0.0, 1.0 - cosi * cosi));
    // Total internal reflection
    if (sint >= 1.0) {
        kr = 1.0;
    }
    else {
        float cost = sqrt(max(0.0, 1.0 - sint * sint));
        cosi = abs(cosi);
        float Rs = ((etat * cosi) - (etai * cost))
                    / ((etat * cosi) + (etai * cost));
        float Rp = ((etai * cosi) - (etat * cost))
                    / ((etai * cosi) + (etat * cost));
        kr = (Rs * Rs + Rp * Rp) * 0.5;
    }
}
""")
]

FUNCTION_NAME_MAPPING = {func.name: func for func in FUNCTION_LIBS}


CAMEL_TO_SNAKE_FIRST_CAP = re.compile('(.)([A-Z][a-z]+)')
CAMEL_TO_SNAKE_ALL_CAP = re.compile('([a-z0-9])([A-Z])')
NODE_BL_IDNAME_PREFIX = 'Shader'


def camel_case_to_snake_case(string):
    """Convert a camel case string to snake case string"""
    temp = CAMEL_TO_SNAKE_FIRST_CAP.sub(r'\1_\2', string)
    return CAMEL_TO_SNAKE_ALL_CAP.sub(r'\1_\2', temp).lower()


def convert_node_to_function_name(node):
    """Generate a function name give a blender shader node"""
    pruned_node_bl_id = node.bl_idname[len(NODE_BL_IDNAME_PREFIX):]
    function_name_base = camel_case_to_snake_case(pruned_node_bl_id)
    if node.bl_idname == 'ShaderNodeMath':
        operation = node.operation.lower()
        if node.use_clamp:
            return function_name_base + "_" + operation + "_clamp"
        return function_name_base + "_" + operation + "_no_clamp"

    if node.bl_idname == 'ShaderNodeVectorMath':
        operation = node.operation.lower()
        return function_name_base + "_" + operation

    if node.bl_idname == 'ShaderNodeNormalMap':
        return function_name_base + "_" + node.space.lower()

    return function_name_base


def node_has_function(node):
    """Check if a shader node has associated functions"""
    func_name = convert_node_to_function_name(node)
    return func_name in FUNCTION_NAME_MAPPING


def find_node_function(node):
    """Given a material node, return its corresponding function"""
    function_name = convert_node_to_function_name(node)
    function = FUNCTION_NAME_MAPPING.get(function_name, None)
    if function is None:
        raise ValidationError(
            "Node with type '{}' at '{}' is not supported".format(
                node.bl_idname, node.name
            )
        )
    return function


def find_function_by_name(function_name):
    """Given identifier of a material node,
    return its corresponding function"""
    return FUNCTION_NAME_MAPPING.get(function_name, None)
