# Picking a team for an issue

Two models read an issue's title and body and give a probability for each team. Their average decides:
name the team at 0.8 or above, otherwise a person chooses from the top two. Neither model sees comments or the fix.

| Step | File | What it does | Cost |
|---|---|---|---|
| 1 | `labels.py` | Builds the training rows from the vault | Free, read-only |
| 2 | `embed_teams.py` | Qwen3-Embedding-8B, frozen, plus logistic regression trained on those rows | About $0.10, one L40S |
| 3 | `stock_openjev.py` | OpenJev with no training, reading `teams.json` | About $0.40, one H100 |
| 4 | `route_rule.py` | Averages the two, applies the rule, scores it | Free |

`compare.py` and `train_tod.py` are earlier experiments, kept as the record of the results below.

Issue text, ticket text and labels stay in `.cache/training/`, which isn't committed:
`test.json` (the answer key), `area_labels.csv` (a suggested team for each open issue, from its Area)
and the rows and picks the steps write. `test.json` and `area_labels.csv` came from a one-off export,
not from code here.

## Results

Correct of 140 issues filed in 2026, from `results/2026-11-06-routing-rule.txt`. Four answers were corrected
from team boards, listed in `route_rule.py`. Each quarter's embedding classifier saw only rows from before it.

| Model | All | Q1 (11) | Q2 (63) | Q3 (35) | Q4 (31) |
|---|---:|---:|---:|---:|---:|
| Stock OpenJev | 114 | 11 | 49 | 32 | 22 |
| Embeddings + logistic regression | 112 | 9 | 51 | 31 | 21 |
| Average of the two | 112 | 10 | 51 | 31 | 20 |

| Rule at 0.8 | Named | Right | Sent to a person | Right team in top two |
|---|---:|---:|---:|---:|
| January to June | 41 of 74 | 39 | 33 | 30 |
| July onward | 34 of 66 | 32 | 32 | 31 |
| All | 75 of 140 | 71 | 65 | 61 |

Fine-tuning TOD on the same rows failed its bar: at most 42 of 63 in Q2 on the corrected key, against 49 for stock OpenJev.
Word counts on the same rows score 41 in Q2, so the rows do carry signal and the fine-tune was the weak step.

Limits:

- The blend and the 0.8 threshold were chosen after seeing these results, though both halves of the year agree.
- 71 of 75 has a 95% interval of about 87% to 98%.
- Open issue rows use Area suggestions built with evidence from after some test dates, which may flatter the embedding score.

## Labels

- **Team tickets.** The Jira or Linear project names the team, and the umbrella `OSS` project goes by the assignee's team.
  Tickets need a 40-character description. Any that link to or copy a test issue are dropped.
- **Open issues.** An issue gets the team suggested for its Area, when that suggestion is high or medium confidence.
  Issues in an unresolved Area are left out.

PRs labelled by author aren't used: they scored lowest and add nothing to tickets.

## Which labels to use

`compare.py` scored each label source with a word-based model, as a mean of 7 seeds on the original answer key,
from `results/2026-11-05-label-sources.txt`. PRs by author's team 75.3, tickets 90.4, tickets + open issues 96.9.

## Assumptions

- Most of the ticket gain is on assignee answers, and a ticket's team and an assignee's team measure much the same thing.
  On the other 65 answers tickets gain only about 3 issues over PRs, and tickets plus open issues about 6.
- The answer key comes from labels, fix authors, assignees and approvers, so every score inherits its errors. Team boards back 49 of the 53 answers they cover.
- The mix was chosen on these 140 issues, so a final check needs issues filed after them.
- Area suggestions use evidence from after some test dates, a small leak in the open issue rows.
- ACT is about 28% of training rows and 18% of test issues; Foundations is 23% of training rows and 54% of test issues.
- `teams.json` and the Area table disagree in places, such as mutable state. A rewrite from the Area table scored no better on January to June, 59 against 60 of 74.
- `build_dataset` drops identical rows, so repeating open issues to weight them would do nothing.
