import json,random,subprocess,collections,time,sys
fs=json.load(open('/dev0/work/corpus_files.json'));random.seed(1)
inp=''.join(json.dumps({"id":f,"source":open(f).read(),"seed":i,"count":12})+'\n' for i,f in enumerate(random.sample(fs,20)))
t=time.time()
out=subprocess.run(['bundle','exec','ruby','/dev0/gen/mutate.rb'],input=inp,capture_output=True,text=True,cwd='/dev0/ref')
print('secs',time.time()-t, out.stderr[-2000:])
c=collections.Counter()
rows=[json.loads(l) for l in out.stdout.splitlines()]
for r in rows:
    c.update(r['applied']); print(r['ok'],len(r['applied']),r['id'][-50:])
print(c)
open('/dev0/work/mt_out.jsonl','w').write(out.stdout)
