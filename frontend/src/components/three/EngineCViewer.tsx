"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { getAssetFeatures, getMeshFeatures, resolveUrl } from "@/lib/api";
import { buildKinematicForest, type Hinge, type Panel, type TreeNode } from "@/lib/kinematic-tree";
import {
  applyMaterialStyle,
  disposeObject,
  exportObjectAsGlb,
  frameObject,
  useThreeScene,
  type MaterialStyle,
} from "@/lib/three-scene";

interface EngineCViewerProps {
  assetId: string;
  hideControls?: boolean;
  materialStyle?: MaterialStyle;
  externalFoldAngle?: number;
  registerExport?: (fn: () => Promise<void>) => void;
}

interface MeshFeatures {
  panels: Panel[];
  hinges: Hinge[];
  fold_angle_deg: number;
}

interface ReferenceBox {
  minX: number;
  minY: number;
  width: number;
  height: number;
}

const CARDBOARD_COLOR = 0xc4a484;

function referenceBoxFromFeatures(features: Record<string, unknown>): ReferenceBox {
  const viewBox = features.view_box as { min_x: number; min_y: number; width: number; height: number } | undefined;
  if (viewBox) return { minX: viewBox.min_x, minY: viewBox.min_y, width: viewBox.width, height: viewBox.height };

  const pageSize = features.page_size as { width: number; height: number } | undefined;
  if (pageSize) return { minX: 0, minY: 0, width: pageSize.width, height: pageSize.height };

  const imageSize = features.image_size as { width: number; height: number } | undefined;
  if (imageSize) return { minX: 0, minY: 0, width: imageSize.width, height: imageSize.height };

  return { minX: 0, minY: 0, width: 100, height: 100 };
}

function buildPanelGeometries(
  polygon: [number, number][],
  thickness: number,
  ref: ReferenceBox,
): { artwork: THREE.BufferGeometry; cardboard: THREE.BufferGeometry } {
  const shape = new THREE.Shape(polygon.map(([x, y]) => new THREE.Vector2(x, -y)));

  const artwork = new THREE.ShapeGeometry(shape);
  const pos = artwork.attributes.position;
  const uv = new Float32Array(pos.count * 2);
  for (let i = 0; i < pos.count; i++) {
    const shapeX = pos.getX(i);
    const shapeY = pos.getY(i);
    uv[i * 2] = (shapeX - ref.minX) / ref.width;
    uv[i * 2 + 1] = (-shapeY - ref.minY) / ref.height;
  }
  artwork.setAttribute("uv", new THREE.BufferAttribute(uv, 2));

  // Recess the cardboard extrusion slightly so its (unused/hidden) front cap
  // doesn't z-fight with the separate artwork plane occupying the same z=0.
  const epsilon = thickness * 0.15;
  const cardboard = new THREE.ExtrudeGeometry(shape, { depth: thickness, bevelEnabled: false });
  cardboard.translate(0, 0, epsilon);

  return { artwork, cardboard };
}

