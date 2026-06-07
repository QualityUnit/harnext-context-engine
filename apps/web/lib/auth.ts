"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { User } from "@/lib/api";

const KEY = "mg.user";

export function getUser(): User | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(KEY);
  return raw ? (JSON.parse(raw) as User) : null;
}

export function setUser(user: User) {
  localStorage.setItem(KEY, JSON.stringify(user));
}

export function clearUser() {
  localStorage.removeItem(KEY);
}

/** Reads the logged-in user; redirects to /login when absent (if `guard`). */
export function useUser(guard = true): User | null {
  const router = useRouter();
  const [user, setU] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const u = getUser();
    setU(u);
    setReady(true);
    if (guard && !u) router.replace("/login");
  }, [guard, router]);

  return ready ? user : null;
}
