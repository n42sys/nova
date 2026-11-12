"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Alert, Card, Loading, StatusBadge } from "@/components/ui";
import { SessionProvider, useSession } from "@/lib/session";

function Home() {
  const { data: me, loading } = useSession();
  const router = useRouter();
  const active = me?.organizations.filter((org) => org.status === "active") ?? [];

  useEffect(() => {
    if (me && active.length === 1) router.replace(`/orgs/${active[0]!.slug}`);
  }, [me, active, router]);

  if (loading || !me) return <Loading />;
  return (
    <Card title="Your organizations">
      {me.organizations.length === 0 ? (
        <Alert kind="info">You are not a member of any organization yet. Ask for an invitation.</Alert>
      ) : (
        <ul className="divide-y divide-zinc-100">
          {me.organizations.map((org) => (
            <li key={org.id} className="flex items-center justify-between py-2">
              {org.status === "active" ? (
                <Link className="font-medium hover:underline" href={`/orgs/${org.slug}`}>
                  {org.name}
                </Link>
              ) : (
                <span className="text-zinc-500">{org.name}</span>
              )}
              <StatusBadge value={org.status} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export default function Page() {
  return (
    <main className="mx-auto max-w-xl p-8">
      <SessionProvider>
        <Home />
      </SessionProvider>
    </main>
  );
}
