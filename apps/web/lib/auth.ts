"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { User } from "@/lib/api";

const KEY = "mg.session";

interface Session {
  token: string;
  user: User;
}

export function getSession(): Session | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(KEY);
  return raw ? (JSON.parse(raw) as Session) : null;
}

export function getToken(): string | null {
  return getSession()?.token ?? null;
}

export function setSession(token: string, user: User) {
  localStorage.setItem(KEY, JSON.stringify({ token, user }));
}

export function clearSession() {
  if (typeof window !== "undefined") localStorage.removeItem(KEY);
}

/** Reads the logged-in user; redirects to /login when absent (if `guard`). */
export function useUser(guard = true): User | null {
  const router = useRouter();
  const [user, setU] = useState<User | null>(null);

  useEffect(() => {
    const s = getSession();
    setU(s?.user ?? null);
    if (guard && !s) router.replace("/login");
  }, [guard, router]);

  return user;
}
