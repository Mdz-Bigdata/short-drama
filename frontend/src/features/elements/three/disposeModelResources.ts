import type { BufferGeometry, Material, Object3D, Texture } from 'three';


export function disposeModelResources(root: Object3D) {
  const geometries = new Set<BufferGeometry>();
  const materials = new Set<Material>();
  const textures = new Set<Texture>();

  root.traverse(object => {
    const renderable = object as Object3D & {
      geometry?: BufferGeometry;
      material?: Material | Material[];
    };
    if (renderable.geometry?.dispose) geometries.add(renderable.geometry);
    const objectMaterials = Array.isArray(renderable.material) ? renderable.material : [renderable.material];
    objectMaterials.forEach(material => {
      if (!material?.dispose) return;
      materials.add(material);
      Object.values(material).forEach(value => {
        if (value && typeof value === 'object' && 'isTexture' in value && value.isTexture) {
          textures.add(value as Texture);
        }
      });
    });
  });

  textures.forEach(texture => {
    const image = (texture as Texture & { source?: { data?: unknown }; image?: unknown }).source?.data
      ?? (texture as Texture & { image?: unknown }).image;
    if (typeof ImageBitmap !== 'undefined' && image instanceof ImageBitmap) image.close();
    texture.dispose();
  });
  materials.forEach(material => material.dispose());
  geometries.forEach(geometry => geometry.dispose());
}
