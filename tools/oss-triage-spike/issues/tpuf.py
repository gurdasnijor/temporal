import json, os, re, sys, urllib.request
KEY=os.environ['TPUF_KEY']; URL='https://gcp-us-west1.turbopuffer.com/v2/namespaces/vault-code-temporal/query'
STOP=set('the a an and or of to in for on with is are be this that it as at by from we i you not when if can should would could has have was were will do does into via but so any all our its'.split())
def terms(q): return ' '.join(w for w in re.findall(r'[A-Za-z][A-Za-z0-9_]+',q) if w.lower() not in STOP)[:1000]
def search(q, k=100):
    ex=["embed_text","fts","hash","title","text"]
    qs=[{"rank_by":["text","ANN",["Embed",q[:8000]]],"top_k":k,"exclude_attributes":ex}]
    t=terms(q)
    if t: qs.append({"rank_by":["fts","BM25",t],"top_k":k,"exclude_attributes":ex})
    body={"queries":qs,"rerank_by":["RRF"]} if t else {"queries":qs}
    req=urllib.request.Request(URL,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+KEY,'Content-Type':'application/json'})
    r=json.load(urllib.request.urlopen(req,timeout=60))
    seen=[]; 
    for row in r['results'][0]['rows']:
        if row['path'] not in [s[0] for s in seen]: seen.append((row['path'],row['$dist']))
    return seen
if __name__=='__main__':
    for p,d in search(sys.argv[1])[:10]: print(f'{d:.4f} {p}')
