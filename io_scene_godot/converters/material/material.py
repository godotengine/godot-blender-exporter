"""
Exports materials. For now I'm targetting the blender internal, however this
will be deprecated in Blender 2.8 in favor of EEVEE. EEVEE has PBR and
should be able to match Godot better, but unfortunately parseing a node
tree into a flat bunch of parameters is not trivial. So for someone else:"""

import logging
import os
import bpy
from .script_shader import export_script_shader
from ...structures import (
    InternalResource, ExternalResource, gamma_correct, ValidationError)


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

    imgpath = os.path.relpath(
        imgpath,
        os.path.dirname(export_settings['path'])
    ).replace("\\", "/")

    # Add the image to the file
    image_resource = ExternalResource(imgpath, "Image")
    image_id = escn_file.add_external_resource(image_resource, image)

    return image_id


def export_material(escn_file, export_settings, material):
    """Exports blender internal/cycles material as best it can"""
    external_material = find_material(export_settings, material)
    if external_material is not None:
        resource_id = escn_file.get_external_resource(material)
        if resource_id is None:
            ext_mat = ExternalResource(
                external_material[0],  # Path
                external_material[1]  # Material Type
            )
            resource_id = escn_file.add_external_resource(ext_mat, material)
        return "ExtResource({})".format(resource_id)

    resource_id = generate_material_resource(
        escn_file, export_settings, material
    )
    return "SubResource({})".format(resource_id)


def generate_material_resource(escn_file, export_settings, material):
    """Export blender material as an internal resource"""
    resource_id = escn_file.get_internal_resource(material)
    if resource_id is not None:
        return resource_id

    engine = bpy.context.scene.render.engine
    mat = None

    if export_settings['generate_external_material']:
        material_rsc_name = material.name
    else:
        # leave material_name as empty, prevent godot
        # to convert material to external file
        material_rsc_name = ''

    if (engine in ('CYCLES', 'BLENDER_EEVEE') and
            material.node_tree is not None):
        mat = InternalResource("ShaderMaterial", material_rsc_name)
        try:
            export_script_shader(
                escn_file, export_settings, material, mat
            )
        except ValidationError as exception:
            mat = None  # revert to SpatialMaterial
            logging.error(
                "%s, in material '%s'", str(exception), material.name
            )

    if mat is None:
        mat = InternalResource("SpatialMaterial", material_rsc_name)
        mat['albedo_color'] = gamma_correct(material.diffuse_color)
    return escn_file.add_internal_resource(mat, material)


# ------------------- Tools for finding existing materials -------------------
def _find_material_in_subtree(folder, material):
    """Searches for godot materials that match a blender material. If found,
    it returns (path, type) otherwise it returns None"""
    candidates = []

    material_file_name = material.name + '.tres'
    for dir_path, _subdirs, files in os.walk(folder):
        if material_file_name in files:
            candidates.append(os.path.join(dir_path, material_file_name))

    # Checks it is a material and finds out what type
    valid_candidates = []
    for candidate in candidates:
        with open(candidate) as mat_file:
            first_line = mat_file.readline()
            if "SpatialMaterial" in first_line:
                valid_candidates.append((candidate, "SpatialMaterial"))
            if "ShaderMaterial" in first_line:
                valid_candidates.append((candidate, "ShaderMaterial"))

    if not valid_candidates:
        return None
    if len(valid_candidates) > 1:
        logging.warning("Multiple materials found for %s", material.name)
    return valid_candidates[0]


def find_material(export_settings, material):
    """Searches for an existing Godot material"""
    search_type = export_settings["material_search_paths"]
    if search_type == "PROJECT_DIR":
        search_dir = export_settings["project_path_func"]()
    elif search_type == "EXPORT_DIR":
        search_dir = os.path.dirname(export_settings["path"])
    else:
        search_dir = None

    if search_dir is None:
        return None
    return _find_material_in_subtree(search_dir, material)
