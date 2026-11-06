"""Picks a team for each test issue from the issue's text, using embeddings and a simple classifier.

Qwen3-Embedding-8B turns each ticket and issue into a vector. It is used as is, with no fine-tuning.
A logistic regression then learns which vectors belong to which team, from the rows labels.py built.
Each quarter's issues are scored by a classifier that saw only rows from before that quarter,
and test issues are never training rows. About $0.10 on one L40S.

    modal run training/embed_teams.py
"""
import json
from pathlib import Path

import modal

MODEL = "Qwen/Qwen3-Embedding-8B"
TEAMS = ["oss-matching", "oss-foundations", "act", "nexus", "cgs"]
INSTRUCTION = "Instruct: Identify which engineering team owns this Temporal server work\nQuery: "
QUARTERS = [
    ("2026-01-01", "2026-04-01"),
    ("2026-04-01", "2026-07-01"),
    ("2026-07-01", "2026-10-01"),
    ("2026-10-01", "2027-01-01"),
]
DATA = Path(".cache/training")

app = modal.App("oss-triage-embed-teams")
image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "torch", "transformers>=4.56", "sentence-transformers>=5", "scikit-learn", "accelerate", "numpy"
)


@app.function(image=image, gpu="L40S", timeout=1500)
def pick_teams(rows, issues):
    import numpy as np
    from sentence_transformers import SentenceTransformer
    from sklearn.linear_model import LogisticRegression

    model = SentenceTransformer(MODEL, model_kwargs={"torch_dtype": "bfloat16"})
    model.max_seq_length = 1024

    def embed(items):
        texts = [INSTRUCTION + item["text"] for item in items]
        return model.encode(texts, batch_size=16, normalize_embeddings=True).astype("float32")

    row_vectors, issue_vectors = embed(rows), embed(issues)
    row_teams = np.array([TEAMS.index(row["team"]) for row in rows])

    picks = {}
    for start, end in QUARTERS:
        earlier = [i for i, row in enumerate(rows) if row["at"] < start]
        in_quarter = [i for i, issue in enumerate(issues) if start <= issue["at"] < end]
        classifier = LogisticRegression(C=10, max_iter=2000, class_weight="balanced")
        classifier.fit(row_vectors[earlier], row_teams[earlier])
        probabilities = classifier.predict_proba(issue_vectors[in_quarter])
        for i, issue_probabilities in zip(in_quarter, probabilities):
            by_team = dict(zip((TEAMS[c] for c in classifier.classes_), issue_probabilities.tolist()))
            picks[issues[i]["number"]] = {team: by_team.get(team, 0.0) for team in TEAMS}
        print(f"{start}: trained on {len(earlier)} rows, scored {len(in_quarter)} issues", flush=True)
    return picks


@app.local_entrypoint()
def main():
    rows = json.load(open(DATA / "pool.json"))
    issues = [{"number": issue["number"], "at": issue["at"], "text": issue["text"]} for issue in json.load(open(DATA / "test.json"))]
    json.dump(pick_teams.remote(rows, issues), open(DATA / "embed-picks.json", "w"))
