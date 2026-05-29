/// <reference types="bun-types-no-globals/lib/index.d.ts" />

import { existsSync, readFileSync } from "node:fs";
import { stdin } from "bun";

import {
  CONVERSATION_OFFSETS_KEY,
  type ConversationTurn,
  getTeamsharedState,
  loadTeamsharedConfig,
  postSessionTurns,
  setTeamsharedState,
  workspaceSlugFromPath,
} from "./teamshared-state.ts";

// Cap each turn so a single huge message can't bloat Redis working memory.
const MAX_TURN_CHARS = 8000;
// Keep the per-conversation offset map bounded.
const MAX_TRACKED_CONVERSATIONS = 50;

interface StopHookInput {
  conversation_id: string;
  transcript_path?: string | null;
  status?: string;
}

interface TranscriptLine {
  role?: string;
  message?: { content?: Array<{ type?: string; text?: string }> };
}

function clampText(text: string): string {
  const trimmed = text.trim();
  if (trimmed.length <= MAX_TURN_CHARS) {
    return trimmed;
  }
  return `${trimmed.slice(0, MAX_TURN_CHARS - 1)}\u2026`;
}

/** Pull the user's actual question out of Cursor's wrapped user message. */
function cleanUserText(text: string): string {
  const match = text.match(/<user_query>\s*([\s\S]*?)\s*<\/user_query>/);
  if (match) {
    return match[1].trim();
  }
  return text.trim();
}

function extractTurn(line: TranscriptLine): ConversationTurn | null {
  const role = line.role;
  if (role !== "user" && role !== "assistant") {
    return null;
  }
  const blocks = line.message?.content;
  if (!Array.isArray(blocks)) {
    return null;
  }
  const text = blocks
    .filter((b) => b?.type === "text" && typeof b.text === "string")
    .map((b) => b.text as string)
    .join("\n")
    .trim();
  if (!text) {
    return null;
  }
  const content = role === "user" ? cleanUserText(text) : text;
  if (!content) {
    return null;
  }
  return { role, content: clampText(content) };
}

function readNewTurns(
  transcriptPath: string,
  alreadyIngested: number
): { turns: ConversationTurn[]; totalLines: number } {
  const raw = readFileSync(transcriptPath, "utf-8");
  const lines = raw.split("\n").filter((l) => l.trim().length > 0);
  const turns: ConversationTurn[] = [];
  for (const line of lines.slice(alreadyIngested)) {
    let parsed: TranscriptLine;
    try {
      parsed = JSON.parse(line) as TranscriptLine;
    } catch {
      continue;
    }
    const turn = extractTurn(parsed);
    if (turn) {
      turns.push(turn);
    }
  }
  return { turns, totalLines: lines.length };
}

function pruneOffsets(offsets: Record<string, number>): Record<string, number> {
  const keys = Object.keys(offsets);
  if (keys.length <= MAX_TRACKED_CONVERSATIONS) {
    return offsets;
  }
  const trimmed: Record<string, number> = {};
  for (const key of keys.slice(keys.length - MAX_TRACKED_CONVERSATIONS)) {
    trimmed[key] = offsets[key];
  }
  return trimmed;
}

async function parseHookInput(): Promise<StopHookInput> {
  const text = await stdin.text();
  return JSON.parse(text) as StopHookInput;
}

async function main(): Promise<number> {
  try {
    const input = await parseHookInput();
    const transcriptPath = input.transcript_path;
    if (!transcriptPath || !existsSync(transcriptPath)) {
      console.log(JSON.stringify({}));
      return 0;
    }

    // NL conversation lives only in the client transcript, so capture requires
    // the teamshared REST config; there is no local-only fallback sink.
    const config = loadTeamsharedConfig();
    if (!config) {
      console.log(JSON.stringify({}));
      return 0;
    }

    const repo = workspaceSlugFromPath(process.cwd());
    const stored = (await getTeamsharedState(config, repo, CONVERSATION_OFFSETS_KEY)) ?? {};
    const offsets = stored as Record<string, number>;
    const conversationId = input.conversation_id;
    const alreadyIngested =
      typeof offsets[conversationId] === "number" ? offsets[conversationId] : 0;

    const { turns, totalLines } = readNewTurns(transcriptPath, alreadyIngested);
    if (totalLines <= alreadyIngested) {
      console.log(JSON.stringify({}));
      return 0;
    }

    let posted = true;
    if (turns.length > 0) {
      posted = await postSessionTurns(config, turns);
    }

    // Only advance the offset if the post succeeded, so a transient failure
    // re-sends those turns next stop rather than dropping them.
    if (posted) {
      offsets[conversationId] = totalLines;
      await setTeamsharedState(config, repo, CONVERSATION_OFFSETS_KEY, pruneOffsets(offsets));
    }

    console.log(JSON.stringify({}));
    return 0;
  } catch (error) {
    console.error("[conversation-capture-stop] failed", error);
    console.log(JSON.stringify({}));
    return 0;
  }
}

const exitCode = await main();
process.exit(exitCode);