function createPanelGroup(
  node: TreeNode,
  panelsById: Map<number, Panel>,
  thickness: number,
  ref: ReferenceBox,
  artworkMaterial: THREE.Material,
  cardboardMaterial: THREE.Material,
  pivotGroups: Map<number, THREE.Group>,
  axisById: Map<number, THREE.Vector3>,
  parentPivot: { x: number; y: number } = { x: 0, y: 0 },
): THREE.Group {
  const panel = panelsById.get(node.panelId);
  const pivotGroup = new THREE.Group();
  pivotGroups.set(node.panelId, pivotGroup);

  // This node's own absolute pivot (flat-space, Y already flipped) — (0,0)
  // for the root. pivotGroup.position must be relative to the PARENT pivot
  // group's local frame, not this absolute point directly: nesting means a
  // deeper node's pivotGroup already sits inside a frame translated by every
  // ancestor's own pivot, so only the *delta* from the parent belongs here.
  let thisPivot = parentPivot;
  if (node.hinge) {
    const [p1, p2] = node.hinge;
    thisPivot = { x: p1[0], y: -p1[1] };
    const axis = new THREE.Vector3(p2[0] - p1[0], -(p2[1] - p1[1]), 0).normalize();

    // Choose the axis sign so this child folds to the same side as its
    // siblings, relative to their shared parent — otherwise flaps can fold
    // to opposite sides (depending on which way this hinge edge happened to
    // be wound) and the net never closes into a coherent box. This is a
    // fixed geometric relationship in the flat/pre-fold layout, so no
    // parent-transform math is needed here: Three.js's own scene-graph
    // nesting already applies it relative to the parent's current rotation.
    // Computed in the same raw (unflipped) coordinate space the backend
    // uses, so the live viewer's fold direction matches the exported GLB's.
    if (panel) {
      const n = panel.polygon.length;
      const centroidRaw = panel.polygon.reduce(
        (acc, [x, y]) => [acc[0] + x / n, acc[1] + y / n] as [number, number],
        [0, 0] as [number, number],
      );
      const axisRawX = p2[0] - p1[0];
      const axisRawY = p2[1] - p1[1];
      const rRawX = centroidRaw[0] - p1[0];
      const rRawY = centroidRaw[1] - p1[1];
      const crossZRaw = axisRawX * rRawY - axisRawY * rRawX;
      if (crossZRaw < 0) axis.multiplyScalar(-1);
    }

    axisById.set(node.panelId, axis);
    pivotGroup.position.set(thisPivot.x - parentPivot.x, thisPivot.y - parentPivot.y, 0);
  }

  const contentGroup = new THREE.Group();
  contentGroup.position.set(-thisPivot.x, -thisPivot.y, 0);
  pivotGroup.add(contentGroup);

  if (panel) {
    const { artwork, cardboard } = buildPanelGeometries(panel.polygon, thickness, ref);
    const artworkMesh = new THREE.Mesh(artwork, artworkMaterial);
    artworkMesh.castShadow = true;
    artworkMesh.receiveShadow = true;
    const cardboardMesh = new THREE.Mesh(cardboard, cardboardMaterial);
    cardboardMesh.castShadow = true;
    cardboardMesh.receiveShadow = true;
    contentGroup.add(artworkMesh, cardboardMesh);
  }

  for (const child of node.children) {
    pivotGroup.add(
      createPanelGroup(
        child,
        panelsById,
        thickness,
        ref,
        artworkMaterial,
        cardboardMaterial,
        pivotGroups,
        axisById,
        thisPivot,
      ),
    );
  }

  return pivotGroup;
}

function applyFoldAngle(
  pivotGroups: Map<number, THREE.Group>,
  axisById: Map<number, THREE.Vector3>,
  angleDeg: number,
) {
  const angleRad = THREE.MathUtils.degToRad(angleDeg);
  for (const [panelId, group] of pivotGroups) {
    const axis = axisById.get(panelId);
    if (!axis) continue;
    group.quaternion.setFromAxisAngle(axis, angleRad);
  }
}

