export type FileKind = "png" | "jpg" | "pdf" | "svg";

export type PipelineRoute = "real_object" | "flat_graphic" | "packaging_dieline";

export type ProcessingStatus = "unprocessed" | "done" | "error";

export type MeshStatus = "unbuilt" | "done" | "error";

export interface Asset {
  id: string;
  original_filename: string;
  file_kind: FileKind;
  content_type: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  page_count: number | null;
  route: PipelineRoute | null;
  original_file_url: string;
  processing_status: ProcessingStatus;
  processing_error: string | null;
  processed_preview_url: string | null;
  feature_summary: Record<string, unknown> | null;
  mesh_status: MeshStatus;
  mesh_error: string | null;
  mesh_url: string | null;
  mesh_extra_url: string | null;
  mesh_summary: Record<string, unknown> | null;
  created_at: string;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function resolveUrl(path: string): string {
  return `${API_URL}${path}`;
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed with status ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export async function uploadAsset(file: File): Promise<Asset> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_URL}/api/assets/upload`, {
    method: "POST",
    body: formData,
  });
  return handleResponse<Asset>(res);
}

export async function setAssetRoute(assetId: string, route: PipelineRoute): Promise<Asset> {
  const res = await fetch(`${API_URL}/api/assets/${assetId}/route`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ route }),
  });
  return handleResponse<Asset>(res);
}

export async function processAsset(assetId: string): Promise<Asset> {
  const res = await fetch(`${API_URL}/api/assets/${assetId}/process`, {
    method: "POST",
  });
  return handleResponse<Asset>(res);
}

export async function getAssetFeatures(assetId: string): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_URL}/api/assets/${assetId}/features`);
  return handleResponse<Record<string, unknown>>(res);
}

export async function getMeshFeatures(assetId: string): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_URL}/api/assets/${assetId}/mesh-features`);
  return handleResponse<Record<string, unknown>>(res);
}

export async function generateMesh(assetId: string): Promise<Asset> {
  const res = await fetch(`${API_URL}/api/assets/${assetId}/generate-mesh`, {
    method: "POST",
  });
  return handleResponse<Asset>(res);
}
