import Turbopuffer from "@turbopuffer/turbopuffer";

export type Method = "voyage" | "keyword" | "hybrid";
export const METHODS: Method[] = ["voyage", "keyword", "hybrid"];

/** Files for a query, best first, by each search method. */
export type Hits = Record<Method, string[]>;

export type IssueText = { title: string; body: string | null };

const STOPWORDS = new Set(
  "the a an and or of to in for on with is are be this that it as at by from we i you not when if can should would could has have was were will do does into via but".split(
    " ",
  ),
);

const CHUNKS = 100;
const RRF_K = 60;

/** Title and body with HTML comments dropped and long code blocks cut, as PR #14 did. */
export function issueQuery({ title, body }: IssueText): string {
  const text = (body ?? "")
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/```[\s\S]*?```/g, (block) => block.slice(0, 600));
  return `${title}\n\n${text}`.slice(0, 4000);
}

export const keywords = (query: string): string =>
  (query.match(/[A-Za-z][A-Za-z0-9_]+/g) ?? [])
    .filter((word) => !STOPWORDS.has(word.toLowerCase()))
    .join(" ")
    .slice(0, 1000);

type Row = { id: string | number; path?: unknown };

const uniquePaths = (rows: Row[]): string[] => [...new Set(rows.map((row) => String(row.path)))];

/** Reciprocal rank fusion over chunks, then one entry per file. */
export function fuse(lists: Row[][]): string[] {
  const scored = new Map<string | number, { row: Row; score: number }>();
  for (const rows of lists) {
    rows.forEach((row, rank) => {
      const entry = scored.get(row.id) ?? { row, score: 0 };
      entry.score += 1 / (RRF_K + rank + 1);
      scored.set(row.id, entry);
    });
  }
  const ranked = [...scored.values()].sort((a, b) => b.score - a.score);
  return uniquePaths(ranked.map(({ row }) => row));
}

export type CodeSearch = (query: string) => Promise<Hits>;

/** Reads a code namespace; never writes to it. */
export function turbopufferSearch(apiKey: string, namespace: string, region = "gcp-us-west1"): CodeSearch {
  const ns = new Turbopuffer({ apiKey, region }).namespace(namespace);
  return async (query) => {
    const include_attributes = ["path"];
    const terms = keywords(query);
    const { results } = await ns.multiQuery({
      queries: [
        { rank_by: ["text", "ANN", ["Embed", query]], top_k: CHUNKS, include_attributes },
        ...(terms ? [{ rank_by: ["fts", "BM25", terms] as ["fts", "BM25", string], top_k: CHUNKS, include_attributes }] : []),
      ],
    });
    const voyage = (results[0]?.rows ?? []) as Row[];
    const keyword = (results[1]?.rows ?? []) as Row[];
    return { voyage: uniquePaths(voyage), keyword: uniquePaths(keyword), hybrid: fuse([voyage, keyword]) };
  };
}
