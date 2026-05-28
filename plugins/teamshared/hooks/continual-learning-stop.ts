/// <reference types="bun-types-no-globals/lib/index.d.ts" />

import { existsSync, mkdirSync, readFileSync, renameSync, statSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { stdin } from "bun";

import {
  CADENCE_KEY,
  followupMessageForLocal,
  followupMessageForTeamshared,
  getTeamsharedState,
  loadTeamsharedConfig,
  setTeamsharedState,
  workspaceSlugFromPath,
} from "./teamshared-state.ts";

const DEFAULT_MIN_TURNS = 10;
const DEFAULT_MIN_MINUTES = 120;
const TRIAL_DEFAULT_MIN_TURNS = 3;
const TRIAL_DEFAULT_MIN_MINUTES = 15;
const TRIAL_DEFAULT_DURATION_MINUTES = 24 * 60;

interface StopHookInput {
  conversation_id: string;
  generation_id?: string;
  status: "completed" | "aborted" | "error" | string;
  loop_count: number;
  transcript_path?: string | null;
}

interface ContinuousLearningState {
  version: 1;
  lastRunAtMs: number;
  turnsSinceLastRun: number;
  lastTranscriptMtimeMs: number | null;
  lastProcessedGenerationId: string | null;
  trialStartedAtMs: number | null;
}

interface WorkspaceStatePaths {
  statePath: string;
  incrementalIndexPath: string;
  legacyStatePath: string;
  legacyIncrementalIndexPath: string;
}

interface StateBackend {
  kind: "teamshared" | "local";
  repo: string;
  loadCadence: () => Promise<ContinuousLearningState>;
  saveCadence: (state: ContinuousLearningState) => Promise<void>;
  followupMessage: () => string;
}

function getWorkspaceStatePaths(workspaceRoot: string): WorkspaceStatePaths {
  const slug = workspaceSlugFromPath(workspaceRoot);
  const stateDir = join(homedir(), ".cursor", "hooks", "state", "continual-learning", slug);
  return {
    statePath: join(stateDir, "continual-learning.json"),
    incrementalIndexPath: join(stateDir, "continual-learning-index.json"),
    legacyStatePath: resolve(workspaceRoot, ".cursor/hooks/state/continual-learning.json"),
    legacyIncrementalIndexPath: resolve(
      workspaceRoot,
      ".cursor/hooks/state/continual-learning-index.json"
    ),
  };
}

function migrateLegacyFile(legacyPath: string, targetPath: string): void {
  if (!existsSync(legacyPath) || existsSync(targetPath)) {
    return;
  }

  const directory = dirname(targetPath);
  if (!existsSync(directory)) {
    mkdirSync(directory, { recursive: true });
  }

  try {
    renameSync(legacyPath, targetPath);
  } catch {
    writeFileSync(targetPath, readFileSync(legacyPath, "utf-8"), "utf-8");
  }
}

function ensureStateMigrated(paths: WorkspaceStatePaths): void {
  migrateLegacyFile(paths.legacyStatePath, paths.statePath);
  migrateLegacyFile(paths.legacyIncrementalIndexPath, paths.incrementalIndexPath);
}

function defaultCadenceState(): ContinuousLearningState {
  return {
    version: 1,
    lastRunAtMs: 0,
    turnsSinceLastRun: 0,
    lastTranscriptMtimeMs: null,
    lastProcessedGenerationId: null,
    trialStartedAtMs: null,
  };
}

function parseCadenceState(raw: unknown): ContinuousLearningState {
  const fallback = defaultCadenceState();
  if (!raw || typeof raw !== "object") {
    return fallback;
  }
  const parsed = raw as Partial<ContinuousLearningState>;
  if (parsed.version !== 1) {
    return fallback;
  }
  return {
    version: 1,
    lastRunAtMs:
      typeof parsed.lastRunAtMs === "number" && Number.isFinite(parsed.lastRunAtMs)
        ? parsed.lastRunAtMs
        : 0,
    turnsSinceLastRun:
      typeof parsed.turnsSinceLastRun === "number" &&
      Number.isFinite(parsed.turnsSinceLastRun) &&
      parsed.turnsSinceLastRun >= 0
        ? parsed.turnsSinceLastRun
        : 0,
    lastTranscriptMtimeMs:
      typeof parsed.lastTranscriptMtimeMs === "number" &&
      Number.isFinite(parsed.lastTranscriptMtimeMs)
        ? parsed.lastTranscriptMtimeMs
        : null,
    lastProcessedGenerationId:
      typeof parsed.lastProcessedGenerationId === "string"
        ? parsed.lastProcessedGenerationId
        : null,
    trialStartedAtMs:
      typeof parsed.trialStartedAtMs === "number" && Number.isFinite(parsed.trialStartedAtMs)
        ? parsed.trialStartedAtMs
        : null,
  };
}

function loadLocalCadence(statePath: string): ContinuousLearningState {
  if (!existsSync(statePath)) {
    return defaultCadenceState();
  }
  try {
    return parseCadenceState(JSON.parse(readFileSync(statePath, "utf-8")));
  } catch {
    return defaultCadenceState();
  }
}

function saveLocalCadence(statePath: string, state: ContinuousLearningState): void {
  const directory = dirname(statePath);
  if (!existsSync(directory)) {
    mkdirSync(directory, { recursive: true });
  }
  writeFileSync(statePath, `${JSON.stringify(state, null, 2)}\n`, "utf-8");
}

async function resolveStateBackend(workspaceRoot: string): Promise<StateBackend> {
  const repo = workspaceSlugFromPath(workspaceRoot);
  const teamshared = loadTeamsharedConfig();
  if (teamshared) {
    return {
      kind: "teamshared",
      repo,
      loadCadence: async () => {
        const value = await getTeamsharedState(teamshared, repo, CADENCE_KEY);
        return parseCadenceState(value);
      },
      saveCadence: async (state) => {
        const ok = await setTeamsharedState(teamshared, repo, CADENCE_KEY, state);
        if (!ok) {
          throw new Error("teamshared state write failed");
        }
      },
      followupMessage: () => followupMessageForTeamshared(repo),
    };
  }

  const paths = getWorkspaceStatePaths(workspaceRoot);
  ensureStateMigrated(paths);
  return {
    kind: "local",
    repo,
    loadCadence: async () => loadLocalCadence(paths.statePath),
    saveCadence: async (state) => {
      saveLocalCadence(paths.statePath, state);
    },
    followupMessage: () => followupMessageForLocal(paths.incrementalIndexPath),
  };
}

function parsePositiveInt(value: string | undefined, fallback: number): number {
  if (!value) {
    return fallback;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }
  return parsed;
}

function parseBoolean(value: string | undefined): boolean {
  if (!value) {
    return false;
  }
  const normalized = value.trim().toLowerCase();
  return (
    normalized === "1" ||
    normalized === "true" ||
    normalized === "yes" ||
    normalized === "on"
  );
}

function readEnvValue(primary: string, legacy: string): string | undefined {
  return process.env[primary] ?? process.env[legacy];
}

function getTranscriptMtimeMs(transcriptPath: string | null | undefined): number | null {
  if (!transcriptPath) {
    return null;
  }

  try {
    return statSync(transcriptPath).mtimeMs;
  } catch {
    return null;
  }
}

function shouldCountTurn(input: StopHookInput): boolean {
  return input.status === "completed" && input.loop_count === 0;
}

async function parseHookInput<T>(): Promise<T> {
  const text = await stdin.text();
  return JSON.parse(text) as T;
}

async function main(): Promise<number> {
  try {
    const input = await parseHookInput<StopHookInput>();
    const backend = await resolveStateBackend(process.cwd());
    const state = await backend.loadCadence();

    if (input.generation_id && input.generation_id === state.lastProcessedGenerationId) {
      console.log(JSON.stringify({}));
      return 0;
    }
    state.lastProcessedGenerationId = input.generation_id ?? null;

    const countedTurn = shouldCountTurn(input);
    const turnIncrement = countedTurn ? 1 : 0;
    const turnsSinceLastRun = state.turnsSinceLastRun + turnIncrement;
    const now = Date.now();

    const trialEnabled = parseBoolean(
      readEnvValue("CONTINUAL_LEARNING_TRIAL_MODE", "CONTINUOUS_LEARNING_TRIAL_MODE")
    );
    if (trialEnabled && countedTurn && state.trialStartedAtMs === null) {
      state.trialStartedAtMs = now;
    }

    const trialDurationMinutes = parsePositiveInt(
      readEnvValue(
        "CONTINUAL_LEARNING_TRIAL_DURATION_MINUTES",
        "CONTINUOUS_LEARNING_TRIAL_DURATION_MINUTES"
      ),
      TRIAL_DEFAULT_DURATION_MINUTES
    );
    const trialMinTurns = parsePositiveInt(
      readEnvValue(
        "CONTINUAL_LEARNING_TRIAL_MIN_TURNS",
        "CONTINUOUS_LEARNING_TRIAL_MIN_TURNS"
      ),
      TRIAL_DEFAULT_MIN_TURNS
    );
    const trialMinMinutes = parsePositiveInt(
      readEnvValue(
        "CONTINUAL_LEARNING_TRIAL_MIN_MINUTES",
        "CONTINUOUS_LEARNING_TRIAL_MIN_MINUTES"
      ),
      TRIAL_DEFAULT_MIN_MINUTES
    );
    const inTrialWindow =
      trialEnabled &&
      state.trialStartedAtMs !== null &&
      now - state.trialStartedAtMs < trialDurationMinutes * 60_000;

    const minTurns = parsePositiveInt(
      readEnvValue("CONTINUAL_LEARNING_MIN_TURNS", "CONTINUOUS_LEARNING_MIN_TURNS"),
      DEFAULT_MIN_TURNS
    );
    const minMinutes = parsePositiveInt(
      readEnvValue("CONTINUAL_LEARNING_MIN_MINUTES", "CONTINUOUS_LEARNING_MIN_MINUTES"),
      DEFAULT_MIN_MINUTES
    );

    const effectiveMinTurns = inTrialWindow ? trialMinTurns : minTurns;
    const effectiveMinMinutes = inTrialWindow ? trialMinMinutes : minMinutes;
    const minutesSinceLastRun =
      state.lastRunAtMs > 0
        ? Math.floor((now - state.lastRunAtMs) / 60000)
        : Number.POSITIVE_INFINITY;
    const transcriptMtimeMs = getTranscriptMtimeMs(input.transcript_path);
    const hasTranscriptAdvanced =
      transcriptMtimeMs !== null &&
      (state.lastTranscriptMtimeMs === null || transcriptMtimeMs > state.lastTranscriptMtimeMs);

    const shouldTrigger =
      countedTurn &&
      turnsSinceLastRun >= effectiveMinTurns &&
      minutesSinceLastRun >= effectiveMinMinutes &&
      hasTranscriptAdvanced;

    if (shouldTrigger) {
      state.lastRunAtMs = now;
      state.turnsSinceLastRun = 0;
      state.lastTranscriptMtimeMs = transcriptMtimeMs;
      await backend.saveCadence(state);

      console.log(
        JSON.stringify({
          followup_message: backend.followupMessage(),
        })
      );
      return 0;
    }

    state.turnsSinceLastRun = turnsSinceLastRun;
    await backend.saveCadence(state);
    console.log(JSON.stringify({}));
    return 0;
  } catch (error) {
    console.error("[continual-learning-stop] failed", error);
    console.log(JSON.stringify({}));
    return 0;
  }
}

const exitCode = await main();
process.exit(exitCode);
