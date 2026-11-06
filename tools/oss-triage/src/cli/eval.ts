/**
 * Blind eval: can each approach name the team that fixed a closed issue, from the issue alone?
 *
 * Blind means: only the title and body, never comments or the PR; commit history stops at the day
 * the issue was filed. The code index is one snapshot of main, so it can still contain the fix.
 *
 * Needs TURBOPUFFER_API_KEY and `gh` auth. Reads only. Inputs are cached in .cache/.
 */
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { parseCodeowners } from "../codeowners.ts";
import { fetchClosedIssues, fetchCommitLogins, fetchMembership, fetchPrFiles, gitCommits, toMembership } from "../github.ts";
import { CommitHistory } from "../history.ts";
import { crossFit, mcnemar, wilson } from "../metrics.ts";
import { routeFiles, type Decision, type Ownership, type Signal } from "../route.ts";
import { issueQuery, METHODS, turbopufferSearch, type Hits, type Method } from "../search.ts";
import { TEAMS, type Team } from "../teams.ts";
import { truthFor, type ClosedIssue, type Truth } from "../truth.ts";

const CACHE = new URL("../../.cache/", import.meta.url).pathname;
const REPO_DIR = process.env.REPO_DIR ?? execFileSync("git", ["rev-parse", "--show-toplevel"], { encoding: "utf8" }).trim();
const REF = process.env.REPO_REF ?? "origin/main";
const NAMESPACE = process.env.CODE_NAMESPACE ?? "vault-code-temporal";
const TARGET = 0.95;
const SIGNALS: Signal[] = ["codeowners", "history", "both"];

mkdirSync(CACHE, { recursive: true });

async function cached<T>(name: string, build: () => Promise<T>): Promise<T> {
  const path = `${CACHE}${name}.json`;
  if (existsSync(path)) return JSON.parse(readFileSync(path, "utf8"));
  const value = await build();
  writeFileSync(path, JSON.stringify(value));
  return value;
}

const issues = await cached("closed-issues", () => fetchClosedIssues());
const membership = toMembership(await cached("membership", fetchMembership));
const logins = await cached("commit-logins", () => fetchCommitLogins("2019-01-01T00:00:00Z"));
const codeowners = parseCodeowners(execFileSync("git", ["-C", REPO_DIR, "show", `${REF}:.github/CODEOWNERS`], { encoding: "utf8" }));
const ownership: Ownership = { codeowners, history: new CommitHistory(gitCommits(REPO_DIR, REF, logins), membership) };

type Case = { issue: ClosedIssue; truth: Truth };
const cases: Case[] = issues.flatMap((issue) => {
  const truth = truthFor(issue, membership);
  return truth ? [{ issue, truth }] : [];
});

const hits = await cached<Record<number, Hits>>("hits", async () => {
  const search = turbopufferSearch(process.env.TURBOPUFFER_API_KEY!, NAMESPACE);
  const out: Record<number, Hits> = {};
  const queue = [...cases];
  await Promise.all(
    Array.from({ length: 8 }, async () => {
      for (let next = queue.shift(); next; next = queue.shift()) {
        out[next.issue.number] = await search(issueQuery(next.issue));
      }
    }),
  );
  return out;
});

type Row = { number: number; truth: Team; margin: number; correct: boolean; decision: Decision };

const score = (subset: Case[], method: Method, signal: Signal): Row[] =>
  subset.map(({ issue, truth }) => {
    const decision = routeFiles(hits[issue.number]![method], Date.parse(issue.createdAt), ownership, signal);
    return { number: issue.number, truth: truth.team, margin: decision.margin, correct: decision.team === truth.team, decision };
  });

const pct = (x: number) => `${(100 * x).toFixed(0)}%`;
const ratio = (k: number, n: number) => (n ? `${k}/${n} ${pct(k / n)}` : "0/0");
const interval = (k: number, n: number) => wilson(k, n).map(pct).join("–");

function report(title: string, subset: Case[]) {
  const byTeam = new Map(TEAMS.map((t) => [t, subset.filter((c) => c.truth.team === t).length]));
  const majority = Math.max(...byTeam.values());
  console.log(`\n## ${title}: ${subset.length} issues (${[...byTeam].map(([t, n]) => `${t} ${n}`).join(", ")})`);
  console.log(`always guessing the largest team: ${pct(majority / subset.length)}`);
  console.log("search    ownership   all right        high band        routed at 95% target (held out)");
  for (const method of METHODS) {
    for (const signal of SIGNALS) {
      const rows = score(subset, method, signal);
      const right = rows.filter((r) => r.correct).length;
      const high = rows.filter((r) => r.decision.confidence === "high");
      const held = crossFit(rows, TARGET);
      console.log(
        `${method.padEnd(9)} ${signal.padEnd(11)} ${ratio(right, rows.length).padEnd(16)} ` +
          `${ratio(high.filter((r) => r.correct).length, high.length).padEnd(16)} ` +
          `routes ${pct(held.routed / rows.length)}, ${ratio(held.correct, held.routed)} (${interval(held.correct, held.routed)})`,
      );
    }
  }
}

function perTeam(subset: Case[], method: Method, signal: Signal) {
  console.log(`\n## Per team, ${method} + ${signal}`);
  const rows = score(subset, method, signal);
  for (const team of TEAMS) {
    const actual = rows.filter((r) => r.truth === team);
    const predicted = rows.filter((r) => r.decision.team === team);
    console.log(
      `${team.padEnd(16)} found ${ratio(actual.filter((r) => r.correct).length, actual.length).padEnd(13)} ` +
        `when named, right ${ratio(predicted.filter((r) => r.correct).length, predicted.length)}`,
    );
  }
}

