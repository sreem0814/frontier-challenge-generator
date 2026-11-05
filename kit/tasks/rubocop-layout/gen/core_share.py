import gzip,json,collections,sys,re
c=collections.Counter()
for l in gzip.open(sys.argv[1]):
    r=json.loads(l)
    if r['kind']!='dept': c[r['cops'][0]]+=1
tot=sum(c.values())
core=[k for k in c if re.match(r'Layout/(Space|Trailing|Leading|EmptyLine|EmptyLines(?!AroundAccess|AroundArguments|AroundAttribute)|EmptyComment|EndOfLine|InitialIndentation|IndentationStyle|DotPosition|DefEndAlignment|SingleLineBlockChain|ConditionPosition|BlockEndNewline|First\w+LineBreak|Multiline\w+LineBreaks|CommentIndentation)',k)]
cs=sum(c[k] for k in core)
print(len(core),'core cops; unit share',round(cs/tot,3),'equal-cop share',round(len(core)/len(c),3))
print(sorted(core))
