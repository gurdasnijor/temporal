import { teamsOf, type Membership, type Team } from "./teams.ts";

export type Pr = {
  number: number;
  merged: boolean;
  author: { login: string } | null;
  baseRepository: { nameWithOwner: string } | null;
  latestReviews: { nodes: { state: string; author: { login: string } | null }[] };
};

type Closer = (Partial<Pr> & { __typename?: string; associatedPullRequests?: { nodes: (Pr | null)[] } }) | null;

export type TimelineItem =
  | { __typename: "ClosedEvent"; closer: Closer }
  | { __typename: "ConnectedEvent"; subject: Closer }
  | { __typename: "CrossReferencedEvent"; willCloseTarget: boolean; source: Closer };

export type ClosedIssue = {
  number: number;
  title: string;
  body: string | null;
  createdAt: string;
  closedAt: string;
  labels: { nodes: { name: string }[] };
  timelineItems: { nodes: TimelineItem[] };
};

export type Link = "firm" | "loose";
export type Source = "author" | "approver";

export type Truth = { number: number; team: Team; source: Source; link: Link; pr: number };

const REPO = "temporalio/temporal";

const mergedHere = (pr: Closer): pr is Pr & { __typename?: string } =>
  Boolean(pr?.merged) && pr?.baseRepository?.nameWithOwner === REPO;

/** The merged PR behind an issue. A closing reference beats a plain mention. */
export function fixPr(issue: ClosedIssue): { pr: Pr; link: Link } | undefined {
  let loose: Pr | undefined;
  for (const item of issue.timelineItems.nodes) {
    let pr: Closer = null;
    let firm = false;
    if (item.__typename === "ClosedEvent") {
      pr = item.closer?.__typename === "Commit" ? (item.closer.associatedPullRequests?.nodes[0] ?? null) : item.closer;
      firm = true;
    } else if (item.__typename === "ConnectedEvent") {
      pr = item.subject;
      firm = true;
    } else if (item.__typename === "CrossReferencedEvent") {
      pr = item.source;
      firm = item.willCloseTarget;
    }
    if (!mergedHere(pr)) continue;
    if (firm) return { pr, link: "firm" };
    loose ??= pr;
  }
  return loose && { pr: loose, link: "loose" };
}

/**
 * The team that fixed an issue: the PR author's team, or for authors on no team, the one team that
 * approved it. Authors on several teams are left out. Nothing here reads CODEOWNERS or file history,
 * so the answer stays independent of what the router uses.
 */
export function truthFor(issue: ClosedIssue, membership: Membership): Truth | undefined {
  const fix = fixPr(issue);
  if (!fix) return undefined;
  const { pr, link } = fix;
  const authorTeams = teamsOf(membership, pr.author?.login);
  const base = { number: issue.number, link, pr: pr.number };
  if (authorTeams.size === 1) return { ...base, team: [...authorTeams][0]!, source: "author" };
  if (authorTeams.size > 1) return undefined;
  const approvers = new Set(
    pr.latestReviews.nodes
      .filter((review) => review.state === "APPROVED")
      .flatMap((review) => [...teamsOf(membership, review.author?.login)]),
  );
  return approvers.size === 1 ? { ...base, team: [...approvers][0]!, source: "approver" } : undefined;
}
