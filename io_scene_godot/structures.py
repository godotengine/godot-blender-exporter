"""The Godot file format has several concepts such as headings and subresources

This file contains classes to help dealing with the actual writing to the file
"""

from .encoders import CONVERSIONS


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
        item._heading.id = index
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
        item._heading.id = index
        self._internal_hashes[hashable] = index
        return index

    def add_node(self, item):
        """Adds a node to this file. Nodes aren't indexed, so none of
        the complexity of the other resource types"""
        self.nodes.append(item)

    def to_string(self):
        """Serializes the file ready to dump out to disk"""
        return "{}\n\n{}\n\n{}\n\n{}\n".format(
            self.heading.to_string(),
            '\n'.join(i.to_string() for i in self.external_resources),
            '\n'.join(e.to_string() for e in self.internal_resources),
            '\n'.join(n.to_string() for n in self.nodes)
        )


class SectionHeading:
    """Many things in the escn file are separated by headings. These consist
    of square brackets with key=value pairs inside them. The first element
    is not a key-value pair, but describes what type of heading it is.

    This class generates a section heading from it's attributes, so you can go:
    sect = SectionHeading('thingo')
    sect.foo = "bar"
    sect.bar = 1234

    and then sect.to_string() will return:
    [thingo foo=bar bar=1234]
    """
    def __init__(self, section_type, **kwargs):
        self._type = section_type
        for key in kwargs:
            self.__dict__[key] = kwargs[key]

    def generate_prop_list(self):
        """Generate all the key=value pairs into a string from all the
        attributes in this class"""
        out_str = ''
        attribs = vars(self)
        for var in attribs:
            if var.startswith('_'):
                continue  # Ignore hidden variables
            val = attribs[var]
            converter = CONVERSIONS.get(type(val))
            if converter is not None:
                val = converter(val)

            # Extra wrapper for str's
            if isinstance(val, str):
                val = '"{}"'.format(val)

            out_str += ' {}={}'.format(var, val)

        return out_str

    def to_string(self):
        """Serializes this heading to a string"""
        return '\n\n[{} {}]\n'.format(self._type, self.generate_prop_list())


class NodeTemplate:
    """Most things inside the escn file are Nodes that make up the scene tree.
    This is a template node that can be used to contruct nodes of any type.
    It is not intended that other classes in the exporter inherit from this,
    but rather that all the exported nodes use this template directly.

    Similar to the Sectionheading, this class uses it's attributes to
    determine the properties of the node."""
    def __init__(self, name, node_type, parent_path):
        self._heading = SectionHeading(
            "node",
            name=name,
            type=node_type,
            parent=parent_path,
        )

    def generate_prop_list(self):
        """Generate key/value pairs from the attributes of the node"""
        out_str = ''
        attribs = vars(self)
        for var in attribs:
            if var.startswith('_'):
                continue  # Ignore hidden variables
            val = attribs[var]
            converter = CONVERSIONS.get(type(val))
            if converter is not None:
                val = converter(val)
            out_str += '\n{} = {}'.format(var, val)

        return out_str

    def to_string(self):
        """Serialize the node for writing to the file"""
        return '{}{}\n'.format(
            self._heading.to_string(),
            self.generate_prop_list()
        )


class ExternalResource():
    def __init__(self, path, resource_type):
        self._heading = SectionHeading(
            'ext_resource',
            id=None,  # This is overwritten by ESCN_File.add_external_resource
            path=path,
            type=resource_type
        )

    def to_string():
        return self.heading.to_string()


class InternalResource():
    def __init__(self, resource_type):
        self._heading = SectionHeading(
            'sub_resource',
            id=None,  # This is overwritten by ESCN_File.add_external_resource
            type=resource_type
        )

        # This string is dumped verbatim, so can be used it the key=value isn't ideal
        self.contents = ''

    def generate_prop_list(self):
        """Generate key/value pairs from the attributes of the node"""
        out_str = ''
        attribs = vars(self)
        for var in attribs:
            if var.startswith('_') or var == 'contents':
                continue  # Ignore hidden variables
            val = attribs[var]
            converter = CONVERSIONS.get(type(val))
            if converter is not None:
                val = converter(val)
            out_str += '\n{} = {}'.format(var, val)

        return out_str

    def to_string(self):
        """Serialize the node for writing to the file"""
        return '{}{}\n{}'.format(
            self._heading.to_string(),
            self.generate_prop_list(),
            self.contents,
        )


class Array(list):
    """In the escn file there are lots of arrays which are defined by
    a type (eg Vector3Array) and then have lots of values. This helps
    to serialize that sort of array. You can also pass in custom separators
    and suffixes.

    Note that the constructor values parameter flattens the list using the
    add_elements method
    """
    def __init__(self, prefix, seperator=', ', suffix='),', values=()):
        self.prefix = prefix
        self.seperator = seperator
        self.suffix = suffix
        super().__init__()
        self.add_elements(values)

    def add_elements(self, list_of_lists):
        """Add each element from a list of lists to the array (flatten the
        list of lists)"""
        for lis in list_of_lists:
            self.extend(lis)

    def to_string(self):
        """Convert the array to serialized form"""
        return "{}{}{}".format(
            self.prefix,
            self.seperator.join([str(v) for v in self]),
            self.suffix
        )
