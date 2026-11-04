"""Issue -> code index (turbopuffer, voyage-code-4 + BM25) -> top files -> team, checked against fix PRs."""
import json, os, re, sys, collections as C
from concurrent.futures import ThreadPoolExecutor
HERE=os.path.dirname(os.path.abspath(__file__)); TRIAGE=os.path.dirname(HERE)
sys.path.insert(0,TRIAGE); sys.argv=[sys.argv[0],'--out',TRIAGE]
cwd=os.getcwd(); import team_labeler as TL; os.chdir(cwd)
from tpuf import search
TEAMS=TL.TEAMS
def issue_text(i):
    body=re.sub(r'<!--.*?-->','',i.get('body') or '',flags=re.S)
    body=re.sub(r'```.*?```',lambda m:m.group(0)[:600],body,flags=re.S)
    return (i['title']+'\n\n'+body)[:4000]
def team_from_files(files):
    files=[f for f in files if not TL.GEN.search(f)]
    owners,history,_=TL.file_signals(files)
    score={t:(0.40*owners[t]+0.35*history[t])/0.75 for t in TEAMS}
    r=sorted(score,key=score.get,reverse=True)
    return r[0],score[r[0]],score[r[0]]-score[r[1]],score
def band(s,m): return 'high' if s>=0.40 and m>=0.15 else 'medium' if s>=0.25 and m>=0.08 else 'low'
def run(items, cache):
    todo=[i for i in items if str(i['number']) not in cache]
    with ThreadPoolExecutor(8) as ex:
        for i,res in zip(todo, ex.map(lambda i: search(issue_text(i),100), todo)):
            cache[str(i['number'])]=[p for p,_ in res]
    return cache
if __name__=='__main__':

    gt=json.load(open(os.path.join(HERE,'gt.json')))
    cpath=os.path.join(HERE,'hits_gt.json'); cache=json.load(open(cpath)) if os.path.exists(cpath) else {}
    run(gt,cache); json.dump(cache,open(cpath,'w'))
    rows=[]
    for i in gt:
        pr=i['pr']; lab=TL.label(dict(pr,isDraft=False,authorAssociation=pr.get('authorAssociation') or 'MEMBER',url=pr.get('url','')))
        hits=cache[str(i['number'])]
        prfiles={f['path'] for f in pr['files']['nodes'] if not TL.GEN.search(f['path']) and not f['path'].endswith('_test.go')}
        row=dict(n=i['number'],title=i['title'],truth=lab['top'],truth_conf=lab['confidence'],
                 recall10=len(prfiles & set(hits[:10]))/len(prfiles) if prfiles else None,
                 hit10=bool(prfiles & set(hits[:10])))
        for k in (5,10,20):
            t,s,m,_=team_from_files(hits[:k]); row[f'k{k}']=t; row[f'k{k}_band']=band(s,m)
        rows.append(row)
    json.dump(rows,open(os.path.join(HERE,'eval_rows.json'),'w'))
    trusted=[r for r in rows if r['truth_conf'] in('high','medium')]
    print(f'ground truth: {len(rows)} issues, {len(trusted)} with a confident fix-PR team')
    print('truth teams:',C.Counter(r['truth'] for r in trusted))
    print(f"retrieval: fix-PR file in top 10 for {sum(r['hit10'] for r in trusted)/len(trusted):.0%}")
    for k in (5,10,20):
        acc=sum(r[f'k{k}']==r['truth'] for r in trusted)/len(trusted)
        by=C.defaultdict(list)
        for r in trusted: by[r[f'k{k}_band']].append(r[f'k{k}']==r['truth'])
        print(f'top-{k} files: accuracy {acc:.0%}  '+'  '.join(f"{b} {sum(v)}/{len(v)}={sum(v)/len(v):.0%}" for b,v in sorted(by.items())))
    base=C.Counter(r['truth'] for r in trusted).most_common(1)[0]
    print(f'baseline (always {base[0]}): {base[1]/len(trusted):.0%}')
