"""V0.2 domain services. SQL-backed graph traversals; no fabricated ancestry."""
import json,re,hashlib,sqlite3,io,csv,zipfile
from collections import deque,defaultdict
from rapidfuzz.fuzz import token_sort_ratio
from .app import db,uid,now,person,create_person,audit,ROOT,DATA,DB
TABLES=['people','edges','evidence','dna','matches','photos','imports','identities','tasks','audit','sources','markers','duplicate_reviews','shared_matches','branches','famous','findings','ancient_samples','ancient_comparisons','events','notifications','import_history','settings']
def migrate():
    with db() as c:
        old=c.execute('SELECT 1 FROM migrations WHERE version=2').fetchone()
        if not old and c.execute('SELECT count(*) FROM people').fetchone()[0]>0:
            backup=DATA/'worldtree.pre_v02.sqlite'
            if not backup.exists():
                target=sqlite3.connect(backup);c.backup(target);target.close()
        c.executescript((ROOT/'backend/schema_v02.sql').read_text())
def rows(c,sql,args=()):return [dict(r) for r in c.execute(sql,args)]
def ancestry(c,p,limit=20000,max_paths=8):
    # A bounded set of alternative ancestor paths, not all exponentially many paths.
    found=defaultdict(list);found[p]=[[p]];todo=deque([(p,[p])]);visited=0;truncated=False
    while todo:
        x,path=todo.popleft();visited+=1
        if visited>limit:truncated=True;break
        for r in c.execute("SELECT a FROM edges WHERE b=? AND kind='parent' AND status='documented'",(x,)):
            a=r[0]
            if a in path:continue
            if len(found[a])<max_paths:found[a].append(path+[a]);todo.append((a,path+[a]))
            else:truncated=True
    return found,truncated

def label(da,dbb,half=False):
    if da==dbb==0:return 'Same person'
    if min(da,dbb)==0:
        n=max(da,dbb);up=da==0;word='parent' if up else 'child'
        return word.capitalize() if n==1 else ('Grandparent' if up else 'Grandchild') if n==2 else f'{n-2}× great-grand'+word
    if da==dbb==1:return 'Half-siblings' if half else 'Siblings'
    if min(da,dbb)==1:
        return ('Great-'*max(0,abs(da-dbb)-1))+('Aunt/uncle' if da<dbb else 'Niece/nephew')
    n=min(da,dbb)-1;suffix='th' if 10<=n%100<=20 else {1:'st',2:'nd',3:'rd'}.get(n%10,'th')
    return f'{n}{suffix} cousins'+(f', {abs(da-dbb)} time(s) removed' if da!=dbb else '')

