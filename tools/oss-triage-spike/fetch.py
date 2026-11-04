import json, subprocess, sys
PRQ = '''query($cursor:String){ repository(owner:"temporalio",name:"temporal"){ pullRequests(states:OPEN, first:10, after:$cursor){ pageInfo{hasNextPage endCursor} nodes{
 number title url isDraft createdAt updatedAt author{login} authorAssociation additions deletions changedFiles
 baseRefName headRepository{nameWithOwner} mergeable reviewDecision
 labels(first:20){nodes{name}} files(first:100){nodes{path}}
 comments{totalCount} reviews{totalCount} reviewRequests(first:10){nodes{requestedReviewer{... on Team{slug} ... on User{login}}}}
 closingIssuesReferences(first:5){nodes{number}}
 latestReviews(first:10){nodes{author{login} state submittedAt}}
 timelineItems(last:1){nodes{__typename}}
 commits(last:1){nodes{commit{committedDate statusCheckRollup{state contexts(first:40){nodes{... on StatusContext{context state} ... on CheckRun{name conclusion status}}}}}}}
 body
}}}}'''
ISQ = '''query($cursor:String){ repository(owner:"temporalio",name:"temporal"){ issues(states:OPEN, first:50, after:$cursor){ pageInfo{hasNextPage endCursor} nodes{
 number title url createdAt updatedAt author{login} authorAssociation labels(first:20){nodes{name}} comments{totalCount}
 assignees(first:5){nodes{login}} body
}}}}'''
def run(q, key):
    out, cur = [], None
    while True:
        args = ["gh","api","graphql","-f",f"query={q}"] + (["-f",f"cursor={cur}"] if cur else [])
        for attempt in range(5):
            p = subprocess.run(args, capture_output=True, text=True)
            if p.returncode == 0: break
            print("retry", attempt, p.stderr[:300], file=sys.stderr); import time; time.sleep(5)
        r = json.loads(p.stdout)
        conn = r["data"]["repository"][key]
        out += conn["nodes"]
        print(key, len(out), file=sys.stderr)
        if not conn["pageInfo"]["hasNextPage"]: return out
        cur = conn["pageInfo"]["endCursor"]
json.dump(run(PRQ,"pullRequests"), open(sys.argv[1]+"/prs.json","w"))
json.dump(run(ISQ,"issues"), open(sys.argv[1]+"/issues.json","w"))
