"""Compares label sources with a cheap word-based model, before paying for a Jev run.

Each test issue is predicted by a model trained only on rows from before its quarter. The model
is a stand-in for telling which labels carry team signal, not a forecast of Jev's accuracy.

    python training/compare.py
"""
import json
import os
import statistics
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")  # this shares a machine with other work

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.pipeline import make_pipeline

DATA = Path(".cache/training")
QUARTERS = [("2026-01-01", "2026-04-01"), ("2026-04-01", "2026-07-01"), ("2026-07-01", "2026-10-01"), ("2026-10-01", "2027-01-01")]
SEEDS = range(7)


def model(seed):
    words = TfidfVectorizer(sublinear_tf=True, min_df=2, max_features=50000)
    classifier = SGDClassifier(loss="log_loss", alpha=1e-5, max_iter=20, tol=None, random_state=seed, class_weight="balanced")
    return make_pipeline(words, classifier)


def correct_issues(rows, test, seed):
    correct = []
    for start, end in QUARTERS:
        train = [row for row in rows if row["at"] < start]
        issues = [issue for issue in test if start <= issue["at"] < end]
        fitted = model(seed).fit([row["text"] for row in train], [row["team"] for row in train])
        predicted = fitted.predict([issue["text"] for issue in issues])
        correct += [issue for issue, team in zip(issues, predicted) if team == issue["team"]]
    return correct


def main():
    test = json.load(open(DATA / "test.json"))
    pool = json.load(open(DATA / "pool.json"))
    tickets = [row for row in pool if row["source"] == "ticket"]
    open_issues = [row for row in pool if row["source"] == "open issue"]
    prs = json.load(open(DATA / "prs.json"))
    sources = {
        "PRs, by author's team": prs,
        "tickets": tickets,
        "tickets + open issues": tickets + open_issues,
        "tickets + open issues x3": tickets + open_issues * 3,
        "PRs + tickets": prs + tickets,
        "PRs + tickets + open issues": prs + tickets + open_issues,
    }
    from_assignee = sum(issue["answer_from"] == "assignee" for issue in test)
    print(f"{len(test)} issues: {from_assignee} answers from the assignee, {len(test) - from_assignee} from elsewhere; mean of {len(SEEDS)} seeds")
    for name, rows in sources.items():
        runs = [correct_issues(rows, test, seed) for seed in SEEDS]
        totals = [len(run) for run in runs]
        assignee = statistics.mean(sum(issue["answer_from"] == "assignee" for issue in run) for run in runs)
        print(f"{name:30} {statistics.mean(totals):5.1f} ({min(totals)}-{max(totals)})  assignee {assignee:4.1f}  elsewhere {statistics.mean(totals) - assignee:4.1f}", flush=True)


if __name__ == "__main__":
    main()
