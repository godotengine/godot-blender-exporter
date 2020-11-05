"""Util functions and structs shared by multiple resource converters"""

import bpy
import bmesh


def get_applicable_modifiers(obj, export_settings):
    """Returns a list of all the modifiers that'll be applied to the final
    godot mesh"""
    ignore_modifiers = []
    if not export_settings['use_mesh_modifiers']:
        return []
    if "ARMATURE" in export_settings['object_types']:
        ignore_modifiers.append(bpy.types.ArmatureModifier)
    ignore_modifiers = tuple(ignore_modifiers)
    return [m for m in obj.modifiers if not isinstance(m, ignore_modifiers)
            and m.show_viewport]


def record_modifier_config(obj):
    """Returns modifiers viewport visibility config"""
    modifier_config_cache = []
    for mod in obj.modifiers:
        modifier_config_cache.append(mod.show_viewport)
    return modifier_config_cache


def restore_modifier_config(obj, modifier_config_cache):
    """Applies modifiers viewport visibility config"""
    for i, mod in enumerate(obj.modifiers):
        mod.show_viewport = modifier_config_cache[i]


def triangulate_mesh(mesh):
    """Triangulate a mesh"""
    tri_mesh = bmesh.new()
    tri_mesh.from_mesh(mesh)
    bmesh.ops.triangulate(
        tri_mesh, faces=tri_mesh.faces, quad_method="ALTERNATE")
    tri_mesh.to_mesh(mesh)
    tri_mesh.free()
    if bpy.app.version[1] > 80:
        mesh.update()
    else:
        mesh.update(calc_loop_triangles=True)


class MeshResourceKey:
    """Produces a key based on an mesh object's data, every different
    Mesh Resource would have a unique key"""

    def __init__(self, rsc_type, obj, export_settings):
        mesh_data = obj.data

        # Resource type included because same blender mesh may be used as
        # MeshResource or CollisionShape, but they are different resources
        gd_rsc_type = rsc_type

        # Here collect info of all the modifiers applied on the mesh.
        # Modifiers along with the original mesh data would determine
        # the evaluated mesh.
        mod_info_list = list()
        for modifier in get_applicable_modifiers(obj, export_settings):
            # Modifier name indicates its type, it's an identifier
            mod_info_list.append(modifier.name)

            # First property is always 'rna_type', skip it
            for prop_key in modifier.bl_rna.properties.keys()[1:]:
                prop = modifier.bl_rna.properties[prop_key]
                prop_val = getattr(modifier, prop_key)

                if prop.type == 'COLLECTION':
                    # For `CollectionProperty`, it would make more sense to
                    # traversal it, however, we cut down here just for
                    # simplicity allowing some of mesh resources not being
                    # shared.
                    mod_info_list.append(id(prop_val))
                elif prop.type == 'POINTER':
                    # For `PointerProperty`, it points to a bpy.types.ID, its
                    # hash value is the python object id, which is good as an
                    # identifier.
                    mod_info_list.append(prop_val)
                else:
                    # Here Property may be `BoolProperty`, `EnumProperty`,
                    # `FloatProperty`, `IntProperty`, `StringProperty`
                    # they are primitive types and all good to be hashed.
                    assert prop.type in \
                        ('BOOLEAN', 'ENUM', 'INT', 'STRING', 'FLOAT')
                    if isinstance(prop_val, (int, float, str, bool)) or \
                            prop_val is None:
                        mod_info_list.append(prop_val)
                    else:
                        # iterable properties
                        mod_info_list.append(tuple(prop_val))

        # Precalculate the hash now for better efficiency later
        self._data = tuple([mesh_data, gd_rsc_type] + mod_info_list)
        self._hash = hash(self._data)

    def __hash__(self):
        return self._hash

    def __eq__(self, other):
        # pylint: disable=protected-access
        return (self.__class__ == other.__class__ and
                self._data == other._data)


class MeshConverter:
    """MeshConverter evaulates and converts objects to meshes, triangulates
    and calculates tangents"""

    def __init__(self, obj, export_settings):
        self.object = obj
        self.eval_object = None
        self.use_mesh_modifiers = export_settings["use_mesh_modifiers"]
        self.use_export_shape_key = export_settings['use_export_shape_key']
        self.has_tangents = False

    def to_mesh(self, triangulate=True, preserve_vertex_groups=True,
                calculate_tangents=True, shape_key_index=0):
        """Evaluates object & converts to final mesh, ready for export.
        The mesh is only temporary, call to_mesh_clear() afterwards."""
        # set shape key to basis key which would have index 0
        orig_shape_key_index = self.object.active_shape_key_index
        self.object.show_only_shape_key = True
        self.object.active_shape_key_index = shape_key_index

        self.eval_object = self.object

        modifier_config_cache = None
        if not self.use_mesh_modifiers:
            modifier_config_cache = record_modifier_config(self.object)
            for mod in self.object.modifiers:
                mod.show_viewport = False

        depsgraph = bpy.context.view_layer.depsgraph
        depsgraph.update()
        self.eval_object = self.object.evaluated_get(depsgraph)

        # These parameters are required for preserving vertex groups.
        mesh = self.eval_object.to_mesh(
            preserve_all_data_layers=preserve_vertex_groups,
            depsgraph=depsgraph
        )

        if not self.use_mesh_modifiers:
            restore_modifier_config(self.object, modifier_config_cache)

        self.has_tangents = False

        # mesh result can be none if the source geometry has no faces, so we
        # need to consider this if we want a robust exporter.
        if mesh is not None:
            if triangulate:
                triangulate_mesh(mesh)

            self.has_tangents = bool(mesh.uv_layers) and bool(mesh.polygons)
            if calculate_tangents:
                if self.has_tangents:
                    try:
                        mesh.calc_tangents()
                    except RuntimeError:
                        # Mesh had n-gons; need to triangulate
                        triangulate_mesh(mesh)
                        mesh.calc_tangents()
                else:
                    mesh.calc_normals_split()

        self.object.show_only_shape_key = False
        self.object.active_shape_key_index = orig_shape_key_index

        return mesh

    def to_mesh_clear(self):
        """Clears the temporary generated mesh from memory"""
        if self.object is None:
            return
        self.eval_object.to_mesh_clear()
        self.object = self.eval_object = None
