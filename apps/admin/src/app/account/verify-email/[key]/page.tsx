"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Alert, Card, Loading } from "@/components/ui";
import { allauth } from "@/lib/allauth";

/** Target of allauth's verification email link (HEADLESS_FRONTEND_URLS). */
export default function VerifyEmailPage() {
  const { key } = useParams<{ key: string }>();
  const [result, setResult] = useState<"ok" | "failed">();

  useEffect(() => {
    void allauth.verifyEmail(key).then((response) =>
      // 401 here means "verified, now sign in"; anything but 400/404/409 is success.
      setResult([400, 404, 409].includes(response.status) ? "failed" : "ok"),
    );
  }, [key]);

  return (
    <main className="mx-auto max-w-sm p-8">
      <Card title="Verify email">
        {!result ? <Loading /> : result === "ok" ? (
          <Alert kind="success">
            Your email is verified. <Link className="underline" href="/login">Sign in</Link>.
          </Alert>
        ) : (
          <Alert>This verification link is invalid or has expired.</Alert>
        )}
      </Card>
    </main>
  );
}
