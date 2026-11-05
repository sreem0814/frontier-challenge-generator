import gzip,json,collections,sys
c=collections.Counter(); k=collections.defaultdict(collections.Counter)
for l in gzip.open(sys.argv[1]):
    r=json.loads(l)
    if r['kind']=='dept': continue
    c[r['cops'][0]]+=1; k[r['cops'][0]][r['kind']]+=1
for cop,n in sorted(c.items(),key=lambda x:x[1]):
    print(n,cop,dict(k[cop]))
