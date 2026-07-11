"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { getAssetFeatures, resolveUrl } from "@/lib/api";
import {
  applyMaterialStyle,
  disposeObject,
  exportObjectAsGlb,
  frameObject,
  useThreeScene,
  type MaterialStyle,
} from "@/lib/three-scene";

interface EngineBViewerProps {
  assetId: string;
  hideControls?: boolean;
  materialStyle?: MaterialStyle;
  externalValues?: {
    thickness: number;
    bevelThickness: number;
    bevelSize: number;
  };
  registerExport?: (fn: () => Promise<void>) => void;
}

interface Contour {
  type: "outer" | "hole";
  points: [number, number][];
  parent_index: number | null;
}

interface FlatGraphicFeatures {
  image_size: { width: number; height: number };
  contours: Contour[];
}

function buildUVGenerator(imgWidth: number, imgHeight: number) {
  const uvFor = (vertices: number[], index: number) => {
    const x = vertices[index * 3];
    const y = vertices[index * 3 + 1];
    return new THREE.Vector2(x / imgWidth, -y / imgHeight);
  };
  return {
    generateTopUV(_geometry: unknown, vertices: number[], a: number, b: number, c: number) {
      return [uvFor(vertices, a), uvFor(vertices, b), uvFor(vertices, c)];
    },
    generateSideWallUV(
      _geometry: unknown,
      vertices: number[],
      a: number,
      b: number,
      c: number,
      d: number,
    ) {
      return [uvFor(vertices, a), uvFor(vertices, b), uvFor(vertices, c), uvFor(vertices, d)];
    },
  };
}

