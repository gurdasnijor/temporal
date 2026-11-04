import json, subprocess, sys, time
PR='''number title merged url authorAssociation author{login} repository{nameWithOwner}
   files(first:100){nodes{path}} latestReviews(first:20){nodes{author{login}}}
   reviewRequests(first:10){nodes{requestedReviewer{... on Team{slug} ... on User{login}}}}'''
Q='''query($q:String!,$cursor:String){search(query:$q,type:ISSUE,first:20,after:$cursor){pageInfo{hasNextPage endCursor} nodes{... on Issue{
 number title body state createdAt closedAt labels(first:20){nodes{name}}
 timelineItems(itemTypes:[CLOSED_EVENT,CONNECTED_EVENT,CROSS_REFERENCED_EVENT],last:15){nodes{__typename
   ... on ClosedEvent{closer{__typename ... on PullRequest{%s} ... on Commit{associatedPullRequests(first:1){nodes{%s}}}}}
   ... on ConnectedEvent{subject{__typename ... on PullRequest{%s}}}
   ... on CrossReferencedEvent{willCloseTarget source{__typename ... on PullRequest{%s}}}}}}}}}'''%(PR,PR,PR,PR)
def fetch(q):
    out,cur=[],None
    while True:
        a=["gh","api","graphql","-f","query="+Q,"-f","q="+q]+(["-f","cursor="+cur] if cur else [])
        for i in range(6):
            p=subprocess.run(a,capture_output=True,text=True)
            if p.returncode==0 and '"errors"' not in p.stdout[:200]: break
            time.sleep(8)
        s=json.loads(p.stdout)["data"]["search"]; out+=s["nodes"]
        if not s["pageInfo"]["hasNextPage"]: return out
        cur=s["pageInfo"]["endCursor"]
issues=[]
for y in range(2020,2027):
    for half in [("01-01","06-30"),("07-01","12-31")]:
        q=f"repo:temporalio/temporal is:issue is:closed closed:{y}-{half[0]}..{y}-{half[1]}"
        got=fetch(q); issues+=got; print(q,len(got),file=sys.stderr)
json.dump(issues,open("closed_all.json","w"))
def fix_pr(i):
    best=None
    for n in i["timelineItems"]["nodes"]:
        c=None; strong=False
        if n["__typename"]=="ClosedEvent":
            c=(n.get("closer") or {}); strong=True
            if c.get("__typename")=="Commit": c=((c.get("associatedPullRequests") or {}).get("nodes") or [None])[0] or {}
        elif n["__typename"]=="ConnectedEvent": c=n.get("subject") or {}; strong=True
        elif n["__typename"]=="CrossReferencedEvent": c=n.get("source") or {}; strong=bool(n.get("willCloseTarget"))
        if c and c.get("merged") and (c.get("repository") or {}).get("nameWithOwner")=="temporalio/temporal" and c.get("files"):
            if strong: return c
            best=best or c
    return best
gt=[dict(i,pr=fix_pr(i)) for i in issues if fix_pr(i)]
json.dump(gt,open("gt.json","w")); print("closed",len(issues),"with merged fix PR",len(gt))
