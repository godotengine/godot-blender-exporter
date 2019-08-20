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
            return None
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

        gds = None
        gdprops = ('gdinclude', 'gdvar', 'gdconst', 'gdfunc', 'gdclass', 'gdenum', 'gdpreload')
        if 'gdscript' in obj.keys():
            comp = ['']
            gdextends = 'Spatial'
            for keyname in obj.keys():
                if keyname == 'gdextends':
                    gdextends = obj[keyname]
                elif keyname.startswith(gdprops):
                    value = obj[keyname]
                    if keyname.startswith(('gdinclude', 'gdfunc', 'gdclass', 'gdenum')):
                        if value in bpy.data.texts:
                            value = bpy.data.texts[value].as_string()
                        comp.append(value)
                    else:
                        keyname = keyname[2:]
                        gdtype = ''
                        if ':' in keyname:
                            vname  = keyname.split(':')[0].strip().split()[-1]
                            gdtype = keyname.split(':')[-1].split('.')[0].strip()
                        else:
                            vname = keyname.strip().split()[-1]
                        if '.' in vname:
                            vname = vname.replace('.', '_')

                        if keyname.startswith('preload'):
                            if gdtype:
                                comp.append('var %s:%s = preload("%s")' % (vname, gdtype, value))
                            else:
                                comp.append('var %s := preload("%s")' % (vname, value))
                        elif keyname.startswith( 'var' ):
                            if gdtype:
                                comp.append('var %s:%s = %s' % (vname, gdtype, value))
                            else:
                                comp.append('var %s := %s' % (vname, value))
                        elif keyname.startswith( 'const' ):
                            if gdtype:
                                comp.append('const %s:%s = %s' % (vname, gdtype, value))
                            else:
                                comp.append('const %s := %s' % (vname, value))

            if obj['gdscript'] in bpy.data.texts:
                code = bpy.data.texts[obj['gdscript']].as_string()
            else:
                code = obj['gdscript']

            if not 'func ' in code:
                fixed = [
                    'func _ready():',
                    '\n'.join(['   ' + ln for ln in code.splitlines()])
                ]
                code = '\n'.join(fixed)

            if not code.startswith('extends'):
                comp[0] = 'extends ' + gdextends

            comp.append(code)
            code = '\n'.join(comp)
            code = code.replace('"', '\\"').strip()

            if code not in self.gdscripts:
                self.gdscripts.append(code)
                gdfunc = []
                gds = self.escn_file.add_internal_resource(
                    gdfunc, # item
                    code  # hashable
                )
                gdfunc.extend([
                    '[sub_resource type="GDScript" id=%s]' % gds,
                    'script/source = "' + code,
                    '"',
                ])

            gds = self.escn_file.get_internal_resource(code)
            exported_node['script'] = 'SubResource( %s )' % gds

        ## godot visual scripting support ##
        if 'gdvs' in obj.keys():
            if obj['gdvs'] not in self.gdscripts:
                self.gdscripts.append(obj['gdvs'])
                sid = self.escn_file.add_internal_resource(
                    None,
                    obj['gdvs']
                )
                if gds:
                    self.vs_scripts[ sid ] = {'gdscript':obj['gdscript'], 'gds_id':gds}
                else:
                    self.vs_scripts[ sid ] = {}

            sid = self.escn_file.get_internal_resource(obj['gdvs'])
            exported_node['script'] = 'SubResource( %s )' % sid

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

    def export_scene(self):
        # pylint: disable-msg=too-many-branches
        """Decide what objects to export, and export them!"""
        logging.info("Exporting scene: %s", self.scene.name)

        in_edit_mode = False
        if bpy.context.object and bpy.context.object.mode == "EDIT":
            in_edit_mode = True
            bpy.ops.object.editmode_toggle()

        # Decide what objects to export
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
        logging.info("Exporting %d objects", len(self.valid_objects))

        # Scene root
        root_gd_node = structures.NodeTemplate(
            self.scene.name,
            "Spatial",
            None
        )
        self.escn_file.add_node(root_gd_node)
        for obj in self.scene.objects:
            if obj in self.valid_objects and obj.parent is None:
                # recursive exporting on root object
                self.export_object(obj, root_gd_node)

        if "ARMATURE" in self.config['object_types']:
            for bl_obj in self.bl_object_gd_node_map:
                for mod in bl_obj.modifiers:
                    if mod.type == "ARMATURE":
                        mesh_node = self.bl_object_gd_node_map[bl_obj]
                        skeleton_node = self.bl_object_gd_node_map[mod.object]
                        mesh_node['skeleton'] = NodePath(
                            mesh_node.get_path(), skeleton_node.get_path())

        if in_edit_mode:
            bpy.ops.object.editmode_toggle()

    def load_supported_features(self):
        """According to `project.godot`, determine all new feature supported
        by that godot version"""
        project_dir = ""
        if self.config['project_path_func']:
            project_dir = self.config["project_path_func"]()

        # minimal supported version
        conf_versiton = 3
        if project_dir:
            project_file_path = os.path.join(project_dir, "project.godot")
            with open(project_file_path, "r") as proj_f:
                for line in proj_f:
                    if not line.startswith("config_version"):
                        continue

                    _, version_str = tuple(line.split("="))
                    conf_versiton = int(version_str)
                    break

        if conf_versiton < 2:
            logging.error(
                "Godot version smaller than 3.0, not supported by this addon")

        if conf_versiton >= 4:
            # godot >=3.1
            self.config["feature_bezier_track"] = True

    def export(self):
        """Begin the export"""
        converters.mesh.reset_material_cache()
        self.escn_file = structures.ESCNFile(structures.FileEntry(
            "gd_scene",
            collections.OrderedDict((
                ("load_steps", 1),
                ("format", 2)
            ))
        ))

        self.export_scene()
        self.escn_file.fix_paths(self.config)

        header = []
        if len(self.gdscripts):
            if self.config.get('external_gd',None):
                pth = os.path.split(self.path)[0]
                for gdname in self.gdscripts:
                    gpth = os.path.join(pth,gdname)
                    if not gpth.endswith('.gd'):
                        gpth += '.gd'
                    with open(self.path, 'w') as gdfile:
                        gd = bpy.data.texts[gdname].as_string()
                        gdfile.write(gd.encode('utf-8'))
            else:
                for gdname in self.gdscripts:
                    gdi = self.escn_file.get_internal_resource(gdname)
                    assert gdi
                    if gdi not in self.vs_scripts:
                        continue
                    if gdname in bpy.data.texts:
                        code = bpy.data.texts[gdname].as_string()
                    else:
                        code = gdname
                    ## VisualScript
                    ## clean up json style code
                    if code.startswith('{') and code.endswith('}'):
                        vscfg = self.vs_scripts[gdi]
                        if '\n' not in code:
                            code = '\n'.join([ln+',' for ln in code[:-1].split(', ')])
                        subres = [
                            '[sub_resource type="VisualScript" id=%s]' % gdi,
                            'data = {',
                            code[1:-1],
                            '}',
                        ]
                        header.extend(subres)
                    else:
                        if not code.startswith('data'):
                            print('invalid godot visual script')
                            raise SyntaxError(code)
                        subres = [
                            '[sub_resource type="VisualScript" id=%s]' % gdi,
                            code,
                        ]
                        header.extend(subres)

        if header:
            self.escn_file.add_subheader(header)

        with open(self.path, 'w') as out_file:
            out_file.write(self.escn_file.to_string())

        return True

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

        self.gdscripts = []
        self.vs_scripts = {}
        self.escn_file = None
        self.bl_object_gd_node_map = {}

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

    with GodotExporter(filepath, kwargs, operator) as exp:
        exp.export()

    logging.getLogger().removeHandler(exporter_log_handler)

    return {"FINISHED"}