def calculate(c,a,b):
    person(c,a);person(c,b)
    if a==b:return {'classification':'same person','relationships':[{'label':'Same person','path':[a]}],'truncated':False}
    aa,ta=ancestry(c,a);bb,tb=ancestry(c,b);common=set(aa)&set(bb);result=[];seen=set()
    def parents(p):return {r[0] for r in c.execute("SELECT a FROM edges WHERE b=? AND kind='parent' AND status='documented'",(p,))}
    pa,pb=parents(a),parents(b)
    for root in sorted(common,key=lambda x:min(map(len,aa[x]))+min(map(len,bb[x]))):
        for xa in aa[root]:
            for xb in bb[root]:
                # Reject redundant paths whose branches meet before the selected ancestor.
                if set(xa[:-1])&set(xb[:-1]):continue
                da,dbb=len(xa)-1,len(xb)-1;path=xa+list(reversed(xb[:-1]));signature=tuple(path)
                if signature in seen:continue
                seen.add(signature);half=len(pa)==len(pb)==2 and len(pa&pb)==1
                title=label(da,dbb,half)
                if da==dbb==1 and len(pa&pb)==1 and not half:title='Siblings; full/half status undetermined'
                edges=[]
                for child,parent_id in list(zip(xa,xa[1:]))+list(zip(xb,xb[1:])):
                    edges.extend(rows(c,"SELECT * FROM edges WHERE a=? AND b=? AND kind='parent' AND status='documented'",(parent_id,child)))
                result.append({'label':title,'classification':'biological genealogy','common_ancestor':root,'generations':[da,dbb],'path':path,'evidence':edges,'status':'documented'})
                if len(result)>=32:break
            if len(result)>=32:break
        if len(result)>=32:break
    if result:return {'classification':'biological genealogy','relationships':result,'truncated':ta or tb or len(result)>=32,'note':'Recorded descent, not independent DNA proof. Up to 8 paths per ancestor and 32 results.'}
    todo=deque([(a,[a],[])]);seen={a}
    while todo and len(seen)<20000:
        x,path,es=todo.popleft()
        for e in rows(c,"SELECT * FROM edges WHERE (a=? OR b=?) AND status='documented'",(x,x)):
            y=e['b'] if e['a']==x else e['a']
            if y==b:
                all_edges=es+[e];kinds={v['kind'] for v in all_edges}
                cl='through marriage/partnership' if 'partner' in kinds else 'adoptive/nonbiological'
                return {'classification':cl,'relationships':[{'label':'Family connection '+cl,'path':path+[b],'evidence':all_edges,'status':'documented'}],'truncated':False}
            if y not in seen:seen.add(y);todo.append((y,path+[y],es+[e]))
    return {'classification':'unknown','relationships':[],'message':'No documented connection found in the available WorldTree data.','truncated':ta or tb or len(seen)>=20000}

def duplicate_candidates(c,limit=100):
    # Indexed surname blocking, generated once and maintained in people mutations by trigger.
    result=[]
    groups=c.execute('SELECT surname FROM person_blocks GROUP BY surname HAVING count(*)>1 AND count(*)<=200 ORDER BY count(*),surname').fetchall()
    for group in groups:
        ps=rows(c,'SELECT p.* FROM people p JOIN person_blocks b ON p.id=b.person WHERE b.surname=?',(group[0],))
        for i,a in enumerate(ps):
            for b in ps[i+1:]:
                state=c.execute('SELECT state FROM duplicate_reviews WHERE a=? AND b=?',tuple(sorted([a['id'],b['id']]))).fetchone()
                if state and state[0] in ('rejected','separate'):continue
                score=token_sort_ratio(a['name'].lower(),b['name'].lower());support=[];conflicts=[]
                if score<65:continue
                for field in ('birth','death','place'):
                    if a[field] and b[field]:
                        if a[field].casefold()==b[field].casefold():score+=8;support.append(field+' agrees')
                        else:conflicts.append(field+' differs')
                ids=[]
                for p in (a,b):ids.append(rows(c,'SELECT namespace,external_id FROM identities WHERE person=?',(p['id'],)))
                parents=[{r[0] for r in c.execute("SELECT a FROM edges WHERE b=? AND kind='parent'",(p['id'],))} for p in (a,b)]
                if parents[0]&parents[1]:support.append('shared recorded parent');score+=15
                result.append({'a':a,'b':b,'score':round(min(score,100),1),'support':support,'conflicts':conflicts,'identities':ids,'state':state[0] if state else 'review needed','note':'Heuristic ranking, not identity probability'})
                if len(result)>=limit:return sorted(result,key=lambda x:-x['score'])
    return sorted(result,key=lambda x:-x['score'])

def init_blocks():
    with db() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS person_blocks(person TEXT PRIMARY KEY REFERENCES people(id) ON DELETE CASCADE,surname TEXT);
