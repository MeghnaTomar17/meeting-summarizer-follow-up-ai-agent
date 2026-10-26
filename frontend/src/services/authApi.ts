import { apiClient, type AuthTokens } from "../utils/apiClient";
import type { User } from "../types/user";

export interface SignupInput {
  email: string;
  password: string;
}

export const authApi = {
  login: (email: string, password: string) =>
    apiClient.post<AuthTokens>("/auth/login", { email, password }, { authenticated: false }),
  signup: (input: SignupInput) =>
    apiClient.post<User>("/auth/signup", input, { authenticated: false }),
  me: () => apiClient.get<User>("/auth/me"),
  logout: (refreshToken: string) =>
    apiClient.post<{ success: boolean }>(
      "/auth/logout",
      { refresh_token: refreshToken },
      { authenticated: false, retryOnUnauthorized: false },
    ),
};
