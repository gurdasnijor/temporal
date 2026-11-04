#!/usr/bin/env python3
"""Deterministic team labeler for open temporalio/temporal PRs.

Scores each PR for each server team from four signals and picks the best:
  owners    share of the PR's non-generated files that CODEOWNERS gives the team
  history   share of the last 12 months of commits on those files made by team members
  author    PR author is on the team
  reviewer  a team member reviewed or was requested, or the team itself was requested

Usage: team_labeler.py [--refresh] [--repo-dir DIR] [--out DIR]
  --refresh   refetch PRs, team membership and commit logins from GitHub (else reuse cache)
Outputs labels.csv (every PR) and labels.json in --out.
"""
import argparse, collections as C, csv, json, os, re, subprocess, sys

TEAMS = ["oss-matching", "oss-foundations", "act", "nexus", "cgs"]
WEIGHTS = dict(owners=0.40, history=0.35, author=0.15, reviewer=0.10)
CATCH_ALL = "oss-foundations"
GEN = re.compile(r"(\.pb\.go|\.pb\.mock\.go|_mock\.go|_gen\.go|\.gen\.go|go\.sum|go\.mod)$")

ap = argparse.ArgumentParser()
ap.add_argument("--refresh", action="store_true")
ap.add_argument("--repo-dir", default=os.path.expanduser("/workspace/worktrees/3ghjzqv8/fluffy-liger"))
ap.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
args = ap.parse_args()
os.chdir(args.out)


def gh_graphql(query, **vars):
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for k, v in vars.items():
        if v is not None:
            cmd += ["-f", f"{k}={v}"]
    for _ in range(5):
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode == 0:
            return json.loads(p.stdout)["data"]
    sys.exit(p.stderr)


def paginate(query, path):
    out, cur = [], None
    while True:
        node = gh_graphql(query, cursor=cur)
        for key in path:
            node = node[key]
        out += node["nodes"]
        if not node["pageInfo"]["hasNextPage"]:
            return out
        cur = node["pageInfo"]["endCursor"]


PR_QUERY = """query($cursor:String){repository(owner:"temporalio",name:"temporal"){
 pullRequests(states:OPEN,first:20,after:$cursor){pageInfo{hasNextPage endCursor} nodes{
  number title url isDraft author{login} authorAssociation
  files(first:100){nodes{path}}
  latestReviews(first:20){nodes{author{login}}}
  reviewRequests(first:10){nodes{requestedReviewer{... on Team{slug} ... on User{login}}}}}}}}"""
HISTORY_QUERY = """query($cursor:String){repository(owner:"temporalio",name:"temporal"){defaultBranchRef{target{
 ... on Commit{history(since:"%s",first:100,after:$cursor){pageInfo{hasNextPage endCursor}
 nodes{oid author{user{login}}}}}}}}}"""

if args.refresh or not os.path.exists("prs.json"):
    json.dump(paginate(PR_QUERY, ["repository", "pullRequests"]), open("prs.json", "w"))
if args.refresh or not os.path.exists("team_members.tsv"):
    with open("team_members.tsv", "w") as f:
        for t in TEAMS + ["server"]:
            logins = subprocess.check_output(
                ["gh", "api", f"orgs/temporalio/teams/{t}/members?per_page=100", "--paginate", "--jq", ".[].login"], text=True)
            f.writelines(f"{t}\t{l}\n" for l in logins.split())
since = subprocess.check_output(["date", "-u", "-d", "12 months ago", "+%Y-%m-%dT00:00:00Z"], text=True).strip()
if args.refresh or not os.path.exists("commit_login.json"):
    nodes = paginate(HISTORY_QUERY % since, ["repository", "defaultBranchRef", "target", "history"])
    json.dump({n["oid"]: (n["author"]["user"] or {}).get("login") for n in nodes}, open("commit_login.json", "w"))
if args.refresh or not os.path.exists("gitlog.txt"):
    subprocess.run(["git", "-C", args.repo_dir, "fetch", "-q", "origin", "main"], check=True)
    with open("gitlog.txt", "w") as f:
        subprocess.run(["git", "-C", args.repo_dir, "log", "origin/main", f"--since={since}", "--no-merges",
                        "--format=@@%H", "--name-only"], stdout=f, check=True)

prs = json.load(open("prs.json"))
commit_login = json.load(open("commit_login.json"))
member_of = C.defaultdict(set)
for line in open("team_members.tsv"):
    t, login = line.split()
    member_of[login.lower()].add(t)


def teams_of(login):
    return member_of.get((login or "").lower(), set()) & set(TEAMS)


