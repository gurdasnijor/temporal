"""Builds the rows Jev trains on, from the vault. Reads only.

A row is the text of one piece of work and the team that owns it. There are two kinds:

    ticket      a team's Jira or Linear ticket; the project names the team
    open issue  a GitHub issue whose Area has a suggested team, high or medium confidence

Anything that could give away a test issue is left out.

    VAULT_PSQL="psql $VAULT_URL" python training/labels.py
"""
import csv
import difflib
import json
import os
import re
import shlex
import subprocess
from collections import Counter
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

DATA = Path(".cache/training")
SINCE = "2023-11-01"
MIN_DESCRIPTION = 40

TEAM_OF_PROJECT = {
    "ACT": "act",
    "NEXUS": "nexus",
    "OSSM": "oss-matching",
    "MTC": "oss-matching",
    "OSSF": "oss-foundations",
    "CGSRF": "cgs",
    "CGS": "cgs",
}
# OSS is an umbrella project, so its tickets go by the team of the person assigned.
TEAM_OF_ASSIGNEE = {
    "Matching Service": "oss-matching",
    "OSS Foundations": "oss-foundations",
    "Application Components": "act",
    "Nexus": "nexus",
    "CGS Replication Foundations": "cgs",
}

TICKETS = f"""
    select i.key as id, i.created as at, i.summary as title, left(i.description, 4000) as body,
           p.key as project, person.team as assignee_team
    from jira.issues i
    join jira.projects p on p.id = i.project_id
    left join people.people person on person.jira = i.assignee_account_id
    where i.created >= '{SINCE}'
    union all
    select identifier, created_at, title, left(description, 4000), team__key, null
    from linear.issues
    where created_at >= '{SINCE}'
"""
ISSUES = "select number, created_at as at, title, left(body, 4000) as body from github.issues where repo = 'temporal'"
ISSUE_LINK = re.compile(r"(?:temporalio/temporal/(?:issues|pull)/|temporal#|GitHub #)(\d+)")


def query(sql):
    psql = shlex.split(os.environ["VAULT_PSQL"])
    wrapped = f"select json_agg(row) from ({sql}) row"
    return json.loads(subprocess.run([*psql, "-At", "-c", wrapped], capture_output=True, text=True, check=True).stdout)


def text_of(row):
    return f"{row['title'] or ''}\n\n{row['body'] or ''}"


def title_of(text):
    return text.split("\n\n")[0]


def team_of(ticket):
    if ticket["project"] == "OSS":
        return TEAM_OF_ASSIGNEE.get(ticket["assignee_team"])
    return TEAM_OF_PROJECT.get(ticket["project"])


def tickets(test):
    test_numbers = {issue["number"] for issue in test}
    rows = []
    for ticket in query(TICKETS):
        team, text = team_of(ticket), text_of(ticket)
        links_a_test_issue = {int(n) for n in ISSUE_LINK.findall(text)} & test_numbers
        if team and len(ticket["body"] or "") >= MIN_DESCRIPTION and not links_a_test_issue:
            rows.append({"id": ticket["id"], "at": ticket["at"], "team": team, "text": text, "source": "ticket"})
    # Some ACT tickets moved from Jira to Linear with the same key and appear in both.
    return without_copies_of(test, list({row["id"]: row for row in rows}.values()))


def without_copies_of(test, rows):
    """Some tickets are copies of GitHub issues. Shortlists by word overlap, then compares titles exactly."""
    test_titles = [title_of(issue["text"]) for issue in test]
    row_titles = [title_of(row["text"]) for row in rows]
    vectors = TfidfVectorizer(sublinear_tf=True).fit(test_titles + row_titles)
    similarity = linear_kernel(vectors.transform(test_titles), vectors.transform(row_titles))
    copies = set()
    for title, scores in zip(test_titles, similarity):
        for index in scores.argsort()[::-1][:5]:
            if difflib.SequenceMatcher(None, title.lower(), row_titles[index].lower()).ratio() > 0.8:
                copies.add(index)
    print(f"dropped {len(copies)} tickets copying a test issue")
    return [row for index, row in enumerate(rows) if index not in copies]


def open_issues(test):
    test_numbers = {issue["number"] for issue in test}
    issues = {issue["number"]: issue for issue in query(ISSUES)}
    rows = []
    for label in csv.DictReader(open(DATA / "area_labels.csv")):
        number = int(label["number"])
        if label["confidence"] in ("high", "medium") and number in issues and number not in test_numbers:
            issue = issues[number]
            rows.append({"id": f"issue-{number}", "at": issue["at"], "team": label["team"], "text": text_of(issue), "source": "open issue"})
    return rows


def main():
    test = json.load(open(DATA / "test.json"))
    rows = tickets(test) + open_issues(test)
    json.dump(rows, open(DATA / "pool.json", "w"))
    print(Counter((row["source"], row["team"]) for row in rows))


if __name__ == "__main__":
    main()
