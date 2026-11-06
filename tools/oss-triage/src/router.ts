import { isGenerated } from "./codeowners.ts";
import { routeFiles, type Decision, type Ownership } from "./route.ts";
import { issueQuery, type CodeSearch, type IssueText, type Method } from "./search.ts";
import type { Team } from "./teams.ts";

export type Evidence = { path: string; owners: Team[] };

export type Route = Decision & { files: Evidence[] };

export type Router = (issue: IssueText) => Promise<Route>;

const SHOWN_FILES = 5;

/** Issue text to a team decision, with the files that drove it. Used by the CLI and the Linear agent. */
export const createRouter =
  (search: CodeSearch, ownership: Ownership, method: Method = "hybrid"): Router =>
  async (issue) => {
    const hits = await search(issueQuery(issue));
    const ranked = hits[method];
    const files = ranked
      .filter((path) => !isGenerated(path))
      .slice(0, SHOWN_FILES)
      .map((path) => ({ path, owners: ownership.codeowners(path) }));
    return { ...routeFiles(ranked, Date.now(), ownership), files };
  };