# CODEOWNERS: last matching rule wins; the catch-all "*" and generated-file rules are skipped.
rules = []
for line in open(os.path.join(args.repo_dir, ".github/CODEOWNERS")):
    line = line.split("#")[0].strip()
    if not line:
        continue
    pat, *owners = line.split()
    if pat == "*" or GEN.search(pat.replace("*", "x")):
        continue
    p = pat.lstrip("/")
    rx = re.escape(p).replace(r"\*\*", ".*").replace(r"\*", "[^/]*") + (".*" if p.endswith("/") else "")
    rules.append((re.compile(("^" if pat.startswith("/") else "(^|.*/)") + rx + "$"),
                  [o.removeprefix("@temporalio/") for o in owners]))


def codeowners(path):
    owners = None
    for rx, o in rules:
        if rx.match(path):
            owners = o
    return [o for o in (owners or []) if o in TEAMS]


file_authors, dir_authors = C.defaultdict(list), C.defaultdict(list)
login = None
for line in open("gitlog.txt"):
    line = line.strip()
    if line.startswith("@@"):
        login = commit_login.get(line[2:])
    elif line and not GEN.search(line):
        file_authors[line].append(login)
        dir_authors[os.path.dirname(line)].append(login)


def file_signals(files):
    """Per-team CODEOWNERS and commit-history shares for a list of paths."""
    owners, history = C.Counter(), C.Counter()
    hist_files = 0
    for f in files:
        o = codeowners(f)
        for t in o:
            owners[t] += 1 / len(o)
        authors, d = file_authors.get(f), os.path.dirname(f)
        while not authors and d:  # new files: fall back to the nearest folder with history
            authors, d = dir_authors.get(d), os.path.dirname(d)
        authors = authors or []
        if authors:
            hist_files += 1
            for a in authors:  # every commit counts in the denominator, team members in the numerator
                ts = teams_of(a)
                for t in ts:
                    history[t] += 1 / len(ts) / len(authors)
    return ({t: owners[t] / len(files) if files else 0 for t in TEAMS},
            {t: history[t] / hist_files if hist_files else 0 for t in TEAMS}, hist_files)


def label(pr):
    files = [f["path"] for f in pr["files"]["nodes"] if not GEN.search(f["path"])]
    owners, history, hist_files = file_signals(files)
    author = (pr["author"] or {}).get("login")
    reviewers = {r["author"]["login"] for r in pr["latestReviews"]["nodes"] if r["author"]}
    req = [r["requestedReviewer"] or {} for r in pr["reviewRequests"]["nodes"]]
    reviewers |= {r["login"] for r in req if "login" in r}
    review_teams = {t for r in reviewers for t in teams_of(r)} | {r["slug"] for r in req if r.get("slug") in TEAMS}
    sig = {t: dict(owners=owners[t], history=history[t],
                   author=float(t in teams_of(author)),
                   reviewer=float(t in review_teams)) for t in TEAMS}
    score = {t: sum(WEIGHTS[k] * v for k, v in s.items()) for t, s in sig.items()}
    ranked = sorted(score, key=score.get, reverse=True)
    top, second = ranked[0], ranked[1]
    margin = score[top] - score[second]
    if score[top] >= 0.40 and margin >= 0.15:
        confidence = "high"
    elif score[top] >= 0.25 and margin >= 0.08:
        confidence = "medium"
    else:
        confidence = "low"
    team = top if confidence != "low" else CATCH_ALL
    s = sig[top]
    reasons = [f"owners {s['owners']:.0%}", f"history {s['history']:.0%}"]
    if s["author"]:
        reasons.append("author on team")
    if s["reviewer"]:
        reasons.append("team reviewer")
    return dict(number=pr["number"], title=pr["title"], url=pr["url"], author=author,
                external=pr["authorAssociation"] != "MEMBER", draft=pr["isDraft"],
                team=team, confidence=confidence, top=top, score=round(score[top], 2),
                runner_up=f"{second} {score[second]:.2f}", reasons=", ".join(reasons),
                files=len(files), files_with_history=hist_files)


if __name__ == "__main__":
    rows = sorted((label(p) for p in prs), key=lambda r: r["number"])
    json.dump(rows, open("labels.json", "w"), indent=1)
    with open("labels.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    dist = C.Counter((r["team"], r["confidence"]) for r in rows)
    for t in TEAMS:
        print(f"{t:16s} high {dist[(t, 'high')]:3d}  medium {dist[(t, 'medium')]:3d}  low->catch-all "
              f"{sum(1 for r in rows if r['confidence'] == 'low' and r['top'] == t):3d}")
    print(f"total {len(rows)} PRs; low confidence (sent to {CATCH_ALL}): {sum(r['confidence'] == 'low' for r in rows)}")
