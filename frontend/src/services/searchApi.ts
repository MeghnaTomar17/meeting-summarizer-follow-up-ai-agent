/**
 * Purpose: HTTP client for semantic search.
 * Future responsibilities: search query, filters, pagination.
 * Service ownership: Frontend → gateway-service /search.
 */

// TODO: Implement searchApi

export const searchApi = {
  search: async (_query: string): Promise<unknown[]> => {
    throw new Error("Not implemented");
  },
};
