import { dirname } from "node:path";
import { TEAMS, teamsOf, type Membership, type Team } from "./teams.ts";
import { isGenerated } from "./codeowners.ts";

export type Commit = { at: number; login: string | null; files: string[] };

const YEAR_MS = 365 * 24 * 3600 * 1000;

type Touch = { at: number; login: string | null };

/**
 * Who changed each file, and when. Every read takes a date, so the blind eval can ask what was
 * known when an issue was filed; the fix for that issue must not count as evidence for it.
 */
export class CommitHistory {
  #byFile = new Map<string, Touch[]>();
  #byDir = new Map<string, Touch[]>();
  #membership: Membership;

  constructor(commits: Commit[], membership: Membership) {
    this.#membership = membership;
    for (const { at, login, files } of [...commits].sort((a, b) => a.at - b.at)) {
      for (const file of files) {
        if (isGenerated(file)) continue;
        push(this.#byFile, file, { at, login });
        push(this.#byDir, dirname(file), { at, login });
      }
    }
  }

  /** Each team's share of the year's commits before `asOf`; other authors stay in the denominator. */
  teamShares(path: string, asOf: number): Record<Team, number> | undefined {
    let touches = inWindow(this.#byFile.get(path), asOf);
    for (let dir = dirname(path); touches.length === 0 && dir !== "."; dir = dirname(dir)) {
      touches = inWindow(this.#byDir.get(dir), asOf);
    }
    if (touches.length === 0) return undefined;
    const shares = Object.fromEntries(TEAMS.map((t) => [t, 0])) as Record<Team, number>;
    for (const { login } of touches) {
      const teams = teamsOf(this.#membership, login);
      for (const team of teams) shares[team] += 1 / teams.size / touches.length;
    }
    return shares;
  }
}

const push = (map: Map<string, Touch[]>, key: string, touch: Touch) => {
  const list = map.get(key);
  if (list) list.push(touch);
  else map.set(key, [touch]);
};

const inWindow = (touches: Touch[] | undefined, asOf: number): Touch[] =>
  (touches ?? []).filter(({ at }) => at < asOf && at >= asOf - YEAR_MS);
