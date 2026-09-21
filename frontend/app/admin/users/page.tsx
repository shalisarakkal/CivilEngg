"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";

import { apiFetch, apiUrl, errorMessage } from "../../api";
import { AuthProvider, useAuth } from "../../AuthContext";

type Role = "admin" | "power_user" | "user";
type ManagedUser = {
  id: string;
  username: string;
  email: string | null;
  role: Role;
  disabled_at: string | null;
};

function UsersAdminPage() {
  const { currentUser } = useAuth();
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [newUsername, setNewUsername] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmNewPassword, setConfirmNewPassword] = useState("");
  const [newRole, setNewRole] = useState<Role>("user");
  const [userPendingDelete, setUserPendingDelete] = useState<ManagedUser | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [userPendingPasswordReset, setUserPendingPasswordReset] = useState<ManagedUser | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [resetting, setResetting] = useState(false);
  const [userPendingEmailEdit, setUserPendingEmailEdit] = useState<ManagedUser | null>(null);
  const [editEmail, setEditEmail] = useState("");
  const [editingEmail, setEditingEmail] = useState(false);

  async function loadUsers() {
    const response = await apiFetch(`${apiUrl}/users`);
    if (response.ok) {
      setUsers(await response.json());
    }
  }

  useEffect(() => {
    let cancelled = false;
    apiFetch(`${apiUrl}/users`).then(async (response) => {
      if (cancelled) return;
      if (response.ok) setUsers(await response.json());
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setMessage(null);
    if (newPassword !== confirmNewPassword) {
      setMessage("New password and confirm password do not match.");
      return;
    }
    const response = await apiFetch(`${apiUrl}/users`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: newUsername,
        email: newEmail,
        password: newPassword,
        role: newRole,
      }),
    });
    if (response.ok) {
      setNewUsername("");
      setNewEmail("");
      setNewPassword("");
      setConfirmNewPassword("");
      setNewRole("user");
      await loadUsers();
    } else {
      const body = await response.json().catch(() => null);
      setMessage(errorMessage(body, "Could not create user."));
    }
  }

  async function toggleDisabled(user: ManagedUser) {
    setMessage(null);
    const response = await apiFetch(`${apiUrl}/users/${user.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ disabled: user.disabled_at === null }),
    });
    if (response.ok) {
      await loadUsers();
    } else {
      const body = await response.json().catch(() => null);
      setMessage(errorMessage(body, "Could not update user."));
    }
  }

  async function changeRole(user: ManagedUser, role: Role) {
    setMessage(null);
    const response = await apiFetch(`${apiUrl}/users/${user.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    });
    if (response.ok) {
      await loadUsers();
    } else {
      const body = await response.json().catch(() => null);
      setMessage(errorMessage(body, "Could not update user."));
    }
  }

  async function confirmDeleteUser() {
    if (!userPendingDelete) return;
    const user = userPendingDelete;
    setMessage(null);
    setDeleting(true);
    try {
      const response = await apiFetch(`${apiUrl}/users/${user.id}`, { method: "DELETE" });
      if (response.ok) {
        await loadUsers();
      } else {
        const body = await response.json().catch(() => null);
        setMessage(errorMessage(body, "Could not delete user."));
      }
    } finally {
      setDeleting(false);
      setUserPendingDelete(null);
    }
  }

  async function confirmEditEmail(event: FormEvent) {
    event.preventDefault();
    if (!userPendingEmailEdit) return;
    const user = userPendingEmailEdit;
    setMessage(null);
    setEditingEmail(true);
    try {
      const response = await apiFetch(`${apiUrl}/users/${user.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: editEmail }),
      });
      if (response.ok) {
        setUserPendingEmailEdit(null);
        setEditEmail("");
        await loadUsers();
      } else {
        const body = await response.json().catch(() => null);
        setMessage(errorMessage(body, "Could not update email."));
      }
    } finally {
      setEditingEmail(false);
    }
  }

  async function confirmResetPassword(event: FormEvent) {
    event.preventDefault();
    if (!userPendingPasswordReset) return;
    const user = userPendingPasswordReset;
    setMessage(null);
    setResetting(true);
    try {
      const response = await apiFetch(`${apiUrl}/users/${user.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: resetPassword }),
      });
      if (response.ok) {
        setUserPendingPasswordReset(null);
        setResetPassword("");
      } else {
        const body = await response.json().catch(() => null);
        setMessage(errorMessage(body, "Could not reset password."));
      }
    } finally {
      setResetting(false);
    }
  }

  if (currentUser.role !== "admin") {
    return (
      <main className="workspace">
        <p className="status status-error">Admin role required.</p>
      </main>
    );
  }

  return (
    <main className="workspace">
      <header className="topbar">
        <div>
          <p className="eyebrow">Civil engineering intelligence</p>
          <h1>Manage users</h1>
        </div>
        <div style={{ display: "flex", gap: 12 }}>
          <Link className="secondary-button" href="/account">
            Change password
          </Link>
          <Link className="secondary-button" href="/">
            Back to workspace
          </Link>
        </div>
      </header>
      {message && (
        <p className="status status-error" role="status">
          {message}
        </p>
      )}
      <form onSubmit={handleCreate} className="create-form">
        <label htmlFor="new-username">New user</label>
        <div className="input-row">
          <input
            id="new-username"
            placeholder="Username"
            value={newUsername}
            onChange={(event) => setNewUsername(event.target.value)}
            required
          />
          <input
            type="email"
            placeholder="Email"
            value={newEmail}
            onChange={(event) => setNewEmail(event.target.value)}
            required
          />
          <input
            type="password"
            placeholder="Password (min. 8 characters)"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            autoComplete="new-password"
            minLength={8}
            required
          />
          <input
            type="password"
            placeholder="Confirm password"
            value={confirmNewPassword}
            onChange={(event) => setConfirmNewPassword(event.target.value)}
            autoComplete="new-password"
            minLength={8}
            required
          />
          <select value={newRole} onChange={(event) => setNewRole(event.target.value as Role)}>
            <option value="user">User</option>
            <option value="power_user">Power User</option>
            <option value="admin">Admin</option>
          </select>
          <button type="submit">Create</button>
        </div>
      </form>
      <section className="project-list">
        {users.map((user) => (
          <div className="archive-row" key={user.id}>
            <div className="archive-row-top">
              <strong>{user.username}</strong>
              <small>{user.email ?? "no email on file"}</small>
              <small>{user.disabled_at ? "disabled" : "active"}</small>
            </div>
            <div className="input-row">
              <select
                value={user.role}
                onChange={(event) => void changeRole(user, event.target.value as Role)}
              >
                <option value="user">User</option>
                <option value="power_user">Power User</option>
                <option value="admin">Admin</option>
              </select>
              <button
                type="button"
                className={user.disabled_at ? "secondary-button" : "danger-button"}
                onClick={() => void toggleDisabled(user)}
              >
                {user.disabled_at ? "Enable" : "Disable"}
              </button>
              <button
                type="button"
                className="secondary-button"
                onClick={() => {
                  setUserPendingEmailEdit(user);
                  setEditEmail(user.email ?? "");
                }}
              >
                Edit email
              </button>
              <button
                type="button"
                className="secondary-button"
                onClick={() => {
                  setUserPendingPasswordReset(user);
                  setResetPassword("");
                }}
              >
                Reset password
              </button>
              <button type="button" className="danger-button" onClick={() => setUserPendingDelete(user)}>
                Delete
              </button>
            </div>
          </div>
        ))}
      </section>
      {userPendingEmailEdit && (
        <div className="modal-backdrop" role="presentation">
          <section
            className="confirm-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="email-edit-title"
          >
            <p className="eyebrow">Edit email</p>
            <h3 id="email-edit-title">Edit email for {userPendingEmailEdit.username}?</h3>
            <form onSubmit={confirmEditEmail}>
              <label htmlFor="edit-email">Email</label>
              <input
                id="edit-email"
                type="email"
                placeholder="Email"
                value={editEmail}
                onChange={(event) => setEditEmail(event.target.value)}
                required
                autoFocus
              />
              <div className="modal-actions">
                <button
                  type="button"
                  className="secondary-button"
                  disabled={editingEmail}
                  onClick={() => setUserPendingEmailEdit(null)}
                >
                  Cancel
                </button>
                <button type="submit" disabled={editingEmail}>
                  {editingEmail ? "Saving..." : "Save email"}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
      {userPendingPasswordReset && (
        <div className="modal-backdrop" role="presentation">
          <section
            className="confirm-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="password-reset-title"
          >
            <p className="eyebrow">Reset password</p>
            <h3 id="password-reset-title">Reset password for {userPendingPasswordReset.username}?</h3>
            <form onSubmit={confirmResetPassword}>
              <label htmlFor="reset-password">New password</label>
              <input
                id="reset-password"
                type="password"
                placeholder="New password (min. 8 characters)"
                value={resetPassword}
                onChange={(event) => setResetPassword(event.target.value)}
                minLength={8}
                required
                autoFocus
              />
              <div className="modal-actions">
                <button
                  type="button"
                  className="secondary-button"
                  disabled={resetting}
                  onClick={() => setUserPendingPasswordReset(null)}
                >
                  Cancel
                </button>
                <button type="submit" className="danger-button" disabled={resetting}>
                  {resetting ? "Resetting..." : "Reset password"}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
      {userPendingDelete && (
        <div className="modal-backdrop" role="presentation">
          <section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="user-delete-title">
            <p className="eyebrow">Delete user</p>
            <h3 id="user-delete-title">Delete {userPendingDelete.username}?</h3>
            <p className="muted">
              This permanently removes the account and cannot be undone. A user who still owns
              projects, or the last active admin, cannot be deleted.
            </p>
            <div className="modal-actions">
              <button className="secondary-button" disabled={deleting} onClick={() => setUserPendingDelete(null)}>
                Cancel
              </button>
              <button className="danger-button" disabled={deleting} onClick={() => void confirmDeleteUser()}>
                {deleting ? "Deleting..." : "Delete user"}
              </button>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

export default function UsersAdminRoute() {
  return (
    <AuthProvider>
      <UsersAdminPage />
    </AuthProvider>
  );
}
