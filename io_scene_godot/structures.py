"""The Godot file format has several concepts such as headings and subresources

This file contains classes to help dealing with the actual writing to the file
"""
import os
import math
import copy
import collections
import mathutils


class ValidationError(Exception):
    """An error type for explicitly delivering error messages to user."""


class ESCNFile:
    """The ESCN file consists of three major sections:
     - paths to external resources
     - internal resources
     - nodes

    Because the write order is important, you have to know all the resources
    before you can start writing nodes. This class acts as a container to store
    the file before it can be written out in full

    Things appended to this file should have the method "to_string()" which is
    used when writing the file
    """

    def __init__(self, heading):
        self.heading = heading
        self.nodes = []
        self.internal_resources = []
        self._internal_hashes = {}

        self.external_resources = []
        self._external_hashes = {}

    def get_external_resource(self, hashable):
        """Searches for existing external resources, and returns their
        resource ID. Returns None if it isn't in the file"""
        return self._external_hashes.get(hashable)

    def add_external_resource(self, item, hashable):
        """External resources are indexed by ID. This function ensures no
        two items have the same ID. It returns the index to the resource.
        An error is thrown if the hashable matches an existing resource. You
        should check get_external_resource before converting it into godot
        format

        The resource is not written to the file until the end, so you can
        modify the resource after adding it to the file"""
        if self.get_external_resource(hashable) is not None:
            raise Exception("Attempting to add object to file twice")

        self.external_resources.append(item)
        index = len(self.external_resources)
        item.heading['id'] = index
        self._external_hashes[hashable] = index
        return index

    def get_internal_resource(self, hashable):
        """Searches for existing internal resources, and returns their
        resource ID"""
        return self._internal_hashes.get(hashable)

    def add_internal_resource(self, item, hashable):
        """See comment on external resources. It's the same"""
        if self.get_internal_resource(hashable) is not None:
            raise Exception("Attempting to add object to file twice")
        resource_id = self.force_add_internal_resource(item)
        self._internal_hashes[hashable] = resource_id
        return resource_id

    def force_add_internal_resource(self, item):
        """Add an internal resource without providing an hashable,
        ATTENTION: it should not be called unless an hashable can not
        be found"""
        self.internal_resources.append(item)
        index = len(self.internal_resources)
        item.heading['id'] = index
        return index

    def add_node(self, item):
        """Adds a node to this file. Nodes aren't indexed, so none of
        the complexity of the other resource types"""
        self.nodes.append(item)

    def fix_paths(self, path):
        """Ensures all external resource paths are relative to the exported
        file"""
        for res in self.external_resources:
            res.fix_path(path)

    def to_string(self):
        """Serializes the file ready to dump out to disk"""
        sections = (
            self.heading.to_string(),
            '\n\n'.join(i.to_string() for i in self.external_resources),
            '\n\n'.join(e.to_string() for e in self.internal_resources),
            '\n\n'.join(n.to_string() for n in self.nodes)
        )
        return "\n\n".join([s for s in sections if s]) + "\n"


class FileEntry(collections.OrderedDict):
    '''Everything inside the file looks pretty much the same. A heading
    that looks like [type key=val key=val...] and contents that is newline
    separated key=val pairs. This FileEntry handles the serialization of
    on entity into this form'''

    def __init__(self, entry_type, heading_dict=(), values_dict=()):
        self.entry_type = entry_type
        self.heading = collections.OrderedDict(heading_dict)

        # This string is copied verbatim, so can be used for custom writing
        self.contents = ''

        super().__init__(values_dict)

    def generate_heading_string(self):
        """Convert the heading dict into [type key=val key=val ...]"""
        out_str = '[{}'.format(self.entry_type)
        for var in self.heading:
            val = self.heading[var]

            if isinstance(val, str):
                val = '"{}"'.format(val)

            out_str += " {}={}".format(var, val)
        out_str += ']'
        return out_str

    def generate_body_string(self):
        """Convert the contents of the super/internal dict into newline
        separated key=val pairs"""
        lines = []
        for var in self:
            val = self[var]
            val = to_string(val)
            lines.append('{} = {}'.format(var, val))
        return "\n".join(lines)

    def to_string(self):
        """Serialize this entire entry"""
        heading = self.generate_heading_string()
        body = self.generate_body_string()
        if body and self.contents:
            return "{}\n\n{}\n{}".format(heading, body, self.contents)
        if body:
            return "{}\n\n{}".format(heading, body)
        return heading


