import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../../context/AuthContext";
import { authApi } from "../../services/authApi";
import AuthPage from "./index";
import { ProtectedLayout } from "../../routes";
import { clearAuthTokens } from "../../utils/apiClient";

vi.mock("../../services/authApi", () => ({
  authApi: {
    login: vi.fn(),
    signup: vi.fn(),
    me: vi.fn(),
    logout: vi.fn(),
  },
}));

const mockedAuthApi = vi.mocked(authApi);
const userProfile = { id: "user-1", email: "person@example.com", created_at: "2026-01-01T00:00:00Z" };

function renderAt(path: string) {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes>
          <Route path="/login" element={<AuthPage mode="login" />} />
          <Route path="/signup" element={<AuthPage mode="signup" />} />
          <Route element={<ProtectedLayout />}>
            <Route path="/dashboard" element={<h1>Protected dashboard</h1>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  clearAuthTokens();
});

describe("authentication pages and routing", () => {
  it("validates login fields before making a request", async () => {
    const user = userEvent.setup();
    renderAt("/login");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("valid email");
    expect(mockedAuthApi.login).not.toHaveBeenCalled();
  });

  it("submits the actual login contract and enters the protected shell", async () => {
    const user = userEvent.setup();
    mockedAuthApi.login.mockResolvedValue({ access_token: "access", refresh_token: "refresh", token_type: "bearer" });
    mockedAuthApi.me.mockResolvedValue(userProfile);
    renderAt("/login");
    await user.type(screen.getByLabelText("Email"), "person@example.com");
    await user.type(screen.getByLabelText("Password"), "passphrase");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Protected dashboard" })).toBeInTheDocument();
    expect(mockedAuthApi.login).toHaveBeenCalledWith("person@example.com", "passphrase");
    expect(mockedAuthApi.me).toHaveBeenCalledOnce();
  });

  it("shows loading state and the Gateway authentication error", async () => {
    const user = userEvent.setup();
    let rejectLogin!: (error: Error) => void;
    mockedAuthApi.login.mockImplementation(() => new Promise((_resolve, reject) => { rejectLogin = reject; }));
    renderAt("/login");
    await user.type(screen.getByLabelText("Email"), "person@example.com");
    await user.type(screen.getByLabelText("Password"), "bad-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(screen.getByRole("button", { name: "Please wait…" })).toBeDisabled();
    rejectLogin(new Error("Invalid email or password."));
    expect(await screen.findByRole("alert")).toHaveTextContent("Authentication failed");
  });

  it("enforces the signup password minimum and submits only supported fields", async () => {
    const user = userEvent.setup();
    mockedAuthApi.signup.mockResolvedValue(userProfile);
    renderAt("/signup");
    await user.type(screen.getByLabelText("Email"), "new@example.com");
    await user.type(screen.getByLabelText("Password"), "short");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("at least 8 characters");
    expect(mockedAuthApi.signup).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText("Password"));
    await user.type(screen.getByLabelText("Password"), "long-enough-password");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Account created");
    expect(mockedAuthApi.signup).toHaveBeenCalledWith({ email: "new@example.com", password: "long-enough-password" });
    expect(mockedAuthApi.login).not.toHaveBeenCalled();
  });

  it("provides navigation between signup and login", async () => {
    const user = userEvent.setup();
    renderAt("/login");
    await user.click(screen.getByRole("link", { name: "Create an account" }));
    expect(await screen.findByRole("heading", { name: "Create your account" })).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
  });

  it("redirects protected pages to login and clears auth state on logout", async () => {
    const user = userEvent.setup();
    renderAt("/dashboard");
    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();

    mockedAuthApi.login.mockResolvedValue({ access_token: "access", refresh_token: "refresh", token_type: "bearer" });
    mockedAuthApi.me.mockResolvedValue(userProfile);
    await user.type(screen.getByLabelText("Email"), "person@example.com");
    await user.type(screen.getByLabelText("Password"), "passphrase");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Protected dashboard" })).toBeInTheDocument();

    mockedAuthApi.logout.mockResolvedValue({ success: true });
    await user.click(screen.getByRole("button", { name: "Log out" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Welcome back" })).toBeInTheDocument());
    expect(mockedAuthApi.logout).toHaveBeenCalledWith("refresh");
  });
});
