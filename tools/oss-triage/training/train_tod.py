"""Fine-tunes TOD, Jev's open picker, then picks a team for one quarter of test issues.

Follows open-jev's ticket routing cookbook. Training rows all predate the quarter under test.
Costs money: read the README before running.

    modal run training/train_tod.py --quarter 2026Q2
"""
import json
from collections import Counter
from pathlib import Path

import modal

TEAMS = ["oss-matching", "oss-foundations", "act", "nexus", "cgs"]
QUESTION = "Which team should own this work in the Temporal server repository?"
QUARTERS = {"2026Q2": ("2026-04-01", "2026-07-01"), "2026Q3": ("2026-07-01", "2026-10-01"), "2026Q4": ("2026-10-01", "2027-01-01")}
DATA = Path(".cache/training")

app = modal.App("oss-triage-tod")
models = modal.Volume.from_name("oss-triage-openjev", create_if_missing=True)
image = modal.Image.debian_slim(python_version="3.12").pip_install("openjev-sdk==0.5.0", "accelerate").env({"HF_HOME": "/models/hf"})


@app.function(image=image, gpu="H100", volumes={"/models": models}, timeout=2 * 3600)
def train_and_pick(quarter, train, test, scopes):
    import shutil

    from openjev.tod import Candidate, DecisionSpec, Episode, Kind, build_dataset, picker

    def state(text):
        title, _, body = text.partition("\n\n")
        return {"title": title, "body": body}

    def candidates(_):
        return [Candidate(team, scopes[team], payload=team) for team in TEAMS]

    spec = DecisionSpec("oss-routing", [Kind("team", QUESTION, candidates, version="1")])

    def episodes(rows):
        return [Episode(row["id"], (spec.decision(f"{row['id']}:team", "team", state(row["text"]), choice=row["team"], group_id=row["id"]),)) for row in rows]

    dataset = build_dataset(spec, episodes(train), fractions={"train": 0.8, "validation": 0.1, "calibration": 0.1, "test": 0.0})
    dataset.splits["test"] = build_dataset(spec, episodes(test), fractions={"test": 1.0}).splits["test"]
    data, out = Path(f"/tmp/{quarter}-data"), Path(f"/models/runs/{quarter}")
    dataset.write(data)
    if out.exists():
        shutil.rmtree(out)
    report = picker.finetune(data, out)
    models.commit()

    tod = picker.TodModel(out)
    tod.model.eval()
    temperature = picker.calibrated_temperatures(out)["team"]
    picks = {}
    for decision in picker._rows(data, "test"):
        probabilities = picker._softmax(tod.logits(decision), temperature)
        picks[decision.id.split(":")[0]] = {c.id: float(p) for c, p in zip(decision.candidates, probabilities)}
    return {"picks": picks, "report": report, "temperature": temperature}


@app.local_entrypoint()
def main(quarter: str = "2026Q2"):
    start, end = QUARTERS[quarter]
    pool = json.load(open(DATA / "pool.json"))
    issues = [issue for issue in json.load(open(DATA / "test.json")) if start <= issue["at"] < end]
    train = [row for row in pool if row["at"] < start]
    test = [{"id": f"test-{issue['number']}", "team": issue["team"], "text": issue["text"]} for issue in issues]
    print(quarter, "train", len(train), Counter(row["team"] for row in train), "test", len(test))

    result = train_and_pick.remote(quarter, train, test, json.load(open(Path(__file__).parent / "teams.json")))
    json.dump(result, open(DATA / f"tod-{quarter}.json", "w"))

    right = Counter()
    for issue in issues:
        picked = result["picks"][f"test-{issue['number']}"]
        if max(picked, key=picked.get) == issue["team"]:
            right[issue["answer_from"]] += 1
    totals = Counter(issue["answer_from"] for issue in issues)
    print(quarter, "correct", sum(right.values()), "of", len(issues), {source: f"{right[source]}/{totals[source]}" for source in totals})
