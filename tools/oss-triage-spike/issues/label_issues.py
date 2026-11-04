"""Label open temporalio/temporal issues by team: linked open PR's team if any, else code-search routing."""
import json, os, sys, csv, collections as C
sys.argv=['x']; import issue_eval as E
HERE=E.HERE; TL=E.TL
def route(files, k=20):
    files=[f for f in files[:k] if not TL.GEN.search(f)]
    s=C.Counter(); wsum=0
    for rank,f in enumerate(files):
        o,h,_=TL.file_signals([f]); w=1/(rank+1); wsum+=w
        for t in E.TEAMS: s[t]+=w*(0.40*o[t]+0.35*h[t])/0.75
    s={t:s[t]/wsum for t in E.TEAMS} if wsum else {t:0 for t in E.TEAMS}
    r=sorted(s,key=s.get,reverse=True)
    return r[0], s[r[0]], s[r[0]]-s[r[1]]
def band(s,m): return 'high' if s>=0.35 and m>=0.12 else 'medium' if s>=0.22 and m>=0.06 else 'low'
LABEL_TEAM={'oss-foundations':'oss-foundations','teams/cgs':'cgs','schedules':'act','CRON':'act','oss-act':'act','matching':'oss-matching','versioning':'oss-matching','visibility':'oss-foundations','archival':'oss-foundations'}
if __name__=='__main__':
    # calibrate bands on ground truth
    rows={r['n']:r for r in json.load(open(os.path.join(HERE,'eval_rows.json')))}; hits=json.load(open(os.path.join(HERE,'hits_gt.json')))
    by=C.defaultdict(list)
    for n,r in rows.items():
        if r['truth_conf'] in('high','medium'):
            t,s,m=route(hits[str(n)]); by[band(s,m)].append(t==r['truth'])
    print('ground-truth accuracy by band:','  '.join(f"{b} {sum(v)}/{len(v)}={sum(v)/len(v):.0%}" for b,v in sorted(by.items())))
    issues=json.load(open(os.path.join(os.path.dirname(HERE),'issues.json')))
    labels={r['number']:r for r in json.load(open(os.path.join(os.path.dirname(HERE),'labels.json')))}
    prs=json.load(open(os.path.join(os.path.dirname(HERE),'prs.json')))
    linked=C.defaultdict(list)
    for p in prs:
        for i in p['closingIssuesReferences']['nodes']: linked[i['number']].append(p['number'])
    cpath=os.path.join(HERE,'hits_open.json'); cache=json.load(open(cpath)) if os.path.exists(cpath) else {}
    E.run(issues,cache); json.dump(cache,open(cpath,'w'))
    out=[]
    for i in issues:
        t,s,m=route(cache[str(i['number'])]); b=band(s,m)
        lt=[LABEL_TEAM[l['name']] for l in i['labels']['nodes'] if l['name'] in LABEL_TEAM]
        prl=[labels[n] for n in linked.get(i['number'],[]) if n in labels]
        if prl: team,src=prl[0]['team'],'linked PR #'+','.join(str(p['number']) for p in prl)
        elif lt: team,src=lt[0],'existing label'
        elif b!='low': team,src=t,f'code search ({b})'
        else: team,src='oss-foundations',f'catch-all (code search guessed {t})'
        top=cache[str(i['number'])][:3]
        out.append(dict(number=i['number'],title=i['title'],team=team,source=src,code_search_team=t,code_search_band=b,label_team=lt[0] if lt else '',
             linked_prs=' '.join(map(str,linked.get(i['number'],[]))),top_files=' '.join(top),updated=i['updatedAt'][:10],url=i['url']))
    with open(os.path.join(HERE,'issue_labels.csv'),'w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    json.dump(out,open(os.path.join(HERE,'issue_labels.json'),'w'),indent=1)
    print('open issues:',len(out)); print('by team:',C.Counter(r['team'] for r in out).most_common())
    print('by source:',C.Counter(r['source'].split(' #')[0].split(' (')[0] for r in out))
    agree=[r for r in out if r['label_team']]; print(f"existing team label vs code search: {sum(r['label_team']==r['code_search_team'] for r in agree)}/{len(agree)} agree")
    print('issues with a linked open PR:',sum(1 for r in out if r['linked_prs']))
