export interface Panel {
  id: number;
  area: number;
  is_base: boolean;
  polygon: [number, number][];
}

export interface Hinge {
  panel_a: number;
  panel_b: number;
  points: [[number, number], [number, number]];
  in_tree: boolean;
}

export interface TreeNode {
  panelId: number;
  parentId: number | null;
  /** Hinge endpoints shared with the parent, or null for a root (base) panel. */
  hinge: [[number, number], [number, number]] | null;
  children: TreeNode[];
}

/** BFS the in-tree hinges from each base panel into a parent/child forest —
 * one tree per connected component, mirroring the backend's spanning-tree
 * construction (app/mesh/dieline.py's _compute_transforms). */
export function buildKinematicForest(panels: Panel[], hinges: Hinge[]): TreeNode[] {
  const adjacency = new Map<number, { other: number; hinge: Hinge }[]>();
  panels.forEach((p) => adjacency.set(p.id, []));
  hinges
    .filter((h) => h.in_tree)
    .forEach((h) => {
      adjacency.get(h.panel_a)?.push({ other: h.panel_b, hinge: h });
      adjacency.get(h.panel_b)?.push({ other: h.panel_a, hinge: h });
    });

  const visited = new Set<number>();
  const roots: TreeNode[] = [];

  for (const base of panels.filter((p) => p.is_base)) {
    if (visited.has(base.id)) continue;
    const rootNode: TreeNode = { panelId: base.id, parentId: null, hinge: null, children: [] };
    visited.add(base.id);

    const queue: TreeNode[] = [rootNode];
    while (queue.length) {
      const current = queue.shift();
      if (!current) break;
      for (const { other, hinge } of adjacency.get(current.panelId) ?? []) {
        if (visited.has(other)) continue;
        visited.add(other);
        const childNode: TreeNode = {
          panelId: other,
          parentId: current.panelId,
          hinge: hinge.points,
          children: [],
        };
        current.children.push(childNode);
        queue.push(childNode);
      }
    }
    roots.push(rootNode);
  }

  return roots;
}
