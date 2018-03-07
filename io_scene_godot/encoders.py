"""This file contains operations that take a blender or python concept and
translate it into a string that godot will understand when it is parsed

It also contains a dictionary called CONVERSIONS which encapsulates all the
encoders by their types
"""
import mathutils


def mat4_to_string(mtx):
    """Converts a matrix to a "Transform" string that can be parsed by Godot"""
    def fix_matrix(mtx):
        """ Shuffles a matrix to change from y-up to z-up"""
        # Todo: can this be replaced my a matrix multiplcation?
        trans = mathutils.Matrix(mtx)
        up_axis = 2

        for i in range(3):
            trans[1][i], trans[up_axis][i] = trans[up_axis][i], trans[1][i]
        for i in range(3):
            trans[i][1], trans[i][up_axis] = trans[i][up_axis], trans[i][1]

        trans[1][3], trans[up_axis][3] = trans[up_axis][3], trans[1][3]

        trans[up_axis][0] = -trans[up_axis][0]
        trans[up_axis][1] = -trans[up_axis][1]
        trans[0][up_axis] = -trans[0][up_axis]
        trans[1][up_axis] = -trans[1][up_axis]
        trans[up_axis][3] = -trans[up_axis][3]

        return trans

    mtx = fix_matrix(mtx)
    s = ""
    for x in range(3):
        for y in range(3):
            if x != 0 or y != 0:
                s += ", "
            s += "{} ".format(mtx[x][y])

    for x in range(3):
        s += ",{} ".format(mtx[x][3])

    s = "Transform( {} )".format(s)
    return s


def color_to_string(rgba):
    """Converts an RGB colors in range 0-1 into a fomat Godot can read. Accepts
    iterables of 3 or 4 in length, but is designed for mathutils.Color"""
    a = 1.0 if len(rgba) < 4 else rgba[3]
    return "Color( {}, {}, {}, {} )".format(
        rgba[0],
        rgba[1],
        rgba[2],
        a,
    )


# Finds the correct conversion function for a datatype
CONVERSIONS = {
    bool: lambda x: 'true' if x else 'false',
    mathutils.Matrix: mat4_to_string,
    mathutils.Color: color_to_string
}