export default function EngineBViewer({
  assetId,
  hideControls,
  materialStyle = "matte",
  externalValues,
  registerExport,
}: EngineBViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const ctxRef = useThreeScene(containerRef);
  const groupRef = useRef<THREE.Group | null>(null);
  const meshRef = useRef<THREE.Mesh | null>(null);
  const textureRef = useRef<THREE.Texture | null>(null);

  const [features, setFeatures] = useState<FlatGraphicFeatures | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);

  const [internalThickness, setInternalThickness] = useState(30);
  const [internalBevelThickness, setInternalBevelThickness] = useState(6);
  const [internalBevelSize, setInternalBevelSize] = useState(6);
  const [ranges, setRanges] = useState({ thicknessMax: 100, bevelMax: 30 });
  const [textureLoaded, setTextureLoaded] = useState(false);

  const thickness = externalValues?.thickness ?? internalThickness;
  const bevelThickness = externalValues?.bevelThickness ?? internalBevelThickness;
  const bevelSize = externalValues?.bevelSize ?? internalBevelSize;

  // Fetch Phase 2 contour features once.
  useEffect(() => {
    let cancelled = false;
    getAssetFeatures(assetId)
      .then((data) => {
        if (cancelled) return;
        const f = data as unknown as FlatGraphicFeatures;
        setFeatures(f);

        const allPoints = f.contours.flatMap((c) => c.points);
        const xs = allPoints.map((p) => p[0]);
        const ys = allPoints.map((p) => p[1]);
        const w = Math.max(...xs) - Math.min(...xs);
        const h = Math.max(...ys) - Math.min(...ys);
        const diag = Math.hypot(w, h) || 100;

        setInternalThickness(diag * 0.08);
        setInternalBevelThickness(diag * 0.015);
        setInternalBevelSize(diag * 0.015);
        setRanges({ thicknessMax: diag * 0.3, bevelMax: diag * 0.08 });
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load contours"));
    return () => {
      cancelled = true;
    };
  }, [assetId]);

  const shapes = useMemo(() => {
    if (!features) return null;

    const holesByParent = new Map<number, Contour[]>();
    features.contours.forEach((c) => {
      if (c.type === "hole" && c.parent_index != null) {
        const list = holesByParent.get(c.parent_index) ?? [];
        list.push(c);
        holesByParent.set(c.parent_index, list);
      }
    });

    const result: THREE.Shape[] = [];
    features.contours.forEach((c, idx) => {
      if (c.type !== "outer" || c.points.length < 3) return;
      const shape = new THREE.Shape(c.points.map(([x, y]) => new THREE.Vector2(x, -y)));
      for (const hole of holesByParent.get(idx) ?? []) {
        shape.holes.push(new THREE.Path(hole.points.map(([x, y]) => new THREE.Vector2(x, -y))));
      }
      result.push(shape);
    });
    return result;
  }, [features]);

  // Load the artwork texture once.
  useEffect(() => {
    let cancelled = false;
    const loader = new THREE.TextureLoader();
    loader.load(resolveUrl(`/api/assets/${assetId}/artwork.png`), (texture) => {
      if (cancelled) {
        texture.dispose();
        return;
      }
      texture.colorSpace = THREE.SRGBColorSpace;
      textureRef.current = texture;
      setTextureLoaded(true);
    });
    return () => {
      cancelled = true;
      textureRef.current?.dispose();
    };
  }, [assetId]);

  // Create the group + mesh once per asset (not on every slider tick) and
  // frame the camera on it exactly once.
  useEffect(() => {
    const ctx = ctxRef.current;
    if (!ctx || !shapes || shapes.length === 0 || !features) return;

    const uvGenerator = buildUVGenerator(features.image_size.width, features.image_size.height);
    const geometry = new THREE.ExtrudeGeometry(shapes, {
      depth: thickness,
      bevelEnabled: true,
      bevelThickness,
      bevelSize,
      bevelSegments: 3,
      curveSegments: 12,
      UVGenerator: uvGenerator,
    });

    const material = new THREE.MeshStandardMaterial({ map: textureRef.current ?? null });
    applyMaterialStyle(material, materialStyle);
    const mesh = new THREE.Mesh(geometry, material);
    mesh.castShadow = true;
    mesh.receiveShadow = true;

    const group = new THREE.Group();
    group.add(mesh);
    ctx.scene.add(group);

    groupRef.current = group;
    meshRef.current = mesh;
    frameObject(group, ctx.camera, ctx.controls);

    if (registerExport) registerExport(handleExport);

    return () => {
      ctx.scene.remove(group);
      disposeObject(group);
      groupRef.current = null;
      meshRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctxRef, shapes, features, registerExport]);

  // Live geometry swap on slider change — no re-framing, no material rebuild.
  useEffect(() => {
    if (!meshRef.current || !features || !shapes) return;
    const uvGenerator = buildUVGenerator(features.image_size.width, features.image_size.height);
    const newGeometry = new THREE.ExtrudeGeometry(shapes, {
      depth: thickness,
      bevelEnabled: true,
      bevelThickness,
      bevelSize,
      bevelSegments: 3,
      curveSegments: 12,
      UVGenerator: uvGenerator,
    });
    meshRef.current.geometry.dispose();
    meshRef.current.geometry = newGeometry;
  }, [thickness, bevelThickness, bevelSize, shapes, features]);

  // Attach the texture once it's loaded, even if the mesh was built first.
  useEffect(() => {
    const material = meshRef.current?.material;
    if (material instanceof THREE.MeshStandardMaterial && textureRef.current) {
      material.map = textureRef.current;
      material.needsUpdate = true;
    }
  }, [textureLoaded, shapes]);

  // Live material-style updates — no geometry/material rebuild.
  useEffect(() => {
    const material = meshRef.current?.material;
    if (material instanceof THREE.MeshStandardMaterial) {
      applyMaterialStyle(material, materialStyle);
    }
  }, [materialStyle, shapes]);

  async function handleExport() {
    if (!groupRef.current) return;
    setIsExporting(true);
    try {
      await exportObjectAsGlb(groupRef.current, "sivi-flat-graphic.glb");
    } finally {
      setIsExporting(false);
    }
  }

  return (
    <div className={hideControls ? "size-full" : "flex flex-col gap-3"}>
      <div
        ref={containerRef}
        className={hideControls ? "size-full" : "h-80 w-full overflow-hidden rounded-lg border border-black/10 dark:border-white/15"}
      />
      {error && <p className="text-xs text-red-500">{error}</p>}

      {!hideControls && (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <label className="flex flex-col gap-1 text-xs">
              <span className="opacity-60">Thickness</span>
              <input
                type="range"
                min={1}
                max={ranges.thicknessMax}
                step={0.5}
                value={thickness}
                onChange={(e) => setInternalThickness(Number(e.target.value))}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              <span className="opacity-60">Bevel depth</span>
              <input
                type="range"
                min={0}
                max={ranges.bevelMax}
                step={0.5}
                value={bevelThickness}
                onChange={(e) => setInternalBevelThickness(Number(e.target.value))}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              <span className="opacity-60">Bevel size</span>
              <input
                type="range"
                min={0}
                max={ranges.bevelMax}
                step={0.5}
                value={bevelSize}
                onChange={(e) => setInternalBevelSize(Number(e.target.value))}
              />
            </label>
          </div>

          <button
            type="button"
            onClick={handleExport}
            disabled={isExporting}
            className="self-start rounded-full border border-black/15 px-3 py-1.5 text-xs font-medium transition-colors hover:bg-black/5 disabled:opacity-50 dark:border-white/20 dark:hover:bg-white/10"
          >
            {isExporting ? "Exporting…" : "Download .glb"}
          </button>
        </>
      )}
    </div>
  );
}
