"use client";

import { useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" }) {
  const styles = {
    primary: "bg-zinc-900 text-white hover:bg-zinc-700",
    secondary: "border border-zinc-300 bg-white text-zinc-900 hover:bg-zinc-50",
    danger: "border border-red-300 bg-white text-red-700 hover:bg-red-50",
  }[variant];
  return (
    <button
      className={`rounded-md px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
      {...props}
    />
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className="w-full rounded-md border border-zinc-300 px-2.5 py-1.5 text-sm focus:border-zinc-500 focus:outline-none disabled:bg-zinc-100"
      {...props}
    />
  );
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm disabled:bg-zinc-100"
      {...props}
    />
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block space-y-1">
      <span className="text-sm font-medium text-zinc-700">{label}</span>
      {children}
      {hint ? <span className="block text-xs text-zinc-500">{hint}</span> : null}
    </label>
  );
}

export function Card({ title, children, actions }: { title?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm">
      {title || actions ? (
        <div className="mb-4 flex items-center justify-between gap-4">
          {title ? <h2 className="text-base font-semibold">{title}</h2> : <span />}
          {actions}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function Alert({ kind = "error", children }: { kind?: "error" | "info" | "success"; children: ReactNode }) {
  const styles = {
    error: "border-red-200 bg-red-50 text-red-800",
    info: "border-zinc-200 bg-zinc-50 text-zinc-700",
    success: "border-green-200 bg-green-50 text-green-800",
  }[kind];
  return <div role={kind === "error" ? "alert" : "status"} className={`rounded-md border px-3 py-2 text-sm ${styles}`}>{children}</div>;
}

export function PageHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <header className="mb-6">
      <h1 className="text-xl font-semibold">{title}</h1>
      {subtitle ? <p className="mt-1 text-sm text-zinc-500">{subtitle}</p> : null}
    </header>
  );
}

export function Loading() {
  return <p className="text-sm text-zinc-500">Loading…</p>;
}

export function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      type="button"
      variant="secondary"
      onClick={async () => {
        await navigator.clipboard.writeText(value);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
    >
      {copied ? "Copied" : "Copy"}
    </Button>
  );
}

export function StatusBadge({ value }: { value: string }) {
  const tone =
    value === "active" || value === "verified" || value === "open" || value === "ready"
      ? "bg-green-100 text-green-800"
      : value === "pending"
        ? "bg-amber-100 text-amber-800"
        : "bg-zinc-100 text-zinc-600";
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>{value}</span>;
}
