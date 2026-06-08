import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";

export const CADENCE_KEY = "continual-learning/cadence";
export const INDEX_KEY = "continual-learning/index";

const MCP_SERVER_NAMES = ["teamshared"] as const;

export interface TeamsharedConfig {
  baseUrl: string;
  token: string;
}

export function workspaceSlugFromPath(workspaceRoot: string): string {
  return resolve(workspaceRoot).replace(/^\/+/, "").replace(/\//g, "-");
}

function normalizeBaseUrl(url: string): string {
  return url.replace(/\/mcp\/?$/, "").replace(/\/$/, "");
}

function findMcpServer(
  servers: Record<string, { url?: string; headers?: Record<string, string> }> | undefined
): { url?: string; headers?: Record<string, string> } | null {
  if (!servers) {
    return null;
  }
  for (const name of MCP_SERVER_NAMES) {
    const server = servers[name];
    if (server?.url) {
      return server;
    }
  }
  return null;
}

export function loadTeamsharedConfig(): TeamsharedConfig | null {
  const envUrl = process.env.TEAMSHARED_STATE_URL ?? process.env.TEAMSHARED_URL;
  const envToken = process.env.TEAMSHARED_STATE_TOKEN ?? process.env.TEAMSHARED_TOKEN;
  if (envUrl && envToken) {
    return { baseUrl: normalizeBaseUrl(envUrl), token: envToken };
  }

  const mcpPath = join(homedir(), ".cursor", "mcp.json");
  if (!existsSync(mcpPath)) {
    return null;
  }

  try {
    const raw = JSON.parse(readFileSync(mcpPath, "utf-8")) as {
      mcpServers?: Record<string, { url?: string; headers?: Record<string, string> }>;
    };
    const server = findMcpServer(raw.mcpServers);
    if (!server?.url) {
      return null;
    }
    const auth = server.headers?.Authorization ?? server.headers?.authorization;
    const token = auth?.replace(/^Bearer\s+/i, "").trim();
    if (!token) {
      return null;
    }
    return { baseUrl: normalizeBaseUrl(server.url), token };
  } catch {
    return null;
  }
}

export async function getTeamsharedState(
  config: TeamsharedConfig,
  repo: string,
  key: string
): Promise<Record<string, unknown> | null> {
  const params = new URLSearchParams({ repo, key });
  const response = await fetch(`${config.baseUrl}/state?${params}`, {
    headers: { Authorization: `Bearer ${config.token}` },
  });
  if (!response.ok) {
    return null;
  }
  const body = (await response.json()) as { value?: Record<string, unknown> | null };
  return body.value ?? null;
}

export async function setTeamsharedState(
  config: TeamsharedConfig,
  repo: string,
  key: string,
  value: Record<string, unknown>
): Promise<boolean> {
  const response = await fetch(`${config.baseUrl}/state`, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${config.token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ repo, key, value }),
  });
  return response.ok;
}

export function followupMessageForTeamshared(repo: string): string {
  return (
    `Run the \`continual-learning\` skill now. Use the \`agents-memory-updater\` subagent for the full memory update flow. Store incremental transcript state in teamshared via \`memory_state_get\` / \`memory_state_set\` with repo \`${repo}\` and index key \`${INDEX_KEY}\` (token+repo scoped). Only consider transcripts not in the index or transcripts whose mtime is newer than indexed mtime. Have the subagent refresh index mtimes, remove entries for deleted transcripts, and update \`AGENTS.md\` only for high-signal recurring user corrections and durable workspace facts. Exclude one-off/transient details and secrets. If no meaningful updates exist, respond exactly: No high-signal memory updates.`
  );
}

export function followupMessageForLocal(indexPath: string): string {
  return (
    `Run the \`continual-learning\` skill now. Use the \`agents-memory-updater\` subagent for the full memory update flow. Use incremental transcript processing with index file \`${indexPath}\`: only consider transcripts not in the index or transcripts whose mtime is newer than indexed mtime. Have the subagent refresh index mtimes, remove entries for deleted transcripts, and update \`AGENTS.md\` only for high-signal recurring user corrections and durable workspace facts. Exclude one-off/transient details and secrets. If no meaningful updates exist, respond exactly: No high-signal memory updates.`
  );
}
