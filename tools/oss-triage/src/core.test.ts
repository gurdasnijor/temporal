import assert from "node:assert/strict";
import { test } from "node:test";
import { parseCodeowners } from "./codeowners.ts";
import { CommitHistory } from "./history.ts";
import { mcnemar, crossFit, thresholdFor, wilson } from "./metrics.ts";
import { routeFiles } from "./route.ts";
import { fuse, issueQuery, keywords } from "./search.ts";
import type { Membership, Team } from "./teams.ts";
import { fixPr, truthFor, type ClosedIssue, type Pr, type TimelineItem } from "./truth.ts";

const OWNERS = `
*                @temporalio/server @temporalio/cgs @temporalio/nexus
/chasm/* @temporalio/oss-foundations
/chasm/lib/activity/ @temporalio/act
/service/matching/ @temporalio/oss-matching
/common/persistence/ @temporalio/oss-foundations @temporalio/oss-matching
/service/history/*chasm* @temporalio/oss-foundations
*.pb.go        @temporalio/server @temporalio/cgs
`;

test("codeowners: last match wins and the repo-wide rule is ignored", () => {
  const owners = parseCodeowners(OWNERS);
  assert.deepEqual(owners("service/matching/config.go"), ["oss-matching"]);
  assert.deepEqual(owners("chasm/lib/activity/x.go"), ["act"]);
  assert.deepEqual(owners("common/persistence/a/b.go"), ["oss-foundations", "oss-matching"]);
  assert.deepEqual(owners("service/history/engine.go"), []);
  assert.deepEqual(owners("service/history/chasm_engine.go"), ["oss-foundations"]);
});

test("codeowners: a rule on direct children does not reach nested files", () => {
  const owners = parseCodeowners(OWNERS);
  assert.deepEqual(owners("chasm/engine.go"), ["oss-foundations"]);
  assert.deepEqual(owners("chasm/other/engine.go"), []);
});

const membership: Membership = new Map<string, Set<Team>>([
  ["ann", new Set<Team>(["oss-matching"])],
  ["bob", new Set<Team>(["act"])],
  ["cam", new Set<Team>(["act", "nexus"])],
]);

const DAY = 24 * 3600 * 1000;
const NOW = Date.UTC(2026, 0, 1);

test("history: commits on or after the cutoff are invisible", () => {
  const history = new CommitHistory(
    [
      { at: NOW - 10 * DAY, login: "ann", files: ["a/x.go"] },
      { at: NOW + DAY, login: "bob", files: ["a/x.go"] },
    ],
    membership,
  );
  assert.equal(history.teamShares("a/x.go", NOW)?.["oss-matching"], 1);
  assert.equal(history.teamShares("a/x.go", NOW)?.act, 0);
});

test("history: commits older than a year fall out, and strangers stay in the denominator", () => {
  const history = new CommitHistory(
    [
      { at: NOW - 400 * DAY, login: "bob", files: ["a/x.go"] },
      { at: NOW - 2 * DAY, login: "ann", files: ["a/x.go"] },
      { at: NOW - DAY, login: "stranger", files: ["a/x.go"] },
    ],
    membership,
  );
  const shares = history.teamShares("a/x.go", NOW)!;
  assert.equal(shares["oss-matching"], 0.5);
  assert.equal(shares.act, 0);
});

test("history: a file with no commits falls back to its nearest folder", () => {
  const history = new CommitHistory([{ at: NOW - DAY, login: "ann", files: ["a/b/y.go"] }], membership);
  assert.equal(history.teamShares("a/b/new.go", NOW)?.["oss-matching"], 1);
  assert.equal(history.teamShares("z/new.go", NOW), undefined);
});

test("route: higher-ranked files outweigh lower ones and generated files are skipped", () => {
  const ownership = {
    codeowners: parseCodeowners("/m/ @temporalio/oss-matching\n/a/ @temporalio/act\n"),
    history: new CommitHistory([], membership),
  };
  const d = routeFiles(["x.pb.go", "m/1.go", "a/1.go"], NOW, ownership, "codeowners");
  assert.equal(d.team, "oss-matching");
  assert.equal(d.runnerUp, "act");
  assert.ok(Math.abs(d.scores["oss-matching"] - 2 / 3) < 1e-9);
});

test("route: no files gives a low-confidence decision, not a crash", () => {
  const ownership = { codeowners: parseCodeowners(""), history: new CommitHistory([], membership) };
  assert.equal(routeFiles([], NOW, ownership).confidence, "low");
});

