import bpy

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
                row.label(text='%s :%s= %s' % (vname, gtype, value))


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
                else:
                    gdtype = ''
                    if ':' in keyname:
                        gdtype = keyname.split(':')[-1].split('.')[0].strip()
                    vname = keyname.strip().split()[-1]
                    if '.' in vname:
                        vname = vname.replace('.', '_')
                    row.label(text='%s :%s= %s' % (vname, gtype, value))
