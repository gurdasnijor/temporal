import json, collections as C
R=json.load(open('rows.json')); T=json.load(open('tiers.json'))
ext=lambda r: r['assoc']!='MEMBER'
iss_count=C.Counter(i for r in R for i in r['issues'])
def bucket(r):
    # first matching rule wins; ordered from most to least deterministic
    if r['author']=='dependabot': return '1 bot (dependabot)'
    if r['cla']=='PENDING' and r['updated']>14: return '3 CLA unsigned >14d'
    if 'stale' in r['labels'] or r['updated']>=180: return '4 stale (labelled or >180d idle)'
    if r['draft'] and r['updated']>60: return '5 draft idle >60d'
    if r['mergeable']=='CONFLICTING' and r['updated']>30: return '6 conflicts, idle >30d'
    if ext(r) and r['ci']=='FAILURE' and r['updated']>30: return '7 external, CI red, idle >30d'
    if any(iss_count[i]>1 for i in r['issues']): return '8 competing PRs for same issue'
    if r['review']=='APPROVED': return '9 approved, not merged'
    if r['base']!='main': return 'S stacked on another branch (follows parent)'
    if not ext(r): return 'M member PR, active (team WIP)'
    if r['review']=='CHANGES_REQUESTED': return 'W external, waiting on author'
    return 'R external, active, needs review'
def show(rows,label):
    c=C.Counter(bucket(r) for r in rows)
    print(f'\n## {label}: {len(rows)}')
    for k in sorted(c): print(f'  {c[k]:4d}  {k}')
show(R,'all open PRs')
M=[r for r in R if T[str(r['n'])][0] in 'ABE']
show(M,'matching candidates (tiers A,B,E)')
A=[r for r in R if T[str(r['n'])][0]=='A']
show(A,'clearly matching (tier A)')
print('\nexternal vs member in A:', C.Counter('member' if not ext(r) else 'external' for r in A))
print('competing-issue groups:', [(i,n) for i,n in iss_count.items() if n>1][:20])
json.dump({r['n']:bucket(r) for r in R},open('buckets.json','w'))
