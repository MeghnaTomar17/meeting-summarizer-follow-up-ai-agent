/**
 * Purpose: Shared HTTP client (base URL, auth headers, error handling).
 * Future responsibilities: Interceptors, retry, correlation IDs.
 * Service ownership: Frontend.
 */

// TODO: Implement apiClient wrapper

export const apiClient = {
  get: async (_path: string): Promise<unknown> => {
    throw new Error("Not implemented");
  },
  post: async (_path: string, _body: unknown): Promise<unknown> => {
    throw new Error("Not implemented");
  },
};
