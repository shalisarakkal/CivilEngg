"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";

import { apiFetch, apiUrl, errorMessage } from "../api";
import { AuthProvider, useAuth } from "../AuthContext";

function AccountPage() {
  const { currentUser } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setMessage(null);
    setSuccess(false);
    if (newPassword !== confirmPassword) {
      setMessage("New password and confirm password do not match.");
      return;
    }
    setSaving(true);
    try {
      const response = await apiFetch(`${apiUrl}/auth/password`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      if (response.ok) {
        setCurrentPassword("");
        setNewPassword("");
        setConfirmPassword("");
        setSuccess(true);
      } else {
        const body = await response.json().catch(() => null);
        setMessage(errorMessage(body, "Could not change password."));
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="workspace">
      <header className="topbar">
        <div>
          <p className="eyebrow">Civil engineering intelligence</p>
          <h1>My account</h1>
        </div>
        <Link className="secondary-button" href="/">
          Back to workspace
        </Link>
      </header>
      <p className="muted">
        Signed in as {currentUser.username} · {currentUser.role.replace("_", " ")}
      </p>
      {success && (
        <p className="status" role="status">
          Password changed.
        </p>
      )}
      {message && (
        <p className="status status-error" role="status">
          {message}
        </p>
      )}
      <form onSubmit={handleSubmit} className="create-form">
        <label htmlFor="current-password">Current password</label>
        <div className="input-row">
          <input
            id="current-password"
            type="password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </div>
        <label htmlFor="new-password">New password</label>
        <div className="input-row">
          <input
            id="new-password"
            type="password"
            placeholder="New password (min. 8 characters)"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            autoComplete="new-password"
            minLength={8}
            required
          />
        </div>
        <label htmlFor="confirm-password">Confirm password</label>
        <div className="input-row">
          <input
            id="confirm-password"
            type="password"
            placeholder="Re-enter new password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            autoComplete="new-password"
            minLength={8}
            required
          />
          <button type="submit" disabled={saving}>
            {saving ? "Changing..." : "Change password"}
          </button>
        </div>
      </form>
    </main>
  );
}

export default function AccountRoute() {
  return (
    <AuthProvider>
      <AccountPage />
    </AuthProvider>
  );
}
