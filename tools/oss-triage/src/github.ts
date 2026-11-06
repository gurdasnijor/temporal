import { execFileSync } from "node:child_process";
import { graphql as octokitGraphql } from "@octokit/graphql";
import { TEAMS, type Membership, type Team } from "./teams.ts";
import type { ClosedIssue } from "./truth.ts";
import type { Commit } from "./history.ts";
import type { IssueText } from "./search.ts";

const token = () => process.env.GITHUB_TOKEN ?? execFileSync("gh", ["auth", "token"], { encoding: "utf8" }).trim();

const client = () => octokitGraphql.defaults({ headers: { authorization: `token ${token()}` } });

const PR = `number merged author { login } baseRepository { nameWithOwner }
  latestReviews(first: 10) { nodes { state author { login } } }`;

const CLOSED_ISSUES = `query($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: 25, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on Issue {
      number title body createdAt closedAt
      labels(first: 15) { nodes { name } }
      timelineItems(itemTypes: [CLOSED_EVENT, CONNECTED_EVENT, CROSS_REFERENCED_EVENT], last: 15) { nodes {
        __typename
        ... on ClosedEvent { closer { __typename
          ... on PullRequest { ${PR} }
          ... on Commit { associatedPullRequests(first: 1) { nodes { ${PR} } } } } }
        ... on ConnectedEvent { subject { __typename ... on PullRequest { ${PR} } } }
        ... on CrossReferencedEvent { willCloseTarget source { __typename ... on PullRequest { ${PR} } } }
      } }
    } }
  }
}`;

type Page<T> = { pageInfo: { hasNextPage: boolean; endCursor: string | null }; nodes: T[] };

async function paginate<T>(page: (after: string | null) => Promise<Page<T>>): Promise<T[]> {
  const items: T[] = [];
  for (let after: string | null = null; ; ) {
    const { nodes, pageInfo }: Page<T> = await page(after);
    items.push(...nodes);
    if (!pageInfo.hasNextPage) return items;
    after = pageInfo.endCursor;
  }
}

/** Search returns at most 1,000 results, so this walks half-years. */
export async function fetchClosedIssues(fromYear = 2020, toYear = new Date().getUTCFullYear()): Promise<ClosedIssue[]> {
  const graphql = client();
  const issues: ClosedIssue[] = [];
  for (let year = fromYear; year <= toYear; year++) {
    for (const [from, to] of [["01-01", "06-30"], ["07-01", "12-31"]]) {
      const q = `repo:temporalio/temporal is:issue is:closed closed:${year}-${from}..${year}-${to}`;
      issues.push(
        ...(await paginate(async (after) => {
          const { search } = await graphql<{ search: Page<ClosedIssue> }>(CLOSED_ISSUES, { q, after });
          return search;
        })),
      );
    }
  }
  return issues;
}

const COMMIT_LOGINS = `query($since: GitTimestamp!, $after: String) {
  repository(owner: "temporalio", name: "temporal") { defaultBranchRef { target { ... on Commit {
    history(since: $since, first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { oid author { user { login } } }
    }
  } } } }
}`;

type CommitNode = { oid: string; author: { user: { login: string } | null } | null };
type CommitPage = { repository: { defaultBranchRef: { target: { history: Page<CommitNode> } } } };

/** Maps commit SHA to GitHub login, which `git log` alone can't give. */
export async function fetchCommitLogins(since: string): Promise<Record<string, string | null>> {
  const graphql = client();
  const commits = await paginate(async (after) => {
    const { repository } = await graphql<CommitPage>(COMMIT_LOGINS, { since, after });
    return repository.defaultBranchRef.target.history;
  });
  return Object.fromEntries(commits.map((c) => [c.oid, c.author?.user?.login ?? null]));
}

const ISSUE = `query($number: Int!) {
  repository(owner: "temporalio", name: "temporal") { issue(number: $number) { title body } }
}`;

export async function fetchIssue(number: number): Promise<IssueText> {
  const { repository } = await client()<{ repository: { issue: IssueText } }>(ISSUE, { number });
  return repository.issue;
}

/** Files each PR changed. A PR over 100 files is cut there, which is plenty to name its owner. */
export async function fetchPrFiles(numbers: number[]): Promise<Record<number, string[]>> {
  const graphql = client();
  const out: Record<number, string[]> = {};
  for (let start = 0; start < numbers.length; start += 40) {
    const batch = numbers.slice(start, start + 40);
    const fields = batch.map((n) => `p${n}: pullRequest(number: ${n}) { files(first: 100) { nodes { path } } }`).join("\n");
    const { repository } = await graphql<{ repository: Record<string, { files: { nodes: { path: string }[] } }> }>(
      `query { repository(owner: "temporalio", name: "temporal") { ${fields} } }`,
    );
    for (const n of batch) out[n] = repository[`p${n}`]!.files.nodes.map((f) => f.path);
  }
  return out;
}

const TEAM_MEMBERS = `query($team: String!, $after: String) {
  organization(login: "temporalio") { team(slug: $team) { members(first: 100, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { login }
  } } }
}`;

type MemberPage = { organization: { team: { members: Page<{ login: string }> } } };

export async function fetchMembership(): Promise<[string, Team[]][]> {
  const graphql = client();
  const membership = new Map<string, Team[]>();
  for (const team of TEAMS) {
    const members = await paginate(async (after) => {
      const { organization } = await graphql<MemberPage>(TEAM_MEMBERS, { team, after });
      return organization.team.members;
    });
    for (const { login } of members) {
      const key = login.toLowerCase();
      membership.set(key, [...(membership.get(key) ?? []), team]);
    }
  }
  return [...membership];
}

export const toMembership = (entries: [string, Team[]][]): Membership =>
  new Map(entries.map(([login, teams]) => [login, new Set(teams)]));

/** Commits on the default branch, oldest paths included, with logins filled in. */
export function gitCommits(repoDir: string, ref: string, logins: Record<string, string | null>): Commit[] {
  const log = execFileSync("git", ["-C", repoDir, "log", ref, "--no-merges", "--format=@@%H %ct", "--name-only"], {
    encoding: "utf8",
    maxBuffer: 1 << 30,
  });
  return log.split("@@").flatMap((entry) => {
    const [header, ...files] = entry.split("\n").filter(Boolean);
    if (!header) return [];
    const [sha, seconds] = header.split(" ") as [string, string];
    return [{ at: Number(seconds) * 1000, login: logins[sha] ?? null, files }];
  });
}
