import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { authApi } from "../services/authApi";
import type { User } from "../types/user";
import {
  AUTH_SESSION_EXPIRED_EVENT,
  clearAuthTokens,
  getAuthTokens,
  setAuthTokens,
} from "../utils/apiClient";

interface AuthContextValue {
  user: User | null;
  isAuthenticated: boolean;
  login(email: string, password: string): Promise<void>;
  signup(email: string, password: string): Promise<User>;
  logout(): Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    const onSessionExpired = () => setUser(null);
    window.addEventListener(AUTH_SESSION_EXPIRED_EVENT, onSessionExpired);
    return () => window.removeEventListener(AUTH_SESSION_EXPIRED_EVENT, onSessionExpired);
  }, []);

  const value = useMemo<AuthContextValue>(() => ({
    user,
    isAuthenticated: user !== null && getAuthTokens() !== null,
    async login(email, password) {
      const tokens = await authApi.login(email, password);
      setAuthTokens(tokens);
      try {
        setUser(await authApi.me());
      } catch (error) {
        clearAuthTokens();
        setUser(null);
        throw error;
      }
    },
    signup: (email, password) => authApi.signup({ email, password }),
    async logout() {
      const refreshToken = getAuthTokens()?.refresh_token;
      clearAuthTokens();
      setUser(null);
      if (refreshToken) {
        try {
          await authApi.logout(refreshToken);
        } catch {
          // Local logout remains complete if the Gateway cannot be reached.
        }
      }
    },
  }), [user]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider.");
  return context;
}