const labelled = (c: Case, ...names: string[]) => c.issue.labels.nodes.some((l) => names.includes(l.name));

console.log(`closed ${issues.length}, usable ${cases.length}, index ${NAMESPACE}, ownership at ${REF}`);
report("All usable", cases);
report("Firm link only", cases.filter((c) => c.truth.link === "firm"));
report("PR author only (no approver fallback)", cases.filter((c) => c.truth.source === "author"));
report("Filed since 2025", cases.filter((c) => c.issue.createdAt >= "2025"));
report("Feature requests", cases.filter((c) => labelled(c, "enhancement", "feature-request")));
report("Bugs", cases.filter((c) => labelled(c, "bug", "potential-bug")));
perTeam(cases, "hybrid", "both");
perTeam(cases, "voyage", "both");
perTeam(cases, "keyword", "both");

function paired(a: [Method, Signal], b: [Method, Signal]) {
  const [left, right] = [score(cases, ...a), score(cases, ...b)];
  const onlyA = left.filter((r, i) => r.correct && !right[i]!.correct).length;
  const onlyB = left.filter((r, i) => !r.correct && right[i]!.correct).length;
  console.log(`${a.join("+")} vs ${b.join("+")}: only first right ${onlyA}, only second ${onlyB}, p=${mcnemar(onlyA, onlyB).toFixed(3)}`);
}

console.log("\n## Paired, all usable");
paired(["voyage", "both"], ["keyword", "both"]);
paired(["voyage", "history"], ["keyword", "history"]);
paired(["hybrid", "both"], ["keyword", "both"]);
paired(["voyage", "history"], ["voyage", "both"]);

/** The ceiling: the same ownership step given the files the fix really changed, in place of a search. */
const prFiles = await cached("pr-files", () => fetchPrFiles([...new Set(cases.map((c) => c.truth.pr))]));
const fixFiles = (truth: Truth) => (prFiles[truth.pr] ?? []).filter((path) => !path.endsWith("_test.go"));

function ceiling(title: string, subset: Case[]) {
  console.log(`\n## Ceiling, ${title}: ${subset.length} issues, ownership step on the fix PR's own non-test files (not blind)`);
  for (const signal of SIGNALS) {
    const decisions = subset.map(({ issue, truth }) => ({
      truth: truth.team,
      decision: routeFiles(fixFiles(truth), Date.parse(issue.createdAt), ownership, signal, 100, () => 1),
    }));
    const right = decisions.filter((r) => r.decision.team === r.truth);
    const high = decisions.filter((r) => r.decision.confidence === "high");
    console.log(
      `${signal.padEnd(11)} ${ratio(right.length, decisions.length).padEnd(16)} ` +
        `high band ${ratio(high.filter((r) => r.decision.team === r.truth).length, high.length)}`,
    );
  }
}

ceiling("all usable", cases);
ceiling("filed since 2025", cases.filter((c) => c.issue.createdAt >= "2025"));
ceiling("firm link", cases.filter((c) => c.truth.link === "firm"));

/** Whether search found the fix at all: share of issues with a fix-PR file in the top 20 hits. */
const foundFix = (method: Method) =>
  cases.map(({ issue, truth }) => {
    const changed = new Set(prFiles[truth.pr] ?? []);
    return hits[issue.number]![method].slice(0, 20).some((path) => changed.has(path));
  });

console.log("\n## Search found a file the fix changed (top 20)");
for (const method of METHODS) console.log(`${method.padEnd(9)} ${ratio(foundFix(method).filter(Boolean).length, cases.length)}`);
const [voyageFound, keywordFound] = [foundFix("voyage"), foundFix("keyword")];
const onlyVoyage = voyageFound.filter((found, i) => found && !keywordFound[i]).length;
const onlyKeyword = keywordFound.filter((found, i) => found && !voyageFound[i]).length;
console.log(`voyage vs keyword: only voyage ${onlyVoyage}, only keyword ${onlyKeyword}, p=${mcnemar(onlyVoyage, onlyKeyword).toFixed(3)}`);

/** Issues the ownership step gets wrong even with the fix's own files: read these by hand. */
if (process.env.SHOW_MISSES) {
  console.log("\n## Misses with the fix's own files, newest first");
  const misses = cases
    .map(({ issue, truth }) => ({ issue, truth, decision: routeFiles(fixFiles(truth), Date.parse(issue.createdAt), ownership, "both", 100, () => 1) }))
    .filter(({ truth, decision }) => decision.team !== truth.team)
    .sort((a, b) => b.issue.createdAt.localeCompare(a.issue.createdAt));
  const pairs = new Map<string, number>();
  for (const { truth, decision } of misses) pairs.set(`${truth.team} named ${decision.team}`, (pairs.get(`${truth.team} named ${decision.team}`) ?? 0) + 1);
  console.log([...pairs].sort((a, b) => b[1] - a[1]).map(([k, v]) => `${v} ${k}`).join("\n"));
  for (const { issue, truth, decision } of misses.slice(0, Number(process.env.SHOW_MISSES))) {
    console.log(`#${issue.number} ${issue.createdAt.slice(0, 10)} ${issue.title.slice(0, 70)}`);
    console.log(`  fixed by ${truth.team} (${truth.source}, ${truth.link}, PR ${truth.pr}); named ${decision.team}; files ${fixFiles(truth).slice(0, 4).join(" ")}`);
  }
}
