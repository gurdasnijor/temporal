"""Combines the two models into a routing rule and scores it against the answer key.

Rule: average the two models' probabilities. If the top team reaches NAME_AT, name it.
Otherwise a person chooses, starting from the top two teams.

    python training/route_rule.py
"""
import json
from pathlib import Path

DATA = Path(".cache/training")
NAME_AT = 0.8
QUARTERS = {
    "Q1": ("2026-01-01", "2026-04-01"),
    "Q2": ("2026-04-01", "2026-07-01"),
    "Q3": ("2026-07-01", "2026-10-01"),
    "Q4": ("2026-10-01", "2027-01-01"),
}
# Each of these issues has a ticket on ACT's board, and the owner is the team whose backlog holds the work.
KEY_CORRECTIONS = {12472: "act", 10520: "act", 10239: "act", 9682: "act"}


def average(first, second):
    return {team: (first[team] + second[team]) / 2 for team in first}


def top_teams(probabilities, count=1):
    return sorted(probabilities, key=probabilities.get, reverse=True)[:count]


def load():
    issues = json.load(open(DATA / "test.json"))
    stock = json.load(open(DATA / "stock-picks.json"))
    embed = json.load(open(DATA / "embed-picks.json"))
    for issue in issues:
        number = str(issue["number"])
        issue["team"] = KEY_CORRECTIONS.get(issue["number"], issue["team"])
        issue["stock"], issue["embed"] = stock[number], embed[number]
        issue["both"] = average(stock[number], embed[number])
    return issues


def right(issues, model):
    return sum(top_teams(issue[model])[0] == issue["team"] for issue in issues)


def report_models(issues):
    print(f"{'Model':<10}{'All':>6}" + "".join(f"{quarter:>6}" for quarter in QUARTERS))
    for model in ("stock", "embed", "both"):
        by_quarter = [right([i for i in issues if start <= i["at"] < end], model) for start, end in QUARTERS.values()]
        print(f"{model:<10}{right(issues, model):>6}" + "".join(f"{score:>6}" for score in by_quarter))


def report_rule(name, issues):
    named = [issue for issue in issues if max(issue["both"].values()) >= NAME_AT]
    unsure = [issue for issue in issues if max(issue["both"].values()) < NAME_AT]
    in_top_two = sum(issue["team"] in top_teams(issue["both"], 2) for issue in unsure)
    print(f"{name}: named {len(named)} of {len(issues)}, right {right(named, 'both')}; "
          f"sent to a person {len(unsure)}, right team in the top two {in_top_two}")


def main():
    issues = load()
    print(f"{len(issues)} issues, {len(KEY_CORRECTIONS)} answers corrected from team boards\n")
    report_models(issues)
    print(f"\nName a team at p >= {NAME_AT}")
    report_rule("January to June", [issue for issue in issues if issue["at"] < "2026-07-01"])
    report_rule("July onward", [issue for issue in issues if issue["at"] >= "2026-07-01"])
    report_rule("All", issues)


if __name__ == "__main__":
    main()