CREATE INDEX IF NOT EXISTS surname_block ON person_blocks(surname);
CREATE TRIGGER IF NOT EXISTS people_block_insert AFTER INSERT ON people BEGIN INSERT OR REPLACE INTO person_blocks VALUES(NEW.id,lower(trim(NEW.name))); END;
CREATE TRIGGER IF NOT EXISTS people_block_update AFTER UPDATE OF name ON people BEGIN UPDATE person_blocks SET surname=lower(trim(NEW.name)) WHERE person=NEW.id; END;''')
        # Block by normalized full name initially; fuzzy surname indexing refreshed for candidate query.
        c.executemany('INSERT OR REPLACE INTO person_blocks VALUES(?,?)',[(r['id'],r['name'].split()[-1].casefold()) for r in c.execute('SELECT id,name FROM people') if r['name'].split()])

def snapshot(c):
    out={}
    import base64
    for t in TABLES:
        out[t]=[{k:({'_blob':base64.b64encode(v).decode()} if isinstance(v,bytes) else v) for k,v in dict(r).items()} for r in c.execute('SELECT * FROM '+t)]
    return json.dumps(out,sort_keys=True,separators=(',',':')).encode()
def digest(c):return hashlib.sha256(snapshot(c)).hexdigest()

def merge(c,keep,remove,reason,cipher):
    a,b=person(c,keep),person(c,remove)
    if keep==remove or not reason.strip():raise ValueError('Review reason and two different profiles required')
    if calculate(c,keep,remove)['classification']!='unknown':raise ValueError('Connected profiles require manual graph review before merging')
    # Restrict merging where any uncertain ancestry path exists to avoid creating cycles.
    seen={keep};todo=[keep]
    while todo:
        x=todo.pop()
        for r in c.execute('SELECT a,b FROM edges WHERE a=? OR b=?',(x,x)):
            y=r[1] if r[0]==x else r[0]
            if y==remove:raise ValueError('Merge would alter an existing family path; review links first')
            if y not in seen:seen.add(y);todo.append(y)
    before=snapshot(c)
    for t,col in [('dna','person'),('photos','person'),('evidence','person'),('tasks','person'),('identities','person'),('matches','person'),('matches','owner'),('markers','person'),('branches','person'),('branches','owner'),('famous','person'),('findings','person'),('events','person'),('ancient_comparisons','person'),('notifications','person'),('shared_matches','owner'),('shared_matches','a'),('shared_matches','b')]:
        c.execute(f'UPDATE {t} SET {col}=? WHERE {col}=?',(keep,remove))
    for col in ('a','b'):c.execute(f'UPDATE edges SET {col}=? WHERE {col}=?',(keep,remove))
    c.execute('UPDATE people SET notes=notes || ? WHERE id=?',('\nSource profile preserved: '+json.dumps(b),keep));c.execute('DELETE FROM people WHERE id=?',(remove,));c.execute('DELETE FROM duplicate_reviews WHERE a=? OR b=?',(remove,remove))
    audit(c,'v02 merge reviewed',{'keep':keep,'remove':remove,'reason':reason});ident=uid()
    c.execute('INSERT INTO merge_history VALUES(?,?,?,?,?,?,0)',(ident,now(),keep,remove,cipher.encrypt(before),digest(c)));return {'merge_id':ident,'note':'Undo allowed only before further data changes; encrypted pre-merge snapshot retained.'}

def undo_merge(c,ident,cipher):
    r=c.execute('SELECT * FROM merge_history WHERE id=? AND undone=0',(ident,)).fetchone()
    if not r:raise ValueError('Merge not found')
    if digest(c)!=r['after_digest']:raise ValueError('Database changed since merge. Restore the pre-merge snapshot into a separate vault to avoid overwriting newer work.')
    import base64
    data=json.loads(cipher.decrypt(r['snapshot']))
    # Defer referential integrity across delete/reinsert within this transaction.
    c.execute('PRAGMA defer_foreign_keys=ON')
    for t in reversed(TABLES):c.execute('DELETE FROM '+t)
    for t in TABLES:
        for row in data[t]:
            vals=[base64.b64decode(v['_blob']) if isinstance(v,dict) and '_blob'in v else v for v in row.values()]
            c.execute('INSERT INTO '+t+'('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',vals)
    c.execute('UPDATE merge_history SET undone=1 WHERE id=?',(ident,));audit(c,'merge undone',{'id':ident});return {'ok':True}

def cluster(c,owner):
    person(c,owner);links=rows(c,'SELECT * FROM shared_matches WHERE owner=?',(owner,));adj=defaultdict(set)
    for e in links:adj[e['a']].add(e['b']);adj[e['b']].add(e['a'])
    seen=set();groups=[]
    for start in adj:
        if start in seen:continue
        todo=[start];seen.add(start);g=[]
        while todo:
            x=todo.pop();g.append(x)
            for y in adj[x]:
                if y not in seen:seen.add(y);todo.append(y)
        groups.append(g)
    return {'groups':groups,'evidence':links,'interpretation':'Connected components of supplied shared-match reports only; not proven ancestral branches or segment triangulation.'}

def gaps(c,p):
    v=person(c,p);parents=rows(c,"SELECT a,status FROM edges WHERE b=? AND kind='parent'",(p,))
    return {'person':v,'missing_fields':[f for f in ('birth','place') if not v[f]],'recorded_parents':len(parents),'parent_slots_unresolved':max(0,2-len([x for x in parents if x['status']=='documented'])),'hypothetical_links':rows(c,"SELECT * FROM edges WHERE (a=? OR b=?) AND status!='documented'",(p,p))}

def sample_import(c,data,dataset,version,license,citation,allowed_ids=None):
    if not all([dataset,version,license,citation]):raise ValueError('Dataset, version, reuse terms, citation required')
    text=data.decode('utf-8-sig');reader=csv.DictReader(io.StringIO(text),delimiter='\t' if '\t' in text.splitlines()[0] else ',');count=0
    for row in reader:
        def get(*names):
            for n in names:
                if row.get(n):return row[n]
            # AADR annotation headings include longer descriptions; explicit prefixes only.
            for k,v in row.items():
                if k and any(k.startswith(n) for n in names) and v:return v
            return ''
        sample=get('sample_id','Genetic ID','Master ID')
        if not sample:raise ValueError('Sample ID / Genetic ID header required')
        if allowed_ids and sample not in allowed_ids:continue
        age=get('age','Date mean','Age','Average of 95.4% date range')
        if not age:raise ValueError('Archaeological age/date metadata required; modern sample import is not supported here')
        # Canonical form requires a user-declared ancient sample; AADR filter excludes modern 0 BP.
        if age.strip() in ('0','0.0','modern','Modern'):continue
        values=(uid(),dataset,version,sample,get('site','Locality'),get('country','Country'),get('period','Group ID'),age,get('sex','Genetic sex'),get('haplogroup','Y haplogroup'),get('build') or 'unknown',license,citation,json.dumps(row))
        n=c.execute('INSERT OR IGNORE INTO ancient_samples VALUES('+','.join('?'for _ in values)+')',values).rowcount;count+=n
    return {'indexed':count,'analysis':'Metadata only; no genetic relationship inferred'}

def compare_markers(modern,ancient,build_a,build_b,strand_a='forward',strand_b='forward'):
    if build_a=='unknown' or build_a!=build_b:raise ValueError('Known identical genome builds required; liftover is not implemented')
    if strand_a not in ('forward','reverse') or strand_b not in ('forward','reverse'):raise ValueError('Known strand metadata required')
    complement=str.maketrans('ACGT','TGCA');a={k:v for k,v in modern.items()};b={k:v.translate(complement) if strand_a!=strand_b else v for k,v in ancient.items()};compared=agree=ambiguous=missing=0
    for k in a.keys()&b.keys():
        x,y=a[k],b[k]
        if not set(x+y)<=set('ACGT') or len(x)!=2 or len(y)!=2:missing+=1;continue
        if set(x+y) in ({'A','T'},{'C','G'}):ambiguous+=1;continue
        compared+=1;agree+=sorted(x)==sorted(y)
    return {'method':'Exploratory diploid genotype concordance','overlapping_compatible_markers':compared,'identical_genotypes':agree,'agreement':agree/compared if compared else None,'excluded_ambiguous':ambiguous,'excluded_missing_or_haploid':missing,'evidence_type':'technical marker similarity','direct_ancestor_claim':False,'limitations':'Not population affinity, IBD, kinship, or direct ancestry. Ancient pseudo-haploid calls excluded. No validated PCA model installed.'}
