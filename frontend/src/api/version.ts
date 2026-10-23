// Build identity of the running frontend, written to /version.json by the
// container at startup (generate-config.sh).
export interface VersionInfo {
  commit: string;
  version: string;
  built_at: string;
}

const FALLBACK: VersionInfo = { commit: "dev", version: "dev", built_at: "unknown" };

export async function fetchVersion(): Promise<VersionInfo> {
  try {
    const res = await fetch("/version.json", { cache: "no-store" });
    if (!res.ok) return FALLBACK;
    const data = await res.json();
    return {
      commit: data.commit || FALLBACK.commit,
      version: data.version || FALLBACK.version,
      built_at: data.built_at || FALLBACK.built_at,
    };
  } catch {
    return FALLBACK;
  }
}

export function formatFooterVersion(info: VersionInfo = FALLBACK): string {
  return `${info.version} · ${info.commit.slice(0, 8)}`;
}
