"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { setSession } from "@/lib/auth";

function Callback() {
  const router = useRouter();
  const search = useSearchParams();

  useEffect(() => {
    const token = search.get("token");
    if (!token) {
      router.replace("/login?error=no_token");
      return;
    }
    // store the token, then fetch the user with it
    setSession(token, { id: "", email: null, name: null, avatar_url: null, created_at: "" });
    api
      .me()
      .then((user) => {
        setSession(token, user);
        router.replace("/projects");
      })
      .catch(() => router.replace("/login?error=auth_failed"));
  }, [router, search]);

  return <p className="mt-16 text-center text-sm text-neutral-400">Signing you in…</p>;
}

export default function AuthCallbackPage() {
  return (
    <Suspense fallback={<p className="mt-16 text-center text-sm text-neutral-400">Signing you in…</p>}>
      <Callback />
    </Suspense>
  );
}
