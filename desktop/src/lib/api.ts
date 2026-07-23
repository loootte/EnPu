/**
 * HTTP client for EnPu core (FastAPI).
 * Wired in issue #6; placeholder base URL for local dual-process dev.
 */

export const DEFAULT_CORE_BASE_URL = "http://127.0.0.1:8765";

export function getCoreBaseUrl(): string {
  // Vite env optional override for later.
  const fromEnv = import.meta.env.VITE_ENPU_CORE_URL as string | undefined;
  return (fromEnv && fromEnv.replace(/\/$/, "")) || DEFAULT_CORE_BASE_URL;
}

export async function healthCheck(
  baseUrl: string = getCoreBaseUrl(),
): Promise<{ status: string; version?: string; engine?: string }> {
  const res = await fetch(`${baseUrl}/health`);
  if (!res.ok) {
    throw new Error(`health failed: HTTP ${res.status}`);
  }
  return res.json() as Promise<{
    status: string;
    version?: string;
    engine?: string;
  }>;
}
