"""The Godot file format has several concepts such as headings and subresources

This file contains classes to help dealing with the actual writing to the file
"""
import os
import collections
import mathutils


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
        self.internal_resources.append(item)
        index = len(self.internal_resources)
        item.heading['id'] = index
        self._internal_hashes[hashable] = index
        return index

    def add_node(self, item):
        """Adds a node to this file. Nodes aren't indexed, so none of
        the complexity of the other resource types"""
        self.nodes.append(item)

    def fix_paths(self, export_settings):
        """Ensures all external resource paths are relative to the exported
        file"""
        for res in self.external_resources:
            res.fix_path(export_settings)

    def to_string(self):
        """Serializes the file ready to dump out to disk"""

        return "{}{}\n{}\n{}\n".format(
            self.heading.to_string(),
            '\n\n'.join(i.to_string() for i in self.external_resources),
            '\n\n'.join(e.to_string() for e in self.internal_resources),
            '\n\n'.join(n.to_string() for n in self.nodes)
        )


class FileEntry(collections.OrderedDict):
    '''Everything inside the file looks pretty much the same. A heading
    that looks like [type key=val key=val...] and contents that is newline
    separated key=val pairs. This FileEntry handles the serialization of
    on entity into this form'''
    def __init__(self, entry_type, heading_dict=(), values_dict=()):
        self.entry_type = entry_type
        self.heading = collections.OrderedDict(heading_dict)

        # This string is copied verbaitum, so can be used for custom writing
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
        out_str = ''
        for var in self:
            val = self[var]
            val = to_string(val)

            out_str += '\n{} = {}'.format(var, val)
        return out_str

    def to_string(self):
        """Serialize this entire entry"""
        return "{}\n{}{}".format(
            self.generate_heading_string(),
            self.generate_body_string(),
            self.contents
        )


class NodeTemplate(FileEntry):
    """Most things inside the escn file are Nodes that make up the scene tree.
    This is a template node that can be used to contruct nodes of any type.
    It is not intended that other classes in the exporter inherit from this,
    but rather that all the exported nodes use this template directly."""
    def __init__(self, name, node_type, parent_node):
        # set child, parent relation
        self.children = []
        self.parent = parent_node

        # filter out special character
        node_name = name.replace('.', '').replace('/', '')

        if parent_node is not None:
            # solve duplication
            counter = 1
            child_name_set = set([c.get_name() for c in self.parent.children])
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
    """External Resouces are references to external files. In the case of
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

    def fix_path(self, export_settings):
        """Makes the resource path relative to the exported file"""
        self.heading['path'] = os.path.relpath(
            self.heading['path'],
            os.path.dirname(export_settings["path"]),
        )


class InternalResource(FileEntry):
    """ A resource stored internally to the escn file, such as the
    description of a material """
    def __init__(self, resource_type):
        super().__init__(
            'sub_resource',
            collections.OrderedDict((
                # ID is overwritten by ESCN_File.add_internal_resource
                ('id', None),
                ('type', resource_type)
            ))
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


class NodePath:
    """Nodes in scene refers to other nodes or nodes' attribute,
    for example MeshInstane refers Skeleton. """
    def __init__(self, referee_path, referrer_path, referrer_attr=''):
        self.ref_path = os.path.relpath(referee_path, referrer_path)
        self.attr_name = referrer_attr

    def to_string(self):
        """Serialize a node path"""
        return 'NodePath("{}:{}")'.format(
            self.ref_path,
            self.attr_name
        )


# ------------------ Implicit Conversions of Blender Types --------------------
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
    array = Array('Transform(')
    for row in range(3):
        for col in range(3):
            array.append(mtx[row][col])

    # Export the basis
    for axis in range(3):
        array.append(mtx[axis][3])

    return array.to_string()


def color_to_string(rgba):
    """Converts an RGB colors in range 0-1 into a fomat Godot can read. Accepts
    iterables of 3 or 4 in length, but is designed for mathutils.Color"""
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
