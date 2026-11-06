import picomatch from "picomatch";
import { isTeam, type Team } from "./teams.ts";

const GENERATED = /(\.pb\.go|\.pb\.mock\.go|_mock\.go|_gen\.go|\.gen\.go|go\.sum|go\.mod)$/;

export const isGenerated = (path: string): boolean => GENERATED.test(path);

export type Codeowners = (path: string) => Team[];

/**
 * Parses CODEOWNERS. The last matching rule wins, as on GitHub. The repo-wide `*` rule and the
 * generated-file rules are skipped: they say who may approve, not who owns the code.
 */
export function parseCodeowners(text: string): Codeowners {
  const rules = text.split("\n").flatMap((raw) => {
    const [pattern, ...owners] = raw.split("#")[0]!.trim().split(/\s+/);
    if (!pattern || pattern === "*" || isGenerated(pattern.replaceAll("*", "x"))) return [];
    const teams = owners.map((o) => o.replace("@temporalio/", "")).filter(isTeam);
    return [{ matches: picomatch(toGlob(pattern), { dot: true }), teams }];
  });
  return (path) => rules.findLast((rule) => rule.matches(path))?.teams ?? [];
}

/** `/a/` covers everything below it, `/a/*` only direct children, and a bare name matches at any depth. */
function toGlob(pattern: string): string {
  const anchored = pattern.startsWith("/") || pattern.slice(0, -1).includes("/");
  const path = pattern.replace(/^\//, "");
  const glob = path.endsWith("/") ? `${path}**` : path;
  return anchored ? glob : `**/${glob}`;
}
