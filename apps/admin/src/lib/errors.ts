type ErrorBody = { error?: { code?: string; message?: string; details?: unknown } };

/** A readable message from an API error body (`{"error": {"code", "message", "details"}}`). */
export function errorMessage(error: unknown, fallback = "Something went wrong."): string {
  const body = error as ErrorBody | undefined;
  const message = body?.error?.message;
  const details = body?.error?.details;
  if (message && details && typeof details === "object" && !Array.isArray(details)) {
    const fields = Object.entries(details as Record<string, unknown>)
      .filter(([, value]) => Array.isArray(value))
      .map(([field, value]) => `${field}: ${(value as unknown[]).join(", ")}`);
    if (fields.length && body?.error?.code === "validation_failed") {
      return `${message} (${fields.join("; ")})`;
    }
  }
  return message ?? fallback;
}
