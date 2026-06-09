/**
 * Purpose: HTTP client for authentication endpoints.
 * Future responsibilities: login, register, refresh, logout.
 * Service ownership: Frontend → gateway-service /auth.
 */

// TODO: Implement authApi with fetch/axios and token storage

export const authApi = {
  login: async (_email: string, _password: string): Promise<void> => {
    throw new Error("Not implemented");
  },
  register: async (_email: string, _password: string, _fullName?: string): Promise<void> => {
    throw new Error("Not implemented");
  },
  logout: async (): Promise<void> => {
    throw new Error("Not implemented");
  },
};
