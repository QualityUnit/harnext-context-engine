"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getUser, clearUser } from "@/lib/auth";
import type { User } from "@/lib/api";

export function NavBar() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  useEffect(() => setUser(getUser()), []);

  return (
    <header className="border-b border-neutral-800">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        <Link href="/projects" className="flex items-baseline gap-2">
          <span className="text-lg font-semibold tracking-tight">MeaningGrid</span>
          <span className="text-sm text-neutral-500">Context Engine</span>
        </Link>
        {user && (
          <div className="flex items-center gap-3 text-sm">
            <span className="text-neutral-400">@{user.username}</span>
            <button
              onClick={() => {
                clearUser();
                router.replace("/login");
              }}
              className="rounded-md border border-neutral-700 px-2.5 py-1 text-neutral-300 hover:bg-neutral-800"
            >
              Log out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
