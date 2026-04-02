const API_KEY_STORAGE_KEY = "ob_api_key";

export function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(API_KEY_STORAGE_KEY);
}

export function setApiKey(key: string): void {
  localStorage.setItem(API_KEY_STORAGE_KEY, key);
}

export function removeApiKey(): void {
  localStorage.removeItem(API_KEY_STORAGE_KEY);
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function api<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const key = getApiKey();
  if (!key) throw new ApiError(401, "NOT_AUTHENTICATED");

  const headers: Record<string, string> = {
    "X-API-Key": key,
  };

  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) {
    removeApiKey();
    throw new ApiError(401, "NOT_AUTHENTICATED");
  }

  if (!res.ok) {
    throw new ApiError(res.status, `API error: ${res.status}`);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

/**
 * Validate an API key by hitting a known endpoint.
 * Returns true if the key is valid (200 or 404), false on 401.
 */
export async function validateApiKey(key: string): Promise<boolean> {
  const res = await fetch("/v1/pulse/today", {
    method: "GET",
    headers: { "X-API-Key": key },
  });

  // 200 = pulse exists, 404 = no pulse yet — both mean key is valid
  if (res.status === 200 || res.status === 404) return true;
  // 401 = invalid key
  return false;
}
