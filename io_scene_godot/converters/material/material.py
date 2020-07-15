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
    InternalResource, ExternalResource, gamma_correct, ValidationError, RGBA)


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


def export_material(escn_file, export_settings, bl_object, material):
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
        escn_file, export_settings, bl_object, material
    )
    return "SubResource({})".format(resource_id)


def export_as_spatial_material(material_rsc_name, material):
    """Export a Blender Material as Godot Spatial Material"""
    mat = InternalResource("SpatialMaterial", material_rsc_name)

    # basic properties we can extract from a blender Material
    # we'll try to override these with better guesses if we can
    mat['albedo_color'] = gamma_correct(material.diffuse_color)
    mat['metallic'] = material.metallic
    mat['metallic_specular'] = material.specular_intensity
    mat['roughness'] = material.roughness

    if not material.node_tree:
        return mat

    out = material.node_tree.get_output_node("ALL")
    if not (out and out.inputs["Surface"].links):
        logging.warning("No Surface output for %s", material.name)
        return mat

    surf = out.inputs["Surface"].links[0].from_node

    def val(key):
        return surf.inputs[key].default_value

    if surf.type == "BSDF_PRINCIPLED":
        mat["albedo_color"] = RGBA([
            *gamma_correct(val("Base Color"))[:3], val("Alpha")
        ])
        mat["flags_transparent"] = val("Alpha") < 1.0

        mat["metallic"] = val("Metallic")
        mat["metallic_specular"] = val("Specular")
        mat["roughness"] = val("Roughness")

        mat["anisotropy_enabled"] = val("Anisotropic") > 0
        mat["anisotropy"] = val("Anisotropic")

        mat["clearcoat_enabled"] = val("Clearcoat") > 0
        mat["clearcoat"] = val("Clearcoat")
        mat["clearcoat_gloss"] = 1.0 - val("Clearcoat Roughness")

        mat["emission_enabled"] = any(val("Emission")[0:3])
        mat["emission_energy"] = 1.0 * any(val("Emission")[0:3])
        mat["emission"] = gamma_correct(val("Emission"))

        mat["subsurf_scatter_enabled"] = val("Subsurface") > 0
        mat["subsurf_scatter_strength"] = val("Subsurface")
    elif surf.type == "EMISSION":
        mat["emission_enabled"] = True
        mat["emission_energy"] = val("Strength") / 100
        mat["emission"] = gamma_correct(val("Color"))
    elif surf.type == "BSDF_DIFFUSE":
        mat["albedo_color"] = gamma_correct(val("Color"))
        mat["albedo_color"] = gamma_correct(val("Roughness"))

    return mat


def generate_material_resource(escn_file, export_settings, bl_object,
                               material):
    """Export blender material as an internal resource"""
    engine = bpy.context.scene.render.engine
    mat = None

    if export_settings['generate_external_material']:
        material_rsc_name = material.name
    else:
        # leave material_name as empty, prevent godot
        # to convert material to external file
        material_rsc_name = ''

    if (export_settings['material_mode'] == 'SCRIPT_SHADER' and
            engine in ('CYCLES', 'BLENDER_EEVEE') and
            material.node_tree is not None):
        mat = InternalResource("ShaderMaterial", material_rsc_name)
        try:
            export_script_shader(
                escn_file, export_settings, bl_object, material, mat
            )
        except ValidationError as exception:
            # fallback to SpatialMaterial
            mat = export_as_spatial_material(material_rsc_name, material)
            logging.error(
                "%s, in material '%s'", str(exception), material.name
            )
    else:  # Spatial Material
        mat = export_as_spatial_material(material_rsc_name, material)

    # make material-object tuple as an identifier, as uniforms is part of
    # material and they are binded with object
    return escn_file.add_internal_resource(mat, (bl_object, material))


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
