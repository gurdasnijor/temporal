# oss-triage

Suggests which team owns a `temporalio/temporal` issue, and tests how often that suggestion is right.
It replaces the Python spike in `tools/oss-triage-spike`, except for PR scoring, which isn't ported yet.

An issue's title and body search the code index. The files found give team scores from CODEOWNERS
and from who committed to them in the year before. See `src/route.ts`.

## Run it

Needs Node 24, `gh` auth, `TURBOPUFFER_API_KEY` and a checkout of temporal (`REPO_DIR`, `REPO_REF`).
All of these read only. The code index, `vault-code-temporal`, is never written.

    npm ci
    npm run typecheck && npm test
    npm run route -- 12962       # one issue, or --title "..." --body "..."
    npm run eval                 # the blind eval; inputs cache in .cache/
    SHOW_MISSES=18 npm run eval  # also lists issues to read by hand

## Linear agent

`npm run serve` answers Linear agent session events at `POST /webhook`. When an issue is delegated
to it or it's mentioned, it posts a thought, then a suggestion with the closest files. It never
changes the issue: it has no write path except session activities.

Not run against Linear yet. Tests cover it with Linear's real webhook client and signatures but a
fake session. Installing it needs a workspace admin, an OAuth app with `actor=app` and the scopes
`app:assignable` and `app:mentionable`, then `LINEAR_ACCESS_TOKEN` and `LINEAR_WEBHOOK_SECRET`.

## Training Jev

`training/` holds the labels and fine-tuning proposed for Jev. See `training/README.md`. Nothing there has run on a GPU.

## Blind eval

Each closed issue with a merged fix PR gets the team of the PR's author, or the one team that
approved it. Routing sees only the title and body, and commit history stops the day the issue was
filed. Thresholds are cross-fitted over 5 folds. Full output: `results/2026-11-05-blind-eval.txt`.

Results on 163 issues, where always guessing Foundations gets 50%:

| | Right overall | Right in high band |
|---|---|---|
| Voyage + CODEOWNERS + history | 57% | 41/57, 72% |
| Keyword + CODEOWNERS + history | 55% | 33/37, 89% |
| Hybrid + CODEOWNERS + history | 60% | 40/51, 78% |
| Same ownership step on the fix's own files | 60% | 41/51, 80% |

No approach routed a useful share at 95% on all issues, so the agent stays suggestion-only.

Limits: the index is a recent snapshot and may hold the fix, which flatters every search arm.
CODEOWNERS and team membership are today's, not those at filing. Issue bodies may have been edited.
A fix's author isn't always the owner. ACT, CGS and Nexus have too few issues to judge. Arms were
compared on the same 163 issues, so the best arm's figures are slightly optimistic. Issues with no
fix PR aren't tested.
