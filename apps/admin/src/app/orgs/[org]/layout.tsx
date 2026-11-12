"use client";

import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { Alert, Button, Loading, Select } from "@/components/ui";
import { allauth } from "@/lib/allauth";
import { can } from "@/lib/perms";
import { SessionProvider, useOrg, useSession } from "@/lib/session";

function Shell({ children }: { children: ReactNode }) {
  const { org: slug } = useParams<{ org: string }>();
  const pathname = usePathname();
  const router = useRouter();
  const me = useSession();
  const org = useOrg(slug);

  if (me.loading && !me.data) return <main className="p-8"><Loading /></main>;
  if (!me.data) return null; // redirecting to login
  if (!org || org.status !== "active") {
    return <main className="mx-auto max-w-xl p-8"><Alert>Organization not found.</Alert></main>;
  }

  const links = [
    { href: `/orgs/${slug}`, label: "Sites", show: true },
    { href: `/orgs/${slug}/members`, label: "Members", show: can(org, "members.view") },
    { href: `/orgs/${slug}/invitations`, label: "Invitations", show: can(org, "members.view") },
    { href: `/orgs/${slug}/payments`, label: "Payments", show: can(org, "payments.manage") },
  ].filter((link) => link.show);
  const active = me.data.organizations.filter((item) => item.status === "active");

  return (
    <div className="min-h-screen">
      <header className="border-b border-zinc-200 bg-white">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-4 px-6 py-3">
          <Select
            aria-label="Organization"
            value={slug}
            onChange={(event) => router.push(`/orgs/${event.target.value}`)}
          >
            {active.map((item) => <option key={item.id} value={item.slug}>{item.name}</option>)}
          </Select>
          <nav className="flex gap-1">
            {links.map((link) => {
              const current = link.href === `/orgs/${slug}` ? pathname === link.href || pathname.startsWith(`${link.href}/sites`) : pathname.startsWith(link.href);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`rounded-md px-3 py-1.5 text-sm ${current ? "bg-zinc-900 text-white" : "text-zinc-700 hover:bg-zinc-100"}`}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm text-zinc-600">
            <span>{me.data.email}{org.org_role ? ` · ${org.org_role}` : ""}</span>
            <Button
              variant="secondary"
              onClick={async () => {
                await allauth.logout();
                router.replace("/login");
              }}
            >
              Sign out
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-8">{children}</main>
    </div>
  );
}

export default function OrgLayout({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <Shell>{children}</Shell>
    </SessionProvider>
  );
}
