import json, re, collections as C, datetime as D
prs=json.load(open('prs.json'))
NOW=D.datetime(2026,10,30,tzinfo=D.timezone.utc)
def age(ts): return (NOW-D.datetime.fromisoformat(ts.replace('Z','+00:00'))).days
# CODEOWNERS matcher (last match wins), ignoring the default * and generated-file rules
rules=[]
for line in open('/workspace/worktrees/3ghjzqv8/fluffy-liger/.github/CODEOWNERS'):
    line=line.split('#')[0].strip()
    if not line: continue
    pat,*owners=line.split()
    if pat=='*' : continue
    owners=[o.replace('@temporalio/','') for o in owners]
    anchored=pat.startswith('/'); p=pat.lstrip('/')
    rx=re.escape(p).replace(r'\*\*','.*').replace(r'\*','[^/]*')
    if p.endswith('/'): rx+='.*'
    rx=('^' if anchored else '(^|.*/)')+rx+'$'
    rules.append((re.compile(rx),owners))
GEN=re.compile(r'(\.pb\.go|\.pb\.mock\.go|_mock\.go|_gen\.go|\.gen\.go|go\.sum|go\.mod)$')
def owners(path):
    o=None
    for rx,ow in rules:
        if rx.match(path): o=ow
    return o
# extended matching heuristics for files CODEOWNERS leaves to the default owners
MATCH_EXTRA=re.compile(r'(^tests/.*(versioning|task_queue|taskqueue|matching|deployment|sticky|poller|fairness|priority).*|^service/frontend/.*(versioning|deployment|taskqueue|task_queue).*|^service/history/.*(versioning|task_queue|matching).*|^common/(priorities|testing/taskpoller).*|^service/worker/workerdeployment/.*)', re.I)
MATCH_TITLE=re.compile(r'\b(matching|task ?queue|versioning|deployment|build[- ]?id|poller|sticky|fairness|backlog|partition|nexus endpoint)\b', re.I)
TEAM_LABEL={'oss-foundations':'oss-foundations','team/cgs-foundation':'cgs','teams/cgs':'cgs','team/ha':'cgs'}
rows=[]
for p in prs:
    files=[f['path'] for f in p['files']['nodes']]
    nongen=[f for f in files if not GEN.search(f)]
    teamfiles=C.Counter()
    unowned=0
    for f in nongen:
        o=owners(f)
        if o:
            for t in o: teamfiles[t]+=1
        else: unowned+=1
    extra=sum(1 for f in nongen if not (owners(f) and 'oss-matching' in owners(f)) and MATCH_EXTRA.match(f))
    ctxs={}
    for c in p['commits']['nodes']:
        r=c['commit']['statusCheckRollup']
        if r:
            for n in r['contexts']['nodes']:
                ctxs[n.get('context') or n.get('name')]=n.get('state') or n.get('conclusion') or n.get('status')
    rollup=(p['commits']['nodes'][0]['commit']['statusCheckRollup'] or {}).get('state') if p['commits']['nodes'] else None
    login=(p['author'] or {}).get('login') or 'ghost'
    rows.append(dict(n=p['number'],title=p['title'],author=login,assoc=p['authorAssociation'],draft=p['isDraft'],
        created=age(p['createdAt']),updated=age(p['updatedAt']),files=len(files),nongen=len(nongen),
        add=p['additions'],dele=p['deletions'],teams=dict(teamfiles),unowned=unowned,match_extra=extra,
        title_match=bool(MATCH_TITLE.search(p['title'])),labels=[l['name'] for l in p['labels']['nodes']],
        cla=ctxs.get('license/cla'),ci=rollup,mergeable=p['mergeable'],review=p['reviewDecision'],
        reviews=p['reviews']['totalCount'],comments=p['comments']['totalCount'],
        reqs=[(r['requestedReviewer'] or {}).get('slug') or (r['requestedReviewer'] or {}).get('login') for r in p['reviewRequests']['nodes']],
        issues=[i['number'] for i in p['closingIssuesReferences']['nodes']],body=len(p['body'] or ''),
        fork=(p['headRepository'] or {}).get('nameWithOwner','') != 'temporalio/temporal', base=p['baseRefName']))
json.dump(rows,open('rows.json','w'))
print(len(rows))
