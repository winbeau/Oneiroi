import { demoRequest, demoUpload } from "@/lib/demo-api";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

export const demoMode = import.meta.env.VITE_DEMO_MODE === "true";
export const apiUrl = (path: string) => `${apiBaseUrl}${path}`;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  if (demoMode) return demoRequest<T>(path, init);
  const response = await fetch(apiUrl(path), {
    ...init,
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = await response.json();
    } catch {
      detail = null;
    }
    const payload = detail as
      | { detail?: string | { code?: string; message?: string } }
      | null;
    const nested = typeof payload?.detail === "object" ? payload.detail : null;
    const message =
      nested?.message ??
      (typeof payload?.detail === "string" ? payload.detail : null) ??
      `API request failed: ${response.status}`;
    throw new ApiError(message, response.status, nested?.code);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function uploadImage<T>(file: File, title?: string): Promise<T> {
  if (demoMode) return (await demoUpload(file)) as T;
  const body = new FormData();
  body.set("file", file);
  if (title) body.set("title", title);
  return apiRequest<T>("/v1/uploads/images", { method: "POST", body });
}
