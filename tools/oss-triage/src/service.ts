import { execFileSync } from "node:child_process";
import { parseCodeowners } from "./codeowners.ts";
import { fetchCommitLogins, fetchMembership, gitCommits, toMembership } from "./github.ts";
import { CommitHistory } from "./history.ts";
import { createRouter, type Router } from "./router.ts";
import { turbopufferSearch } from "./search.ts";

const YEAR_MS = 365 * 24 * 3600 * 1000;

/** A router over today's ownership. History only looks back a year, so only a year of logins is fetched. */
export async function loadRouter(env = process.env): Promise<Router> {
  const repoDir = env.REPO_DIR ?? execFileSync("git", ["rev-parse", "--show-toplevel"], { encoding: "utf8" }).trim();
  const ref = env.REPO_REF ?? "origin/main";
  const since = new Date(Date.now() - YEAR_MS).toISOString();
  const [entries, logins] = await Promise.all([fetchMembership(), fetchCommitLogins(since)]);
  const codeowners = parseCodeowners(
    execFileSync("git", ["-C", repoDir, "show", `${ref}:.github/CODEOWNERS`], { encoding: "utf8" }),
  );
  const history = new CommitHistory(gitCommits(repoDir, ref, logins), toMembership(entries));
  const search = turbopufferSearch(env.TURBOPUFFER_API_KEY!, env.CODE_NAMESPACE ?? "vault-code-temporal");
  return createRouter(search, { codeowners, history });
}
