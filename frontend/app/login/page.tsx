"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { apiUrl } from "../api";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiUrl}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email, password }),
      });
      if (response.ok) {
        router.replace("/");
      } else {
        setError("Invalid email or password.");
      }
    } catch {
      setError("Could not reach the server.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="workspace" style={{ maxWidth: 420, margin: "0 auto" }}>
      <p className="eyebrow">Civil Engineering Intelligence</p>
      <h1 style={{ marginBottom: 32 }}>Sign in</h1>
      <form onSubmit={handleSubmit} className="create-form">
        <label htmlFor="login-email">Email</label>
        <div className="input-row">
          <input
            id="login-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="email"
            required
          />
        </div>
        <label htmlFor="login-password">Password</label>
        <div className="input-row">
          <input
            id="login-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
          <button type="submit" disabled={loading}>
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </div>
      </form>
      {error && (
        <p className="status status-error" role="status" style={{ marginTop: 16 }}>
          {error}
        </p>
      )}
    </div>
  );
}