export default function EngineCViewer({
  assetId,
  hideControls,
  materialStyle = "matte",
  externalFoldAngle,
  registerExport,
}: EngineCViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const ctxRef = useThreeScene(containerRef);
  const rootRef = useRef<THREE.Group | null>(null);
  const pivotGroupsRef = useRef<Map<number, THREE.Group>>(new Map());
  const axisByIdRef = useRef<Map<number, THREE.Vector3>>(new Map());
  const artworkMaterialRef = useRef<THREE.MeshStandardMaterial | null>(null);
  const cardboardMaterialRef = useRef<THREE.MeshStandardMaterial | null>(null);

  const [data, setData] = useState<{ mesh: MeshFeatures; ref: ReferenceBox } | null>(null);
  const [textureLoaded, setTextureLoaded] = useState(false);
  const textureRef = useRef<THREE.Texture | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [internalFoldAngle, setInternalFoldAngle] = useState(90);
  const [isExporting, setIsExporting] = useState(false);

  const foldAngle = externalFoldAngle ?? internalFoldAngle;

  useEffect(() => {
    let cancelled = false;
    Promise.all([getMeshFeatures(assetId), getAssetFeatures(assetId)])
      .then(([meshFeatures, dielineFeatures]) => {
        if (cancelled) return;
        setData({
          mesh: meshFeatures as unknown as MeshFeatures,
          ref: referenceBoxFromFeatures(dielineFeatures),
        });
        setInternalFoldAngle((meshFeatures as unknown as MeshFeatures).fold_angle_deg ?? 90);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load panel data"));
    return () => {
      cancelled = true;
    };
  }, [assetId]);

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

  // Build the panel/hinge scene graph once per asset; fold-angle slider only
  // updates existing group rotations afterward (see the effect below).
  useEffect(() => {
    const ctx = ctxRef.current;
    if (!ctx || !data) return;

    const { panels, hinges } = data.mesh;
    const panelsById = new Map(panels.map((p) => [p.id, p]));
    const forest = buildKinematicForest(panels, hinges);

    const allPoints = panels.flatMap((p) => p.polygon);
    const xs = allPoints.map((p) => p[0]);
    const ys = allPoints.map((p) => p[1]);
    const diag = Math.hypot(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) || 100;
    const thickness = Math.max(diag * 0.01, 1);

    const artworkMaterial = new THREE.MeshStandardMaterial({
      map: textureRef.current ?? null,
      side: THREE.DoubleSide,
    });
    applyMaterialStyle(artworkMaterial, materialStyle);
    const cardboardMaterial = new THREE.MeshStandardMaterial({
      color: CARDBOARD_COLOR,
      side: THREE.DoubleSide,
    });
    applyMaterialStyle(cardboardMaterial, materialStyle);

    const pivotGroups = new Map<number, THREE.Group>();
    const axisById = new Map<number, THREE.Vector3>();
    const root = new THREE.Group();
    for (const tree of forest) {
      root.add(
        createPanelGroup(tree, panelsById, thickness, data.ref, artworkMaterial, cardboardMaterial, pivotGroups, axisById),
      );
    }

    ctx.scene.add(root);
    rootRef.current = root;
    pivotGroupsRef.current = pivotGroups;
    axisByIdRef.current = axisById;
    artworkMaterialRef.current = artworkMaterial;
    cardboardMaterialRef.current = cardboardMaterial;

    applyFoldAngle(pivotGroups, axisById, foldAngle);
    frameObject(root, ctx.camera, ctx.controls);

    if (registerExport) registerExport(handleExport);

    return () => {
      ctx.scene.remove(root);
      disposeObject(root);
      rootRef.current = null;
      pivotGroupsRef.current = new Map();
      axisByIdRef.current = new Map();
      artworkMaterialRef.current = null;
      cardboardMaterialRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctxRef, data, registerExport]);

  // Live fold-angle updates: rotate existing pivot groups, no rebuild.
  useEffect(() => {
    applyFoldAngle(pivotGroupsRef.current, axisByIdRef.current, foldAngle);
  }, [foldAngle]);

  // Attach the texture once loaded, even if the panels were built first —
  // only the artwork material gets it, never the cardboard one.
  useEffect(() => {
    const material = artworkMaterialRef.current;
    if (!textureLoaded || !material || !textureRef.current) return;
    material.map = textureRef.current;
    material.needsUpdate = true;
  }, [textureLoaded, data]);

  // Live material-style updates — no rebuild, both materials restyled together.
  useEffect(() => {
    if (artworkMaterialRef.current) applyMaterialStyle(artworkMaterialRef.current, materialStyle);
    if (cardboardMaterialRef.current) applyMaterialStyle(cardboardMaterialRef.current, materialStyle);
  }, [materialStyle, data]);

  async function handleExport() {
    if (!rootRef.current) return;
    setIsExporting(true);
    try {
      await exportObjectAsGlb(rootRef.current, `sivi-dieline-fold-${Math.round(foldAngle)}.glb`);
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
          <label className="flex flex-col gap-1 text-xs">
            <span className="opacity-60">Fold ({Math.round(foldAngle)}°)</span>
            <input
              type="range"
              min={0}
              max={180}
              step={1}
              value={foldAngle}
              onChange={(e) => setInternalFoldAngle(Number(e.target.value))}
            />
          </label>

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
