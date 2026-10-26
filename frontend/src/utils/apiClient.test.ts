import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiClient, clearAuthTokens, getAuthTokens, setAuthTokens } from "./apiClient";

function response(status: number, body?: unknown, contentType = "application/json") {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { get: (name: string) => name.toLowerCase() === "content-type" ? contentType : null },
    json: async () => body,
    text: async () => typeof body === "string" ? body : "",
  } as Response;
}

beforeEach(() => {
  clearAuthTokens();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiClient", () => {
  it("converts the Gateway error envelope to a typed error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(401, {
      error: { code: "UNAUTHORIZED", message: "Invalid email or password.", request_id: "r1" },
    })));
    await expect(apiClient.post("/auth/login", { email: "a@example.com", password: "bad" }, { authenticated: false }))
      .rejects.toMatchObject({
        name: "ApiError",
        status: 401,
        code: "UNAUTHORIZED",
        message: "Invalid email or password.",
      });
  });

  it("reports network failures without exposing request data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("socket failed")));
    await expect(apiClient.get("/auth/me")).rejects.toBeInstanceOf(ApiError);
    await expect(apiClient.get("/auth/me")).rejects.toMatchObject({ status: 0, code: "NETWORK_ERROR" });
  });

  it("rotates an in-memory refresh token once after a 401 and retries the request", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(401, { error: { message: "Expired" } }))
      .mockResolvedValueOnce(response(200, { access_token: "new-access", refresh_token: "new-refresh", token_type: "bearer" }))
      .mockResolvedValueOnce(response(200, { id: "user-1" }));
    vi.stubGlobal("fetch", fetchMock);
    setAuthTokens({ access_token: "old-access", refresh_token: "old-refresh", token_type: "bearer" });

    await expect(apiClient.get("/auth/me")).resolves.toEqual({ id: "user-1" });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/auth/refresh");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ refresh_token: "old-refresh" });
    expect(fetchMock.mock.calls[2][1].headers.get("Authorization")).toBe("Bearer new-access");
  });

  it("clears the session and notifies auth state when refresh is rejected", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(401, { error: { message: "Expired" } }))
      .mockResolvedValueOnce(response(401, { error: { message: "Invalid refresh token." } }));
    vi.stubGlobal("fetch", fetchMock);
    setAuthTokens({ access_token: "expired-access", refresh_token: "revoked-refresh", token_type: "bearer" });
    const onExpired = vi.fn();
    window.addEventListener("meeting-agent:auth-session-expired", onExpired);

    try {
      await expect(apiClient.get("/auth/me")).rejects.toMatchObject({ status: 401 });
      expect(getAuthTokens()).toBeNull();
      expect(onExpired).toHaveBeenCalledOnce();
    } finally {
      window.removeEventListener("meeting-agent:auth-session-expired", onExpired);
    }
  });

  it("accepts a successful non-JSON response body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(200, "ok", "text/plain")));
    await expect(apiClient.get<string>("/health", { authenticated: false })).resolves.toBe("ok");
  });
});
