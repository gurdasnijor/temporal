import json, re, os, collections as C
prs={p['number']:p for p in json.load(open('prs.json'))}
T=json.load(open('tiers.json'))
login=json.load(open('commit_login.json'))
teams=C.defaultdict(set)
for line in open('team_members.tsv'):
    t,l=line.split(); teams[l.lower()].add(t)
def team_of(l):
    if not l: return {'unknown'}
    s=teams.get(l.lower(),set())-{'server'}
    if s: return s
    return {'server-other'} if 'server' in teams.get(l.lower(),()) else {'external'}
GEN=re.compile(r'(\.pb\.go|\.pb\.mock\.go|_mock\.go|_gen\.go|\.gen\.go|go\.sum|go\.mod)$')
file_commits=C.defaultdict(list); dir_commits=C.defaultdict(list)
cur=None
for line in open('gitlog.txt'):
    line=line.strip()
    if line.startswith('@@'): cur=login.get(line[2:]); continue
    if line and not GEN.search(line):
        file_commits[line].append(cur); dir_commits[os.path.dirname(line)].append(cur)
def dist(authors):
    d=C.Counter()
    for a in authors:
        ts=team_of(a)
        for t in ts: d[t]+=1/len(ts)
    s=sum(d.values()); return {k:v/s for k,v in d.items()} if s else {}
res={}
for n,p in prs.items():
    files=[f['path'] for f in p['files']['nodes'] if not GEN.search(f['path'])]
    agg=C.Counter(); used=0
    for f in files:
        a=file_commits.get(f) or dir_commits.get(os.path.dirname(f))
        if not a: continue
        used+=1
        for k,v in dist(a).items(): agg[k]+=v
    hist={k:round(v/used,2) for k,v in agg.most_common()} if used else {}
    au=(p['author'] or {}).get('login')
    revs={r['author']['login'] for r in p['latestReviews']['nodes'] if r['author']} | {(r['requestedReviewer'] or {}).get('login') for r in p['reviewRequests']['nodes']} - {None}
    revteams=C.Counter(t for r in revs for t in team_of(r) if t not in('external','unknown'))
    reqteams=[(r['requestedReviewer'] or {}).get('slug') for r in p['reviewRequests']['nodes'] if (r['requestedReviewer'] or {}).get('slug')]
    res[n]=dict(hist=hist,files_with_history=used,files=len(files),author_teams=sorted(team_of(au)),review_teams=dict(revteams),req_team_slugs=reqteams)
json.dump(res,open('committers.json','w'))
# summary
def top(h):
    h={k:v for k,v in h.items() if k not in('external','unknown','server-other')}
    return max(h,key=h.get) if h else None
c=C.Counter()
for n,r in res.items():
    hm=r['hist'].get('oss-matching',0)
    c['hist matching share >=0.5']+= hm>=0.5
    c['hist matching is top team']+= top(r['hist'])=='oss-matching'
    c['author on oss-matching']+= 'oss-matching' in r['author_teams']
    c['a matching reviewer']+= 'oss-matching' in r['review_teams']
    c['no history for any file']+= r['files_with_history']==0
print(dict(c))
print('author teams:',C.Counter(t for r in res.values() for t in r['author_teams']))
