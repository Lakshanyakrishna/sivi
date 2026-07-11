"use client";

import { type RefObject, useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFExporter } from "three/examples/jsm/exporters/GLTFExporter.js";

export interface ThreeContext {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  controls: OrbitControls;
}

/** Shared renderer/camera/lighting/shadow/resize/animate-loop scaffold.
 * Each viewer adds its own content into `ctx.scene` and cleans it up itself. */
export function useThreeScene(containerRef: RefObject<HTMLDivElement | null>) {
  const ctxRef = useRef<ThreeContext | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf2f2f2);

    const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 100);
    camera.position.set(2.4, 1.8, 2.8);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 0.4;
    controls.maxDistance = 30;

    const ambient = new THREE.AmbientLight(0xffffff, 0.7);
    scene.add(ambient);

    const key = new THREE.DirectionalLight(0xffffff, 2.4);
    key.position.set(3, 5, 4);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    key.shadow.camera.left = -3;
    key.shadow.camera.right = 3;
    key.shadow.camera.top = 3;
    key.shadow.camera.bottom = -3;
    key.shadow.bias = -0.001;
    scene.add(key);

    const fill = new THREE.DirectionalLight(0xffffff, 0.6);
    fill.position.set(-3, 2, -2);
    scene.add(fill);

    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(30, 30),
      new THREE.ShadowMaterial({ opacity: 0.18 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -1.05;
    ground.receiveShadow = true;
    scene.add(ground);

    ctxRef.current = { scene, camera, renderer, controls };

    function resize() {
      if (!container) return;
      const { clientWidth, clientHeight } = container;
      if (clientWidth === 0 || clientHeight === 0) return;
      camera.aspect = clientWidth / clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(clientWidth, clientHeight);
    }
    resize();
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(container);

    let frameId = 0;
    function animate() {
      frameId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    }
    animate();

    return () => {
      cancelAnimationFrame(frameId);
      resizeObserver.disconnect();
      controls.dispose();
      renderer.dispose();
      if (renderer.domElement.parentElement === container) {
        container.removeChild(renderer.domElement);
      }
      ctxRef.current = null;
    };
  }, [containerRef]);

  return ctxRef;
}

/** Center + scale an object so its longest bounding-box side is `targetSize`,
 * and re-point the orbit controls/camera at its new center. */
export function frameObject(
  object: THREE.Object3D,
  camera: THREE.PerspectiveCamera,
  controls: OrbitControls,
  targetSize = 2.2,
) {
  const box = new THREE.Box3().setFromObject(object);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const longest = Math.max(size.x, size.y, size.z) || 1;
  const scale = targetSize / longest;
  object.scale.setScalar(scale);

  const scaledCenter = center.multiplyScalar(scale);
  object.position.sub(scaledCenter);

  controls.target.set(0, 0, 0);
  camera.position.set(targetSize * 1.1, targetSize * 0.85, targetSize * 1.3);
  camera.near = targetSize / 100;
  camera.far = targetSize * 50;
  camera.updateProjectionMatrix();
  controls.update();
}

export type MaterialStyle = "matte" | "glossy" | "wireframe";

/** Apply a named look to a MeshStandardMaterial in place — shared by every
 * viewer so "Matte" / "Glossy" / "Wireframe" mean the same thing everywhere. */
export function applyMaterialStyle(material: THREE.MeshStandardMaterial, style: MaterialStyle) {
  material.wireframe = style === "wireframe";
  if (style === "glossy") {
    material.roughness = 0.15;
    material.metalness = 0.35;
  } else {
    material.roughness = 0.85;
    material.metalness = 0.05;
  }
  material.needsUpdate = true;
}

/** Apply a material style to every MeshStandardMaterial found under `object`
 * (e.g. a loaded GLTF scene, whose materials aren't otherwise reachable). */
export function applyMaterialStyleToObject(object: THREE.Object3D, style: MaterialStyle) {
  object.traverse((child) => {
    if (!(child instanceof THREE.Mesh)) return;
    const materials = Array.isArray(child.material) ? child.material : [child.material];
    for (const material of materials) {
      if (material instanceof THREE.MeshStandardMaterial) {
        applyMaterialStyle(material, style);
      }
    }
  });
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export async function exportObjectAsGlb(object: THREE.Object3D, filename: string) {
  const exporter = new GLTFExporter();
  const result = await exporter.parseAsync(object, { binary: true });
  const blob = new Blob([result as ArrayBuffer], { type: "model/gltf-binary" });
  downloadBlob(blob, filename);
}

/** Recursively dispose geometries/materials/textures under `object`. */
export function disposeObject(object: THREE.Object3D) {
  object.traverse((child) => {
    if (child instanceof THREE.Mesh) {
      child.geometry?.dispose();
      const materials = Array.isArray(child.material) ? child.material : [child.material];
      for (const material of materials) {
        if (!material) continue;
        for (const key of Object.keys(material) as (keyof typeof material)[]) {
          const value = material[key];
          if (value instanceof THREE.Texture) value.dispose();
        }
        material.dispose();
      }
    }
  });
}
