# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# ##### END GPL LICENSE BLOCK #####

# Script copyright (C) Juan Linietsky
# Contact Info: juan@godotengine.org

"""
This script is an exporter to Godot Engine

http://www.godotengine.org
"""

import os
import collections
import functools
import logging
import bpy

from . import structures
from . import converters
from .structures import (_AXIS_CORRECT, NodePath)

logging.basicConfig(level=logging.INFO, format="[%(levelname)s]: %(message)s")


@functools.lru_cache(maxsize=1)  # Cache it so we don't search lots of times
def find_godot_project_dir(export_path):
    """Finds the project.godot file assuming that the export path
    is inside a project (looks for a project.godot file)"""
    project_dir = export_path

    # Search up until we get to the top, which is "/" in *nix.
    # Standard Windows ends up as, e.g., "C:\", and independent of what else is
    # in the world, we can at least watch for repeats, because that's bad.
    last = None
    while not os.path.isfile(os.path.join(project_dir, "project.godot")):
        project_dir = os.path.split(project_dir)[0]
        if project_dir in ("/", last):
            raise structures.ValidationError(
                "Unable to find Godot project file"
            )
        last = project_dir
    logging.info("Found Godot project directory at %s", project_dir)
    return project_dir


class ExporterLogHandler(logging.Handler):
    """Custom handler for exporter, would report logging message
    to GUI"""

    def __init__(self, operator):
        super().__init__()
        self.setLevel(logging.WARNING)
        self.setFormatter(logging.Formatter("%(message)s"))

        self.blender_op = operator

    def emit(self, record):
        if record.levelno == logging.WARNING:
            self.blender_op.report({'WARNING'}, record.message)
        else:
            self.blender_op.report({'ERROR'}, record.message)


