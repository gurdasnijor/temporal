/**
 * Routes one issue and prints the suggestion Linear would get. Reads only.
 *
 *   node src/cli/route.ts 1234
 *   node src/cli/route.ts --title "Matching drops tasks" --body "..."
 *
 * Needs TURBOPUFFER_API_KEY, `gh` auth and a checkout (REPO_DIR, REPO_REF).
 */
import { parseArgs } from "node:util";
import { fetchIssue } from "../github.ts";
import { suggestion } from "../linear/agent.ts";
import { loadRouter } from "../service.ts";

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: { title: { type: "string" }, body: { type: "string" } },
});
const number = positionals[0];
if (!number && !values.title) throw new Error("give an issue number or --title");

const issue = number ? await fetchIssue(Number(number)) : { title: values.title!, body: values.body ?? null };
const route = await loadRouter();
console.log(suggestion(await route(issue)));
