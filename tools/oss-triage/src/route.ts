import { isGenerated, type Codeowners } from "./codeowners.ts";
import type { CommitHistory } from "./history.ts";
import { TEAMS, type Team } from "./teams.ts";

/** Which ownership evidence to use for each file a search returned. */
export type Signal = "codeowners" | "history" | "both";

export type Ownership = { codeowners: Codeowners; history: CommitHistory };

export type Confidence = "high" | "medium" | "low";

export type Decision = {
  team: Team;
  runnerUp: Team;
  score: number;
  margin: number;
  confidence: Confidence;
  scores: Record<Team, number>;
};

const WEIGHTS = { codeowners: 0.4, history: 0.35 };

function fileScores(path: string, asOf: number, { codeowners, history }: Ownership, signal: Signal) {
  const owners = codeowners(path);
  const shares = history.teamShares(path, asOf);
  const weights =
    signal === "both"
      ? { owners: WEIGHTS.codeowners, history: WEIGHTS.history }
      : signal === "codeowners"
        ? { owners: 1, history: 0 }
        : { owners: 0, history: 1 };
  const total = weights.owners + weights.history;
  return (team: Team) =>
    (weights.owners * (owners.includes(team) ? 1 / owners.length : 0) +
      weights.history * (shares?.[team] ?? 0)) /
    total;
}

/** Scores teams from ranked files: a file's weight is 1/rank, so the best hits count most. */
export function routeFiles(
  rankedFiles: string[],
  asOf: number,
  ownership: Ownership,
  signal: Signal = "both",
  topK = 20,
  weightAt = (rank: number) => 1 / (rank + 1),
): Decision {
  const files = rankedFiles.filter((f) => !isGenerated(f)).slice(0, topK);
  const scores = Object.fromEntries(TEAMS.map((t) => [t, 0])) as Record<Team, number>;
  let totalWeight = 0;
  files.forEach((file, rank) => {
    const weight = weightAt(rank);
    const score = fileScores(file, asOf, ownership, signal);
    totalWeight += weight;
    for (const team of TEAMS) scores[team] += weight * score(team);
  });
  if (totalWeight > 0) for (const team of TEAMS) scores[team] /= totalWeight;
  const [team, runnerUp] = [...TEAMS].sort((a, b) => scores[b] - scores[a]) as [Team, Team];
  const score = scores[team];
  const margin = score - scores[runnerUp];
  return { team, runnerUp, score, margin, confidence: band(score, margin), scores };
}

/** The spike's issue bands, kept so results can be compared with PR #14. */
const band = (score: number, margin: number): Confidence =>
  score >= 0.35 && margin >= 0.12 ? "high" : score >= 0.22 && margin >= 0.06 ? "medium" : "low";
