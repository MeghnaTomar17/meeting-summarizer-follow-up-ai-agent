/** Typed Gateway client. Session tokens deliberately remain in memory. */

export interface ApiErrorPayload {
  code?: string;
  message?: string;
  request_id?: string;
  details?: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(message: string, status: number, code = "API_ERROR", details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface RequestOptions {
  authenticated?: boolean;
  retryOnUnauthorized?: boolean;
}

export const AUTH_SESSION_EXPIRED_EVENT = "meeting-agent:auth-session-expired";

let authTokens: AuthTokens | null = null;
let refreshInFlight: Promise<boolean> | null = null;

export function setAuthTokens(tokens: AuthTokens): void {
  authTokens = tokens;
}

export function getAuthTokens(): AuthTokens | null {
  return authTokens;
}

export function clearAuthTokens(): void {
  authTokens = null;
}

const apiBaseUrl = (import.meta.env.VITE_GATEWAY_API_URL || "/api/v1").replace(/\/$/, "");

function apiUrl(path: string): string {
  return `${apiBaseUrl}/${path.replace(/^\//, "")}`;
}

async function readResponse<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return (await response.json()) as T;
  }
  const text = await response.text();
  return (text || undefined) as T;
}

async function refreshSession(): Promise<boolean> {
  const refreshToken = authTokens?.refresh_token;
  if (!refreshToken) return false;
  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = (async () => {
    try {
      const response = await fetch(apiUrl("auth/refresh"), {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!response.ok) {
        clearAuthTokens();
        return false;
      }
      const tokens = await readResponse<AuthTokens>(response);
      if (!tokens?.access_token || !tokens.refresh_token) {
        clearAuthTokens();
        return false;
      }
      setAuthTokens(tokens);
      return true;
    } catch {
      clearAuthTokens();
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  const authenticated = options.authenticated ?? true;
  const send = () => {
    const headers = new Headers({ Accept: "application/json" });
    if (body !== undefined) headers.set("Content-Type", "application/json");
    if (authenticated && authTokens?.access_token) {
      headers.set("Authorization", `Bearer ${authTokens.access_token}`);
    }
    return fetch(apiUrl(path), {
      method,
      headers,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  };

  let response: Response;
  try {
    response = await send();
    if (
      response.status === 401 && authenticated && options.retryOnUnauthorized !== false
    ) {
      const refreshed = await refreshSession();
      if (refreshed) {
        response = await send();
        if (response.status === 401) {
          clearAuthTokens();
          if (typeof window !== "undefined") {
            window.dispatchEvent(new Event(AUTH_SESSION_EXPIRED_EVENT));
          }
        }
      }
      else if (typeof window !== "undefined") {
        window.dispatchEvent(new Event(AUTH_SESSION_EXPIRED_EVENT));
      }
    }
  } catch {
    throw new ApiError("Unable to reach the Gateway. Check your connection and try again.", 0, "NETWORK_ERROR");
  }

  if (!response.ok) {
    const contentType = response.headers.get("content-type") || "";
    let payload: ApiErrorPayload | undefined;
    if (contentType.includes("application/json")) {
      try {
        const data: unknown = await response.json();
        if (data && typeof data === "object" && "error" in data) {
          const error = (data as { error?: unknown }).error;
          if (error && typeof error === "object") payload = error as ApiErrorPayload;
        }
      } catch {
        // Keep the predictable status-based message for malformed error bodies.
      }
    }
    throw new ApiError(
      payload?.message || `Request failed with status ${response.status}.`,
      response.status,
      payload?.code || "API_ERROR",
      payload?.details,
    );
  }
  return readResponse<T>(response);
}

export const apiClient = {
  get: <T>(path: string, options?: RequestOptions) => request<T>("GET", path, undefined, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>("POST", path, body, options),
};
