export const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Drop-in replacement for `fetch` that always sends the session cookie
 * (needed because the frontend and backend are different origins -- same
 * host, different port) and redirects to /login on a 401 rather than
 * leaving every call site to notice and handle it individually.
 */
export async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(input, { ...init, credentials: "include" });
  if (response.status === 401 && typeof window !== "undefined") {
    if (window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
  }
  return response;
}

type PydanticError = { type?: string; loc?: (string | number)[]; msg?: string; ctx?: Record<string, unknown> };

// The field name a Pydantic error's `loc` points at, e.g. ["body", "password"] -> "password".
function fieldLabel(loc: (string | number)[] | undefined): string {
  const field = loc?.filter((part) => part !== "body").pop();
  if (typeof field !== "string") return "This field";
  return field.charAt(0).toUpperCase() + field.slice(1).replace(/_/g, " ");
}

// Rephrase common Pydantic validation errors in plain language; unrecognized
// error types fall back to Pydantic's own (still-readable) `msg`.
function humanize(error: PydanticError): string {
  const label = fieldLabel(error.loc);
  switch (error.type) {
    case "string_too_short":
      return `${label} must be at least ${error.ctx?.min_length} characters.`;
    case "string_too_long":
      return `${label} must be at most ${error.ctx?.max_length} characters.`;
    case "string_pattern_mismatch":
      return `${label} has an invalid format.`;
    case "missing":
      return `${label} is required.`;
    default:
      return error.msg ? `${label}: ${error.msg}` : `${label} is invalid.`;
  }
}

/**
 * FastAPI's `detail` field is a plain string for a handler-raised HTTPException,
 * but an array of Pydantic error objects ({type, loc, msg, ctx}) on a 422
 * request-validation failure. Normalize both into a plain-language string.
 */
export function errorMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = (detail as PydanticError[])
      .filter((item) => item && typeof item === "object")
      .map(humanize);
    if (msgs.length > 0) return msgs.join(" ");
  }
  return fallback;
}
