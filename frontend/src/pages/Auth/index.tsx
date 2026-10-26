import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { ApiError } from "../../utils/apiClient";
import { useAuth } from "../../context/AuthContext";

export default function AuthPage({ mode }: { mode: "login" | "signup" }) {
  const isSignup = mode === "signup";
  const { isAuthenticated, login, signup } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  if (isAuthenticated) return <Navigate to="/dashboard" replace />;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSuccess("");
    const cleanEmail = email.trim();
    if (!cleanEmail || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanEmail)) {
      setError("Enter a valid email address.");
      return;
    }
    if (!password) {
      setError("Enter your password.");
      return;
    }
    if (isSignup && password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }

    setSubmitting(true);
    try {
      if (isSignup) {
        await signup(cleanEmail, password);
        setSuccess("Account created. Sign in with your new account.");
        setPassword("");
      } else {
        await login(cleanEmail, password);
        navigate("/dashboard", { replace: true });
      }
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Authentication failed. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="auth-title">
        <Link className="brand auth-brand" to="/login">MannerAI</Link>
        <p className="eyebrow">Meeting intelligence</p>
        <h1 id="auth-title">{isSignup ? "Create your account" : "Welcome back"}</h1>
        <p className="auth-description">{isSignup ? "Sign up to organize and explore your meetings." : "Sign in to continue to your workspace."}</p>
        <form onSubmit={(event) => void handleSubmit(event)} noValidate>
          <label htmlFor="email">Email</label>
          <input
            autoComplete="email"
            id="email"
            name="email"
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@example.com"
            required
            type="email"
            value={email}
          />
          <label htmlFor="password">Password</label>
          <input
            autoComplete={isSignup ? "new-password" : "current-password"}
            id="password"
            name="password"
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
          {isSignup && <p className="field-hint">Use at least 8 characters.</p>}
          {error && <p className="form-message form-error" role="alert">{error}</p>}
          {success && <p className="form-message form-success" role="status">{success}</p>}
          <button className="button button-primary submit-button" disabled={submitting} type="submit">
            {submitting ? "Please wait…" : isSignup ? "Create account" : "Sign in"}
          </button>
        </form>
        <p className="auth-switch">
          {isSignup ? "Already have an account? " : "New to MannerAI? "}
          <Link to={isSignup ? "/login" : "/signup"}>{isSignup ? "Sign in" : "Create an account"}</Link>
        </p>
      </section>
    </main>
  );
}
