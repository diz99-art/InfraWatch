export async function checkHealth(signal: AbortSignal): Promise<void> {
  const base = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
  const response = await fetch(`${base}/api/health`, { signal });
  if (!response.ok) throw new Error("Health request failed");
  const data: unknown = await response.json();
  if (
    !data ||
    typeof data !== "object" ||
    !("status" in data) ||
    data.status !== "ok" ||
    !("service" in data) ||
    data.service !== "InfraWatch"
  ) {
    throw new Error("Invalid health response");
  }
}
