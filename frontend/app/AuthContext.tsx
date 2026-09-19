"use client";

import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { apiFetch, apiUrl } from "./api";

export type Role = "admin" | "power_user" | "user";

export type CurrentUser = {
  id: string;
  username: string;
  role: Role;
};

type AuthContextValue = {
  currentUser: CurrentUser;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [checked, setChecked] = useState(false);
  const router = useRouter();

  const logout = useCallback(async () => {
    await apiFetch(`${apiUrl}/auth/logout`, { method: "POST" });
    setCurrentUser(null);
    router.replace("/login");
  }, [router]);

  useEffect(() => {
    let cancelled = false;
    apiFetch(`${apiUrl}/auth/me`)
      .then(async (response) => {
        if (cancelled) return;
        if (response.ok) {
          setCurrentUser(await response.json());
        } else {
          router.replace("/login");
        }
      })
      .catch(() => {
        if (!cancelled) router.replace("/login");
      })
      .finally(() => {
        if (!cancelled) setChecked(true);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!checked) {
    return <p className="status">Checking session…</p>;
  }
  if (!currentUser) {
    // Redirect already triggered above; render nothing while it happens.
    return null;
  }

  return (
    <AuthContext.Provider value={{ currentUser, logout }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