class GodotExporter:
    """Handles picking what nodes to export and kicks off the export process"""

    def export_object(self, obj, parent_gd_node):
        """Recursively export a object. It calls the export_object function on
        all of the objects children. If you have heirarchies more than 1000
        objects deep, this will fail with a recursion error"""
        if obj not in self.valid_objects:
            return

        logging.info("Exporting Blender object: %s", obj.name)

        prev_node = bpy.context.view_layer.objects.active
        bpy.context.view_layer.objects.active = obj

        # Figure out what function will perform the export of this object
        if obj.type not in converters.BLENDER_TYPE_TO_EXPORTER:
            logging.warning(
                "Unknown object type. Treating as empty: %s", obj.name
            )
        elif obj in self.exporting_objects:
            exporter = converters.BLENDER_TYPE_TO_EXPORTER[obj.type]
        else:
            logging.warning(
                "Object is parent of exported objects. "
                "Treating as empty: %s", obj.name
            )
            exporter = converters.BLENDER_TYPE_TO_EXPORTER["EMPTY"]

        is_bone_attachment = False
        if ("ARMATURE" in self.config['object_types'] and
                obj.parent and obj.parent_bone != ''):
            is_bone_attachment = True
            parent_gd_node = converters.BONE_ATTACHMENT_EXPORTER(
                self.escn_file,
                self.config,
                obj,
                parent_gd_node
            )

        # Perform the export, note that `exported_node.parent` not
        # always the same as `parent_gd_node`, as sometimes, one
        # blender node exported as two parented node
        exported_node = exporter(self.escn_file, self.config, obj,
                                 parent_gd_node)

        self.bl_object_gd_node_map[obj] = exported_node

        if is_bone_attachment:
            for child in parent_gd_node.children:
                child['transform'] = structures.fix_bone_attachment_transform(
                    obj, child['transform']
                )

        # CollisionShape node has different direction in blender
        # and godot, so it has a -90 rotation around X axis,
        # here rotate its children back
        if (exported_node.parent is not None and
                exported_node.parent.get_type() == 'CollisionShape'):
            exported_node['transform'] = (
                _AXIS_CORRECT.inverted() @
                exported_node['transform'])

        # if the blender node is exported and it has animation data
        if exported_node != parent_gd_node:
            converters.ANIMATION_DATA_EXPORTER(
                self.escn_file,
                self.config,
                exported_node,
                obj,
                "transform"
            )

        for child in obj.children:
            self.export_object(child, exported_node)

        bpy.context.view_layer.objects.active = prev_node

    def should_export_object(self, obj):
        """Checks if a node should be exported:"""
        if obj.type not in self.config["object_types"]:
            return False

        if self.config["use_visible_objects"]:
            view_layer = bpy.context.view_layer
            if obj.name not in view_layer.objects:
                return False
            if not obj.visible_get():
                return False

        if self.config["use_export_selected"] and not obj.select_get():
            return False

        return True

    def export_objects(self, obj=None, collection=None):
        """Decide what objects to export, and export them!"""

        self.disable_edit_mode()
        if obj:
            logging.info("Exporting object: %s of scene %s",
                         obj.name, self.scene.name)
            self.select_objects_object(obj)
            self.reset_transform(obj)
            scene_name = obj.name
        elif collection:
            logging.info("Exporting collection: %s of scene %s",
                         collection.name, self.scene.name)
            self.select_objects_collection(collection)
            scene_name = collection.name
        else:
            logging.info("Exporting scene: %s", self.scene.name)
            self.select_objects_scene()
            scene_name = self.scene.name
        # Decide what objects to export

        logging.info("Exporting %d objects", len(self.valid_objects))

        if obj is None or not self.config["root_objects"]:
            # Scene root
            root_gd_node = structures.NodeTemplate(
                scene_name,
                "Spatial",
                None
            )
            self.escn_file.add_node(root_gd_node)
        else:
            root_gd_node = None

        for _obj in self.scene.objects:
            if _obj in self.valid_objects and _obj.parent is None:
                # recursive exporting on root object
                self.export_object(_obj, root_gd_node)

        if "ARMATURE" in self.config['object_types']:
            for bl_obj in self.bl_object_gd_node_map:
                for mod in bl_obj.modifiers:
                    if mod.type == "ARMATURE":
                        mesh_node = self.bl_object_gd_node_map[bl_obj]
                        skeleton_node = self.bl_object_gd_node_map[mod.object]
                        mesh_node['skeleton'] = NodePath(
                            mesh_node.get_path(), skeleton_node.get_path())
        if obj is not None:
            self.reapply_transform(obj)

    def reset_transform(self, obj):
        """Resets transformation to pos=0, rot=0, scale=1"""
        if "LOC" in self.config["reset_transform"]:
            self.transform[0] = obj.location.copy()
            obj.location = (0, 0, 0)
        if "ROT" in self.config["reset_transform"]:
            self.transform[1] = obj.rotation_euler.copy()
            obj.rotation_euler = (0, 0, 0)
        if "SCA" in self.config["reset_transform"]:
            self.transform[2] = obj.scale.copy()
            obj.scale = (1, 1, 1)

    def reapply_transform(self, obj):
        """Restores reset transformation"""
        if "LOC" in self.config["reset_transform"]:
            obj.location = self.transform[0]
        if "ROT" in self.config["reset_transform"]:
            obj.rotation_euler = self.transform[1]
        if "SCA" in self.config["reset_transform"]:
            obj.scale = self.transform[2]

    def disable_edit_mode(self):
        '''Disables edit mode, and stores the current state
        for restore_edit_mode'''
        if bpy.context.object and bpy.context.object.mode == "EDIT":
            self.in_edit_mode = True
            bpy.ops.object.editmode_toggle()

    def restore_edit_mode(self):
        '''Reenables edit mode, when disabled with
        disable_edit_mode'''
        if self.in_edit_mode:
            bpy.ops.object.editmode_toggle()
            self.in_edit_mode = False

    def select_objects_scene(self):
        '''Selects the objects that should be exported for scene export'''
        for obj in self.scene.objects:
            if obj in self.exporting_objects:
                continue
            if self.should_export_object(obj):
                self.exporting_objects.add(obj)
                # Ensure parents of current valid object is
                # going to the exporting recursion
                tmp = obj
                while tmp is not None:
                    if tmp not in self.valid_objects:
                        self.valid_objects.add(tmp)
                    else:
                        break
                    tmp = tmp.parent

    def select_objects_collection(self, collection):
        '''Selects the objects that should be exported for collection export'''
        for obj in collection.objects:
            if obj in self.exporting_objects:
                continue
            if self.should_export_object(obj):
                self.exporting_objects.add(obj)
                # Ensure parents of current valid object is
                # going to the exporting recursion
                tmp = obj
                while tmp is not None:
                    if tmp not in self.valid_objects:
                        self.valid_objects.add(tmp)
                    else:
                        break
                    tmp = tmp.parent

    def select_objects_object(self, obj):
        '''Selects the objects that should be exported for object export'''
        if self.should_export_object(obj) and obj.parent is None:
            self.exporting_objects.add(obj)
            self.valid_objects.add(obj)

        for child in self.scene.objects:
            if child in self.exporting_objects:
                continue

            if self.should_export_object(child):
                parent = child

                # test if child is related to obj
                while parent.parent is not None:
                    parent = parent.parent
                if parent is obj:
                    self.exporting_objects.add(child)
                    # Ensure parents of current valid child
                    # are going to the exporting recursion
                    tmp = child
                    while tmp is not None:
                        if tmp not in self.valid_objects:
                            self.valid_objects.add(tmp)
                        else:
                            break
                        tmp = tmp.parent

    def load_supported_features(self):
        """According to `project.godot`, determine all new feature supported
        by that godot version"""
        project_dir = ""
        try:
            project_dir = self.config["project_path_func"]()
        except structures.ValidationError:
            project_dir = False
            logging.warning(
                "Not export to Godot project dir, disable all beta features.")

        # minimal supported version
        conf_version = 3
        if project_dir:
            project_file_path = os.path.join(project_dir, "project.godot")
            with open(project_file_path, "r") as proj_f:
                for line in proj_f:
                    if not line.startswith("config_version"):
                        continue

                    _, version_str = tuple(line.split("="))
                    conf_version = int(version_str)
                    break

        if conf_version < 2:
            logging.error(
                "Godot version smaller than 3.0, not supported by this addon")

        if conf_version >= 4:
            # godot >=3.1
            self.config["feature_bezier_track"] = True

    def get_path(self, collection, obj=None):
        '''Returns the path for export
        of collection and objects'''
        path, file_name = os.path.split(self.path)
        if file_name.endswith(".escn"):
            file_name = file_name[:-5]
        path += os.path.sep
        if obj is None:
            if self.config["prefix"]:
                path += file_name + "_"
            path += collection.name + ".escn"
        else:
            if self.config["collection_folders"]:
                if self.config["prefix"]:
                    path += file_name + "_"
                path += collection.name + os.path.sep
                if self.config["prefix_in_folders"]:
                    path += file_name + "_"
            else:
                if self.config["prefix"]:
                    path += file_name + "_"
            path += obj.name + ".escn"

        return path

    def create_folder(self, collection):
        """Creates folder for collection"""
        folder = self.get_path(collection)[:-5]
        print("Creating folder" + folder)
        try:
            os.makedirs(folder, exist_ok=True)
            return True
        except FileExistsError:
            # Can easily happen when exporting
            # Collections first by accident
            self.operator.report(
                {'ERROR'}, "Unable to create Folder, " +
                folder +
                "there was already a file.")
            return False

    def export(self):
        """Begin the export"""
        self.escn_file = structures.ESCNFile(structures.FileEntry(
            "gd_scene",
            collections.OrderedDict((
                ("load_steps", 1),
                ("format", 2)
            ))
        ))

        scene_mode = self.config["scene_mode"]
        if scene_mode == "ONE":
            self.export_objects()
            self.save(self.path)

        elif scene_mode == "COLLECTIONS":
            for collection in bpy.data.collections:
                self.export_objects(collection=collection)

                # skip empty collections
                if (len(self.escn_file.nodes) > 1 or
                        self.config["empty_collections"]):
                    self.save(self.get_path(collection))
                self.reset()
        else:
            # create folders for empty collections
            if (self.config["collection_folders"] and
                    self.config["empty_collections"]):
                for collection in bpy.data.collections:
                    if not self.create_folder(collection):
                        return False
            for obj in bpy.data.objects:
                if obj.parent is None:
                    self.export_objects(obj=obj)

                    # skip empty objects
                    if (not self.config["root_objects"]
                            and len(self.escn_file.nodes) <= 1
                            or len(self.escn_file.nodes) == 0):
                        self.reset()
                        continue

                    # create folder
                    if self.config["collection_folders"]:
                        self.create_folder(obj.users_collection[0])

                    self.save(self.get_path(obj.users_collection[0], obj))
                    self.reset()

        return True

    def save(self, path):
        '''Saves the scenefile to path'''
        self.escn_file.fix_paths(path)
        with open(path, 'w') as out_file:
            out_file.write(self.escn_file.to_string())
        return True

    def reset(self):
        """Reset Export Object for Object and Collection Export"""
        self.valid_objects.clear()
        self.exporting_objects.clear()

        self.escn_file = structures.ESCNFile(structures.FileEntry(
            "gd_scene",
            collections.OrderedDict((
                ("load_steps", 1),
                ("format", 2)
            ))
        ))
        self.bl_object_gd_node_map = {}

    def __init__(self, path, kwargs, operator):
        self.path = path
        self.operator = operator
        self.scene = bpy.context.scene
        self.config = kwargs
        self.config["path"] = path
        self.config["project_path_func"] = functools.partial(
            find_godot_project_dir, path
        )
        # valid object would contain object should be exported
        # and their parents to retain the hierarchy
        self.valid_objects = set()
        # exporting objects would only contain objects need
        # to be exported
        self.exporting_objects = set()

        # optional features
        self.config["feature_bezier_track"] = False
        if self.config["use_beta_features"]:
            self.load_supported_features()

        self.escn_file = None
        self.bl_object_gd_node_map = {}

        self.in_edit_mode = False
        self.transform = [None] * 3

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


def save(operator, context, filepath="", **kwargs):
    """Begin the export"""
    exporter_log_handler = ExporterLogHandler(operator)
    logging.getLogger().addHandler(exporter_log_handler)

    object_types = kwargs["object_types"]
    # GEOMETRY isn't an object type so replace it with all valid geometry based
    # object types
    if "GEOMETRY" in object_types:
        object_types.remove("GEOMETRY")
        object_types |= {"MESH", "CURVE", "SURFACE", "META", "FONT"}

    successful = False
    with GodotExporter(filepath, kwargs, operator) as exp:
        successful = exp.export()

    logging.getLogger().removeHandler(exporter_log_handler)
    if successful:
        return {"FINISHED"}
    return {"CANCELLED"}
