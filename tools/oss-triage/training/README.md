# Training Jev to pick a team

Proposed, not run. Jev here means TOD, the open picker from [open-jev](https://github.com/daseinlabs/open-jev),
fine-tuned the way its ticket routing cookbook does it.

| File | What it does | Cost |
|---|---|---|
| `labels.py` | Builds the training rows from the vault | Free, read-only |
| `compare.py` | Scores label sources with a cheap word-based model | Free, about a minute on one thread |
| `train_tod.py` | Fine-tunes TOD on Modal and picks teams for one quarter | One H100, 2-hour limit |
| `teams.json` | What each team owns; TOD reads this as the choices | |

Issue text, ticket text and labels stay in `.cache/training/`, which isn't committed:
`test.json` (the frozen answer key), `prs.json` (old PR labels, for comparison only) and
`area_labels.csv` (a suggested team for each open issue, from its Area).

## Labels

- **Team tickets.** The Jira or Linear project names the team, and the umbrella `OSS` project goes by the assignee's team.
  Tickets need a 40-character description. Any that link to or copy a test issue are dropped.
- **Open issues.** An issue gets the team suggested for its Area, when that suggestion is high or medium confidence.
  Issues in an unresolved Area are left out.

PRs labelled by author aren't used: they scored lowest and add nothing to tickets.

## What the comparison shows

Correct of 140 test issues, mean of 7 seeds, from `results/2026-11-05-label-sources.txt`.
"Assignee" is the 75 answers taken from an issue's assignee. "Elsewhere" is the other 65: team labels, fix authors and approvers.

| Labels | All | Assignee | Elsewhere |
|---|---:|---:|---:|
| PRs by author's team | 75.3 | 38.6 | 36.7 |
| Tickets | 90.4 | 51.4 | 39.0 |
| Tickets + open issues | 96.9 | 54.1 | 42.7 |
| PRs + tickets + open issues | 93.6 | 52.0 | 41.6 |

This compares labels, not models. Stock OpenJev scores 114 on the same issues, and 95% is 133.

## Assumptions

- Most of the ticket gain is on assignee answers, and a ticket's team and an assignee's team measure much the same thing.
  On the other 65 answers tickets gain only about 2 issues over PRs, and tickets plus open issues about 6.
- The answer key has known errors and stays frozen for now, so every score inherits them.
- The mix was chosen on these 140 issues, so a final check needs issues filed after the freeze.
- Area suggestions use evidence from after some test dates, a small leak in the open issue rows.
- ACT is about 37% of training rows and 18% of test issues; Foundations is 54% of test issues.
- `teams.json` and the Area table disagree in places, such as mutable state, and TOD sees both.
- `build_dataset` drops identical rows, so repeating open issues to weight them would do nothing.

## Pass bar

Run 2026Q2 alone first: about 1,800 rows before April 2026, tested on 63 issues. It passes if it clearly
beats stock OpenJev on those same issues, on assignee answers and on the rest. Other quarters run only then.
