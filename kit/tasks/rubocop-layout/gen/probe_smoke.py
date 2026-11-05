import json,subprocess,time,sys
tree=sys.argv[1]; sel=sys.argv[2]
rows=[l for l in open('/dev0/work/cases_in.jsonl') if json.loads(l)['id'].startswith(sel)][:int(sys.argv[3])]
inp=''.join(json.dumps({k:v for k,v in json.loads(l).items() if k not in('kind','group','origin')})+'\n' for l in rows)
t=time.time()
p=subprocess.run(['bundle','exec','ruby','/dev0/tests/layout_probe.rb'],input=inp,capture_output=True,text=True,cwd=tree)
print('secs',round(time.time()-t,2),'n',len(rows),p.stderr[-1500:])
for l in p.stdout.splitlines()[:int(sys.argv[4]) if len(sys.argv)>4 else 5]:
    r=json.loads(l); print(r['id'],r['error'],r['iterations'],{k:len(v) for k,v in r['offenses'].items()})