test("search: fusion rewards chunks both lists agree on and returns each file once", () => {
  const files = fuse([
    [{ id: 1, path: "a.go" }, { id: 2, path: "b.go" }],
    [{ id: 2, path: "b.go" }, { id: 3, path: "a.go" }],
  ]);
  assert.deepEqual(files, ["b.go", "a.go"]);
});

test("search: query text drops comments and stopwords", () => {
  assert.equal(issueQuery({ title: "T", body: "<!-- hidden -->shown" }), "T\n\nshown");
  assert.equal(keywords("the matching service is down"), "matching service down");
});

const pr = (over: Partial<Pr>): Pr => ({
  number: 1,
  merged: true,
  author: { login: "ann" },
  baseRepository: { nameWithOwner: "temporalio/temporal" },
  latestReviews: { nodes: [] },
  ...over,
});

const issue = (...nodes: TimelineItem[]): ClosedIssue => ({
  number: 9,
  title: "t",
  body: null,
  createdAt: "2026-01-01T00:00:00Z",
  closedAt: "2026-02-01T00:00:00Z",
  labels: { nodes: [] },
  timelineItems: { nodes },
});

test("truth: a closing PR beats an earlier mention", () => {
  const found = fixPr(
    issue(
      { __typename: "CrossReferencedEvent", willCloseTarget: false, source: pr({ number: 1 }) },
      { __typename: "ClosedEvent", closer: { __typename: "PullRequest", ...pr({ number: 2 }) } },
    ),
  );
  assert.equal(found?.pr.number, 2);
  assert.equal(found?.link, "firm");
});

test("truth: unmerged and other-repo PRs don't count", () => {
  assert.equal(fixPr(issue({ __typename: "ConnectedEvent", subject: pr({ merged: false }) })), undefined);
  const elsewhere = pr({ baseRepository: { nameWithOwner: "temporalio/api" } });
  assert.equal(fixPr(issue({ __typename: "ConnectedEvent", subject: elsewhere })), undefined);
});

test("truth: closed by a commit uses that commit's PR", () => {
  const closer = { __typename: "Commit", associatedPullRequests: { nodes: [pr({ number: 7 })] } };
  assert.equal(fixPr(issue({ __typename: "ClosedEvent", closer }))?.pr.number, 7);
});

test("truth: author's team, then a single approving team, else nothing", () => {
  const closed = (p: Pr) => issue({ __typename: "ConnectedEvent", subject: p });
  assert.equal(truthFor(closed(pr({})), membership)?.team, "oss-matching");
  assert.equal(truthFor(closed(pr({ author: { login: "cam" } })), membership), undefined);
  const approved = (...logins: string[]) => ({
    nodes: logins.map((login) => ({ state: "APPROVED", author: { login } })),
  });
  const outsider = { author: { login: "stranger" } };
  const one = truthFor(closed(pr({ ...outsider, latestReviews: approved("bob") })), membership);
  assert.deepEqual([one?.team, one?.source], ["act", "approver"]);
  assert.equal(truthFor(closed(pr({ ...outsider, latestReviews: approved("ann", "bob") })), membership), undefined);
  assert.equal(truthFor(closed(pr(outsider)), membership), undefined);
});

test("metrics: wilson matches the figure quoted for 42 of 46", () => {
  const [low, high] = wilson(42, 46);
  assert.ok(Math.abs(low - 0.797) < 0.001 && Math.abs(high - 0.966) < 0.001);
});

test("metrics: threshold is the loosest margin that still meets the target", () => {
  const items = [
    ...Array.from({ length: 10 }, (_, i) => ({ margin: 0.9 - i / 100, correct: true })),
    { margin: 0.5, correct: false },
    { margin: 0.4, correct: false },
  ];
  assert.equal(thresholdFor(items, 0.9), 0.5);
  assert.equal(thresholdFor(items, 1), 0.81);
  assert.equal(thresholdFor([{ margin: 1, correct: true }], 0.9), Infinity);
});

test("metrics: cross-fitting scores every issue at most once", () => {
  const items = Array.from({ length: 100 }, (_, number) => ({ number, margin: number / 100, correct: number > 20 }));
  const held = crossFit(items, 0.95);
  assert.equal(held.total, 100);
  assert.ok(held.routed <= 100 && held.correct <= held.routed);
});

test("metrics: mcnemar matches the exact binomial", () => {
  assert.equal(mcnemar(5, 5), 1);
  assert.ok(Math.abs(mcnemar(10, 0) - 2 / 1024) < 1e-12);
  assert.ok(Math.abs(mcnemar(9, 1) - 22 / 1024) < 1e-12);
});
