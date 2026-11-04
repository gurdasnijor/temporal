import json, subprocess, sys, time
Q='''query($q:String!,$cursor:String){search(query:$q,type:ISSUE,first:25,after:$cursor){pageInfo{hasNextPage endCursor} nodes{... on Issue{
 number title body createdAt closedAt labels(first:20){nodes{name}}
 timelineItems(itemTypes:[CLOSED_EVENT],last:1){nodes{... on ClosedEvent{closer{__typename ... on PullRequest{
   number title merged url isDraft authorAssociation author{login}
   files(first:100){nodes{path}} latestReviews(first:20){nodes{author{login}}}
   reviewRequests(first:10){nodes{requestedReviewer{... on Team{slug} ... on User{login}}}}} ... on Commit{oid associatedPullRequests(first:1){nodes{number title merged url isDraft authorAssociation author{login}
   files(first:100){nodes{path}} latestReviews(first:20){nodes{author{login}}}
   reviewRequests(first:10){nodes{requestedReviewer{... on Team{slug} ... on User{login}}}}}}}}}}}}}}}'''
out=[]
for window in ["closed:2025-10-30..2026-10-30","closed:2024-10-30..2025-10-29","closed:2023-10-30..2024-10-29"]:
    cur=None
    while True:
        a=["gh","api","graphql","-f","query="+Q,"-f",f"q=repo:temporalio/temporal is:issue is:closed reason:completed {window}"]+(["-f","cursor="+cur] if cur else [])
        for i in range(5):
            p=subprocess.run(a,capture_output=True,text=True)
            if p.returncode==0: break
            time.sleep(5)
        s=json.loads(p.stdout)["data"]["search"]
        out+=s["nodes"]; print(window,len(out),file=sys.stderr)
        if not s["pageInfo"]["hasNextPage"]: break
        cur=s["pageInfo"]["endCursor"]
json.dump(out,open("closed_issues.json","w"))
def closer_pr(i):
    n=(i.get("timelineItems") or {}).get("nodes") or []
    c=(n[0].get("closer") if n else None) or {}
    if c.get("__typename")=="Commit": c=((c.get("associatedPullRequests") or {}).get("nodes") or [None])[0] or {}
    return c if c.get("merged") else None
gt=[dict(i,pr=closer_pr(i)) for i in out if closer_pr(i)]
json.dump(gt,open("gt.json","w"))
print("closed",len(out),"closed by merged PR",len(gt))
