/** Origin of the Nova API, e.g. "https://api.example.com". Required in production builds. */
export const API_URL: string =
  process.env.NEXT_PUBLIC_API_URL ??
  (process.env.NODE_ENV === "production" ? "" : "http://localhost:8000");