class NodeTemplate(FileEntry):
    """Most things inside the escn file are Nodes that make up the scene tree.
    This is a template node that can be used to construct nodes of any type.
    It is not intended that other classes in the exporter inherit from this,
    but rather that all the exported nodes use this template directly."""

    def __init__(self, name, node_type, parent_node):
        # set child, parent relation
        self.children = []
        self.parent = parent_node

        # filter out special character
        node_name = name.replace('.', '').replace('/', '').replace('\\', '')

        if parent_node is not None:
            # solve duplication
            counter = 1
            child_name_set = {c.get_name() for c in self.parent.children}
            node_name_base = node_name
            while node_name in child_name_set:
                node_name = node_name_base + str(counter).zfill(3)
                counter += 1

            parent_node.children.append(self)

            super().__init__(
                "node",
                collections.OrderedDict((
                    ("name", node_name),
                    ("type", node_type),
                    ("parent", parent_node.get_path())
                ))
            )
        else:
            # root node
            super().__init__(
                "node",
                collections.OrderedDict((
                    ("type", node_type),
                    ("name", node_name)
                ))
            )

    def get_name(self):
        """Get the name of the node in Godot scene"""
        return self.heading['name']

    def get_path(self):
        """Get the node path in the Godot scene"""
        # root node
        if 'parent' not in self.heading:
            return '.'

        # children of root node
        if self.heading['parent'] == '.':
            return self.heading['name']

        return self.heading['parent'] + '/' + self.heading['name']

    def get_type(self):
        """Get the node type in Godot scene"""
        return self.heading["type"]


class ExternalResource(FileEntry):
    """External Resources are references to external files. In the case of
    an escn export, this is mostly used for images, sounds and so on"""

    def __init__(self, path, resource_type):
        super().__init__(
            'ext_resource',
            collections.OrderedDict((
                # ID is overwritten by ESCN_File.add_external_resource
                ('id', None),
                ('path', path),
                ('type', resource_type)
            ))
        )

    def fix_path(self, path):
        """Makes the resource path relative to the exported file"""

        # The replace line is because godot always works in linux
        # style slashes, and python doing relpath uses the one
        # from the native OS
        self.heading['path'] = os.path.relpath(
            self.heading['path'],
            os.path.dirname(path),
        ).replace('\\', '/')


class InternalResource(FileEntry):
    """ A resource stored internally to the escn file, such as the
    description of a material """

    def __init__(self, resource_type, name):
        super().__init__(
            'sub_resource',
            collections.OrderedDict((
                # ID is overwritten by ESCN_File.add_internal_resource
                ('id', None),
                ('type', resource_type)
            ))
        )
        self['resource_name'] = '"{}"'.format(
            name.replace('.', '').replace('/', '')
        )


class Array(list):
    """In the escn file there are lots of arrays which are defined by
    a type (eg Vector3Array) and then have lots of values. This helps
    to serialize that sort of array. You can also pass in custom separators
    and suffixes.

    Note that the constructor values parameter flattens the list using the
    add_elements method
    """

    def __init__(self, prefix, seperator=', ', suffix=')', values=()):
        self.prefix = prefix
        self.seperator = seperator
        self.suffix = suffix
        super().__init__()
        self.add_elements(values)

        self.__str__ = self.to_string

    def add_elements(self, list_of_lists):
        """Add each element from a list of lists to the array (flatten the
        list of lists)"""
        for lis in list_of_lists:
            self.extend(lis)

    def to_string(self):
        """Convert the array to serialized form"""
        return "{}{}{}".format(
            self.prefix,
            self.seperator.join([to_string(v) for v in self]),
            self.suffix
        )


class Map(collections.OrderedDict):
    """An ordered dict, used to serialize to a dict to escn file. Note
    that the key should be string, but for the value will be applied
    with to_string() method"""

    def __init__(self):
        super().__init__()

        self.__str__ = self.to_string

    def to_string(self):
        """Convert the map to serialized form"""
        return ("{\n\t" +
                ',\n\t'.join(['"{}":{}'.format(k, to_string(v))
                              for k, v in self.items()]) +
                "\n}")


