"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, type ReactNode } from "react";

import { api, type Me } from "./api";
import { useResource, type Resource } from "./resource";

const SessionContext = createContext<Resource<Me> | null>(null);

/** Loads `/api/manage/me/`; sends anonymous visitors to the login page. */
export function SessionProvider({ children }: { children: ReactNode }) {
  const me = useResource(() => api.GET("/api/manage/me/"), []);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (me.status === 401) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [me.status, pathname, router]);

  return <SessionContext.Provider value={me}>{children}</SessionContext.Provider>;
}

export function useSession(): Resource<Me> {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <SessionProvider>");
  return value;
}

export function useOrg(slug: string) {
  const { data } = useSession();
  return data?.organizations.find((org) => org.slug === slug);
}
