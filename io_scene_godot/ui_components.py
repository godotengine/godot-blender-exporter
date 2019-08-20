import bpy

LAST_EXPORT = {}

def set_export_config(path, options):
    LAST_EXPORT['filepath'] = path
    LAST_EXPORT.update(options)

class GodotTextProps(bpy.types.Panel):
    bl_label = "Godot"
    bl_idname = "TEXT_PT_GODOT"
    bl_space_type = 'TEXT_EDITOR'
    bl_region_type = 'UI'
    @classmethod
    def poll(self, context):
        if context.edit_text:
            return True

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        for keyname in context.edit_text.keys():
            if not keyname.startswith('gd'):
                continue
            row = layout.row()
            value = context.edit_text[keyname]
            if keyname.startswith('gdinclude'):
                row.label(text='%s <bpy.data.texts["%s"]>' % (keyname, value))
            elif keyname.startswith('gdpreload'):
                row.label(text='%s <%s>' % (keyname, value))
            elif keyname == 'gdextends':
                row.label(text='script extends <%s>' % value)
            else:
                gdtype = ''
                if ':' in keyname:
                    gdtype = keyname.split(':')[-1].split('.')[0].strip()
                vname = keyname.strip().split()[-1]
                if '.' in vname:
                    vname = vname.replace('.', '_')
                row.label(text='%s :%s= %s' % (vname, gdtype, value))


class GodotObProps(bpy.types.Panel):
    bl_label = "Godot"
    bl_idname = "OBJECT_PT_GODOT_PROPS"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    def draw(self, context):
        layout = self.layout
        obj = context.object
        for keyname in obj.keys():
            if keyname.startswith('gd'):
                value = obj[keyname]
                row = layout.row()
                if keyname == 'gdscript':
                    if value in bpy.data.texts:
                        row.label(text='gdscript: <bpy.data.texts["%s"]>' % value)
                    else:
                        row.label(text='gdscript: ' % value)
                elif keyname == 'gdvs':
                    if value in bpy.data.texts:
                        row.label(text='vscript: <bpy.data.texts["%s"]>' % value)
                    else:
                        row.label(text='vscript: <inline>')
                elif keyname.startswith('gdpreload'):
                    row.label('%s <%s>' % (keyname, value))
                elif keyname == 'gdextends':
                    row.label(text='script extends <%s>' % value)
                elif keyname.startswith('gdinclude'):
                    if value in bpy.data.texts:
                        row.label(text='include: <bpy.data.texts["%s"]>' % value)
                    else:
                        row.label(text='WARN include missing: %s' % value)
                elif keyname=='gdprim':
                    row.label(text='prim type: %s' % value)
                elif keyname=='gdprim_radius':
                    row.label(text='prim radius: %s' % value)
                else:
                    gdtype = ''
                    if ':' in keyname:
                        gdtype = keyname.split(':')[-1].split('.')[0].strip()
                    vname = keyname.strip().split()[-1]
                    if '.' in vname:
                        vname = vname.replace('.', '_')
                    row.label(text='%s :%s= %s' % (vname, gdtype, value))


class ReExportGodot(bpy.types.Operator):
    bl_idname = "export_godot.reexport"
    bl_label = "ReExport"
    def execute(self, context):
        print(LAST_EXPORT)
        from . import export_godot
        return export_godot.save(self, context, **LAST_EXPORT)

class GodotPrim(bpy.types.Operator):
    bl_idname = "export_godot.new_prim"
    bl_label = "godot primitive"
    prim_type = bpy.props.StringProperty(
        name="godot primitive type",
        description="godot static primitive.",
        default='',
    )
    prim_radius = 0.5
    def execute(self, context):
        op = getattr(bpy.ops.mesh, 'primitive_%s_add' % self.prim_type)
        if self.prim_type not in ('uv_sphere', 'ico_sphere', 'cylinder'):
            res = op( size=self.prim_radius*2 )
        else:
            res = op( radius=self.prim_radius )

        bpy.context.object['gdprim'] = self.prim_type.split('_')[-1]
        bpy.context.object['gdprim_radius'] = self.prim_radius
        return res


class GodotTopBar(bpy.types.Header):
    bl_space_type = 'TOPBAR'
    bl_idname = "GODOT_HT_TOOLS"

    def draw(self, context):
        op = self.layout.operator('export_godot.new_prim', text='', icon="MESH_CUBE")
        op.prim_type = 'cube'
        op = self.layout.operator('export_godot.new_prim', text='', icon="MESH_ICOSPHERE")
        op.prim_type = 'ico_sphere'
        op = self.layout.operator('export_godot.new_prim', text='', icon="MESH_CYLINDER")
        op.prim_type = 'cylinder'

        if LAST_EXPORT:
            op = self.layout.operator("export_godot.reexport", text='escn')
