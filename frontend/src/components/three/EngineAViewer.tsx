"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import {
  applyMaterialStyleToObject,
  disposeObject,
  exportObjectAsGlb,
  frameObject,
  useThreeScene,
  type MaterialStyle,
} from "@/lib/three-scene";

interface EngineAViewerProps {
  glbUrl: string;
  hideControls?: boolean;
  materialStyle?: MaterialStyle;
  registerExport?: (fn: () => Promise<void>) => void;
}

export default function EngineAViewer({
  glbUrl,
  hideControls,
  materialStyle = "matte",
  registerExport,
}: EngineAViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const ctxRef = useThreeScene(containerRef);
  const objectRef = useRef<THREE.Object3D | null>(null);
  const [isExporting, setIsExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctx = ctxRef.current;
    if (!ctx) return;

    let cancelled = false;
    const loader = new GLTFLoader();
    loader.load(
      glbUrl,
      (gltf) => {
        if (cancelled) return;
        gltf.scene.traverse((child) => {
          if (child instanceof THREE.Mesh) {
            child.castShadow = true;
            child.receiveShadow = true;
          }
        });
        applyMaterialStyleToObject(gltf.scene, materialStyle);
        ctx.scene.add(gltf.scene);
        objectRef.current = gltf.scene;
        frameObject(gltf.scene, ctx.camera, ctx.controls);
        registerExport?.(handleExport);
      },
      undefined,
      (err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load model");
      },
    );

    return () => {
      cancelled = true;
      if (objectRef.current) {
        ctx.scene.remove(objectRef.current);
        disposeObject(objectRef.current);
        objectRef.current = null;
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [glbUrl, ctxRef, registerExport]);

  // Live material-style updates without re-fetching the GLB.
  useEffect(() => {
    if (objectRef.current) applyMaterialStyleToObject(objectRef.current, materialStyle);
  }, [materialStyle]);

  async function handleExport() {
    if (!objectRef.current) return;
    setIsExporting(true);
    try {
      await exportObjectAsGlb(objectRef.current, "sivi-real-object.glb");
    } finally {
      setIsExporting(false);
    }
  }

  return (
    <div className={hideControls ? "size-full" : "flex flex-col gap-2"}>
      <div
        ref={containerRef}
        className={hideControls ? "size-full" : "h-80 w-full overflow-hidden rounded-lg border border-black/10 dark:border-white/15"}
      />
      {error && <p className="text-xs text-red-500">{error}</p>}
      {!hideControls && (
        <button
          type="button"
          onClick={handleExport}
          disabled={isExporting}
          className="self-start rounded-full border border-black/15 px-3 py-1.5 text-xs font-medium transition-colors hover:bg-black/5 disabled:opacity-50 dark:border-white/20 dark:hover:bg-white/10"
        >
          {isExporting ? "Exporting…" : "Download .glb"}
        </button>
      )}
    </div>
  );
}
