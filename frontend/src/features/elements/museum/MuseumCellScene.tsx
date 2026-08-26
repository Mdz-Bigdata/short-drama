import { Center, ContactShadows, OrbitControls } from '@react-three/drei';
import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useRef, useState } from 'react';
import {
  Color,
  DoubleSide,
  Group,
  Mesh,
  MeshStandardMaterial,
  type BufferGeometry,
  type Material,
  type Object3D,
  type Texture,
} from 'three';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';

import {
  museumAsset,
  type MuseumCatalogItem,
  type MuseumModelAsset,
} from './museumCatalog';


export type MuseumModelStatus =
  | { state: 'loading' }
  | { state: 'ready' }
  | { state: 'error'; message: string };

type MuseumCellSceneProps = {
  item: MuseumCatalogItem;
  autoRotate: boolean;
  resetKey: number;
  lowQuality: boolean;
  onStatusChange: (status: MuseumModelStatus) => void;
};


function disposeMuseumModel(root: Object3D) {
  const geometries = new Set<BufferGeometry>();
  const materials = new Set<Material>();
  const textures = new Set<Texture>();

  root.traverse(object => {
    const renderable = object as Object3D & {
      geometry?: BufferGeometry;
      material?: Material | Material[];
    };
    if (renderable.geometry?.dispose) geometries.add(renderable.geometry);
    const objectMaterials = Array.isArray(renderable.material)
      ? renderable.material
      : [renderable.material];
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


function tuneMuseumMaterials(root: Object3D, asset: MuseumModelAsset, lowQuality: boolean) {
  root.traverse(object => {
    const mesh = object as Mesh;
    if (!mesh.isMesh) return;

    mesh.castShadow = !lowQuality;
    mesh.receiveShadow = true;
    const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    materials.forEach(material => {
      material.side = DoubleSide;
      if (material instanceof MeshStandardMaterial) {
        const displayMap = material.map ?? null;
        if (displayMap) {
          displayMap.anisotropy = lowQuality ? 2 : 8;
          displayMap.needsUpdate = true;
        }
        material.vertexColors = false;
        material.emissive = new Color('#fff8eb');
        material.emissiveMap = displayMap;
        material.emissiveIntensity = 0.07 * (asset.exposure ?? 1);
        material.envMapIntensity = 0.62 * (asset.exposure ?? 1);
        material.roughness = Math.max(0.34, Math.min(material.roughness, 0.58));
        material.metalness = Math.min(material.metalness, 0.08);
        material.color.setRGB(1.04, 1.035, 1.02);
      }
      material.needsUpdate = true;
    });
  });
}


function MuseumModel({
  asset,
  autoRotate,
  resetKey,
  lowQuality,
  onStatusChange,
}: {
  asset: MuseumModelAsset;
  autoRotate: boolean;
  resetKey: number;
  lowQuality: boolean;
  onStatusChange: (status: MuseumModelStatus) => void;
}) {
  const group = useRef<Group>(null);
  const statusCallback = useRef(onStatusChange);
  const [root, setRoot] = useState<Object3D | null>(null);

  useEffect(() => {
    statusCallback.current = onStatusChange;
  }, [onStatusChange]);

  useEffect(() => {
    let active = true;
    let loadedRoot: Object3D | null = null;
    const controller = new AbortController();
    const dracoLoader = new DRACOLoader();
    const gltfLoader = new GLTFLoader();

    dracoLoader.setDecoderPath(museumAsset('/museum/draco/'));
    dracoLoader.setWorkerLimit(lowQuality ? 1 : 2);
    gltfLoader.setDRACOLoader(dracoLoader);
    statusCallback.current({ state: 'loading' });

    async function loadModel() {
      try {
        const response = await fetch(museumAsset(asset.url), {
          cache: 'force-cache',
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`模型请求失败（HTTP ${response.status}）`);
        }
        const parsed = await gltfLoader.parseAsync(await response.arrayBuffer(), '');
        loadedRoot = parsed.scene;
        tuneMuseumMaterials(loadedRoot, asset, lowQuality);
        if (!active) {
          disposeMuseumModel(loadedRoot);
          loadedRoot = null;
          return;
        }
        setRoot(loadedRoot);
        statusCallback.current({ state: 'ready' });
      } catch (error) {
        if (!active || controller.signal.aborted) return;
        statusCallback.current({
          state: 'error',
          message: error instanceof Error ? error.message : '模型解析失败',
        });
      }
    }

    void loadModel();

    return () => {
      active = false;
      controller.abort();
      dracoLoader.dispose();
      if (loadedRoot) disposeMuseumModel(loadedRoot);
    };
  }, [asset, lowQuality]);

  useFrame((_, delta) => {
    if (group.current && autoRotate) group.current.rotation.y += delta * 0.12;
  });

  useEffect(() => {
    group.current?.rotation.set(0, 0, 0);
  }, [resetKey]);

  if (!root) return null;

  return (
    <group ref={group}>
      <group
        position={asset.position ?? [0, 0, 0]}
        rotation={asset.rotation ?? [0, 0, 0]}
        scale={asset.scale}
      >
        <Center>
          <primitive object={root} />
        </Center>
      </group>
    </group>
  );
}


function MuseumCameraControls({ resetKey, lowQuality }: { resetKey: number; lowQuality: boolean }) {
  const controls = useRef<OrbitControlsImpl>(null);
  const { camera } = useThree();

  useEffect(() => {
    camera.position.set(0, 0.2, 5.8);
    camera.up.set(0, 1, 0);
    controls.current?.target.set(0, 0, 0);
    controls.current?.update();
  }, [camera, resetKey]);

  return (
    <OrbitControls
      ref={controls}
      makeDefault
      enableDamping={!lowQuality}
      dampingFactor={0.08}
      enablePan
      minDistance={2.6}
      maxDistance={9}
    />
  );
}


export default function MuseumCellScene({
  item,
  autoRotate,
  resetKey,
  lowQuality,
  onStatusChange,
}: MuseumCellSceneProps) {
  return (
    <>
      <ambientLight intensity={lowQuality ? 1.35 : 1.18} />
      <hemisphereLight args={['#f2e6d4', '#2a2218', lowQuality ? 1.15 : 0.95]} />
      <directionalLight
        position={[4.2, 5.2, 5.8]}
        intensity={2.35}
        castShadow={!lowQuality}
        color="#fff4e4"
      />
      <directionalLight position={[-4.4, 2.2, 3.6]} intensity={0.72} color="#ffd9a8" />
      {!lowQuality && (
        <spotLight
          position={[-3.6, 3.2, 4.6]}
          angle={0.42}
          penumbra={0.74}
          intensity={0.92}
          color="#ffe8c8"
        />
      )}
      <pointLight position={[2.8, -1.2, 3.2]} intensity={0.38} color="#c9a56a" />

      <MuseumModel
        key={`${item.id}-${lowQuality ? 'low' : 'high'}`}
        asset={item.modelAsset}
        autoRotate={autoRotate}
        resetKey={resetKey}
        lowQuality={lowQuality}
        onStatusChange={onStatusChange}
      />
      {!lowQuality && (
        <ContactShadows
          position={[0, -1.8, 0]}
          opacity={0.42}
          scale={7.8}
          blur={3.4}
          far={4.2}
          color="#000000"
          resolution={512}
        />
      )}
      <MuseumCameraControls resetKey={resetKey} lowQuality={lowQuality} />
    </>
  );
}
