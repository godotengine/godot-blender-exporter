

def export_image(escn_file, image):
	img_id = self.image_cache.get(image)
	if img_id:
		return img_id

	imgpath = image.filepath
	if imgpath.startswith("//"):
		imgpath = bpy.path.abspath(imgpath)

	try:
		imgpath = os.path.relpath(imgpath, os.path.dirname(self.path)).replace("\\", "/")
	except:
		# TODO: Review, not sure why it fails - maybe try bpy.paths.abspath
		pass

	imgid = str(self.new_external_resource_id())

	self.image_cache[image] = imgid
	self.writel(S_EXTERNAL_RES, 0, '[ext_resource path="' + imgpath + '" type="Texture" id=' + imgid + ']')
	return imgid

def export_material(escn_file, material):
	material_id = self.material_cache.get(material)
	if material_id:
		return material_id

	material_id = str(self.new_resource_id())
	self.material_cache[material] = material_id

	self.writel(S_INTERNAL_RES, 0, '\n[sub_resource type="SpatialMaterial" id=' + material_id + ']\n')
	return material_id