class NodePath:
    """Node in scene points to other node or node's attribute,
    for example, a MeshInstane points to a Skeleton. """

    def __init__(self, from_here, to_there, attribute_pointed=''):
        self.relative_path = os.path.normpath(
            os.path.relpath(to_there, from_here)
        )
        if os.sep == '\\':
            # Ensure node path use '/' on windows as well
            self.relative_path = self.relative_path.replace('\\', '/')
        self.attribute_name = attribute_pointed

    def new_copy(self, attribute=None):
        """Return a new instance of the current NodePath and
        able to change the attribute pointed"""
        new_node_path = copy.deepcopy(self)
        if attribute is not None:
            new_node_path.attribute_name = attribute
        return new_node_path

    def to_string(self):
        """Serialize a node path"""
        return 'NodePath("{}:{}")'.format(
            self.relative_path,
            self.attribute_name
        )


def fix_matrix(mtx):
    """ Shuffles a matrix to change from y-up to z-up"""
    # TODO: can this be replaced my a matrix multiplication?
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


_AXIS_CORRECT = mathutils.Matrix.Rotation(math.radians(-90), 4, 'X')


def fix_directional_transform(mtx):
    """Used to correct spotlights and cameras, which in blender are
    Z-forwards and in Godot are Y-forwards"""
    return mtx @ _AXIS_CORRECT


def fix_bone_attachment_transform(attachment_obj, blender_transform):
    """Godot and blender bone children nodes' transform relative to
    different bone joints, so there is a difference of bone_length
    along bone direction axis"""
    armature_obj = attachment_obj.parent
    bone_length = armature_obj.data.bones[attachment_obj.parent_bone].length
    mtx = mathutils.Matrix(blender_transform)
    mtx[1][3] += bone_length
    return mtx


def fix_bone_attachment_location(attachment_obj, location_vec):
    """Fix the bone length difference in location vec3 of
    BoneAttachment object"""
    armature_obj = attachment_obj.parent
    bone_length = armature_obj.data.bones[attachment_obj.parent_bone].length
    vec = mathutils.Vector(location_vec)
    vec[1] += bone_length
    return vec


def gamma_correct(color):
    """Apply sRGB color space gamma correction to the given color"""
    if isinstance(color, float):
        # separate color channel
        return color ** (1 / 2.2)

    # mathutils.Color does not support alpha yet, so just use RGB
    # see: https://developer.blender.org/T53540
    color = color[0:3]
    # note that here use a widely mentioned sRGB approximation gamma = 2.2
    # it is good enough, the exact gamma of sRGB can be find at
    # https://en.wikipedia.org/wiki/SRGB
    if len(color) > 3:
        color = color[:3]
    return mathutils.Color(tuple([x ** (1 / 2.2) for x in color]))


# ------------------ Implicit Conversions of Blender Types --------------------
def mat4_to_string(mtx):
    """Converts a matrix to a "Transform" string that can be parsed by Godot"""
    mtx = fix_matrix(mtx)
    array = Array('Transform(')
    for row in range(3):
        for col in range(3):
            array.append(mtx[row][col])

    # Export the basis
    for axis in range(3):
        array.append(mtx[axis][3])

    return array.to_string()


def color_to_string(rgba):
    """Converts an RGB colors in range 0-1 into a format Godot can read.
    Accepts iterables of 3 or 4 in length, but is designed for
    mathutils.Color"""
    alpha = 1.0 if len(rgba) < 4 else rgba[3]
    col = list(rgba[0:3]) + [alpha]
    return Array('Color(', values=[col]).to_string()


def vector_to_string(vec):
    """Encode a mathutils.vector. actually, it accepts iterable of any length,
    but 2, 3 are best...."""
    return Array('Vector{}('.format(len(vec)), values=[vec]).to_string()


def float_to_string(num):
    """Intelligently rounds float numbers"""
    if abs(num) < 1e-15:
        # This should make floating point errors round sanely. It does mean
        # that if you have objects with large scaling factors and tiny meshes,
        # then the object may "collapse" to zero.
        # There are still some e-8's that appear in the file, but I think
        # people would notice it collapsing.
        return '0.0'
    return '{:.6}'.format(num)


def to_string(val):
    """Attempts to convert any object into a string using the conversions
    table, explicit conversion, or falling back to the str() method"""
    if hasattr(val, "to_string"):
        val = val.to_string()
    else:
        converter = CONVERSIONS.get(type(val))
        if converter is not None:
            val = converter(val)
        else:
            val = str(val)

    return val


# Finds the correct conversion function for a datatype
CONVERSIONS = {
    float: float_to_string,
    bool: lambda x: 'true' if x else 'false',
    mathutils.Matrix: mat4_to_string,
    mathutils.Color: color_to_string,
    mathutils.Vector: vector_to_string
}
