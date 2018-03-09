"""
Exports materials. For now I'm targetting the blender internal, however this
will be deprecated in Blender 2.8 in favor of EEVEE. EEVEE has PBR and
should be able to match Godot better, but unfortunately parseing a node
tree into a flat bunch of parameters is not trivial. So for someone else:"""
# TODO: Add EEVEE support


import bpy
import mathutils
from ..structures import InternalResource


def export_image(escn_file, export_settings, image):
    """
    Saves an image as an external reference relative to the blend location
    """
    image_id = escn_file.get_external_resource(image)
    if image_id is not None:
        return image_id


    imgpath = image.filepath
    if imgpath.startswith("//"):
        imgpath = bpy.path.abspath(imgpath)

    imgpath = os.path.relpath(imgpath, os.path.dirname(self.path)).replace("\\", "/")

    # Add the image to the file
    image_resource = ExternalResource("Image", imgpath)
    image_id = escn_file.add_external_resource(image_resource, image)

    return image_id


def export_material(escn_file, export_settings, material):
    print(material)
    resource_id = escn_file.get_internal_resource(material)
    if resource_id is not None:
        return resource_id

    mat = InternalResource("SpatialMaterial")

    mat.flags_unshaded = material.use_shadeless
    mat.flags_vertex_lighting = material.use_vertex_color_light
    mat.flags_transparent = material.use_transparency
    mat.vertex_color_use_as_albedo = material.use_vertex_color_paint
    mat.albedo_color = material.diffuse_color
    mat.subsurf_scatter_enabled = material.subsurface_scattering.use


    resource_id = escn_file.add_internal_resource(mat, material)
    return resource_id
