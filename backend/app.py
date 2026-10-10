import os,json,sqlite3,uuid,hashlib,secrets,base64,io,zipfile
from pathlib import Path
from datetime import datetime,timezone
from collections import deque
from contextlib import contextmanager
from fastapi import FastAPI,Request,HTTPException,UploadFile,File,Form
from fastapi.responses import FileResponse,Response,JSONResponse
from fastapi.staticfiles import StaticFiles
from cryptography.fernet import Fernet,InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from PIL import Image,ImageOps
from .parsers import dna_parse,relatives_parse,gedcom_parse
ROOT=Path(__file__).resolve().parents[1]; DATA=Path(os.getenv('WORLDTREE_DATA',str(ROOT/'data'))); DATA.mkdir(exist_ok=True,parents=True)
DB=DATA/'worldtree.sqlite'; sessions={}; app=FastAPI(title='WorldTree AI — Connected Ancestry',docs_url=None,redoc_url=None)
def now(): return datetime.now(timezone.utc).isoformat()
def uid(): return str(uuid.uuid4())
@contextmanager
def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON')
    try: yield c; c.commit()
    except: c.rollback(); raise
    finally: c.close()
with db() as c: c.executescript((ROOT/'backend/schema.sql').read_text())
def audit(c,action,details): c.execute('INSERT INTO audit(at,action,details) VALUES(?,?,?)',(now(),action,json.dumps(details)))
def person(c,p):
    r=c.execute('SELECT * FROM people WHERE id=?',(p,)).fetchone()
    if not r: raise HTTPException(404,'Person not found')
    return dict(r)
def create_person(c,d):
    p=uid(); keys=['name','birth','death','place','aliases','notes','status','living','private','synthetic']
    vals=[d.get(k,{'status':'hypothesis','living':1,'private':1,'synthetic':0}.get(k,'')) for k in keys]
    if not str(vals[0]).strip(): raise HTTPException(422,'Name required')
    vals[8]=1 # v0.1 is entirely private
    c.execute('INSERT INTO people(id,'+','.join(keys)+') VALUES('+','.join('?' for _ in range(11))+')',[p]+vals); return p
@app.middleware('http')
async def security(req,call_next):
    host=req.headers.get('host','').split(':')[0]
    if host not in ('127.0.0.1','localhost','testserver'): return JSONResponse({'detail':'Local access only'},403)
    origin=req.headers.get('origin')
    if origin and origin not in ('http://127.0.0.1:8765','http://localhost:8765'): return JSONResponse({'detail':'Origin denied'},403)
    if req.url.path.startswith('/api/') and req.url.path not in ('/api/unlock','/api/status'):
        token=req.cookies.get('wt_session'); s=sessions.get(token)
        if not s: return JSONResponse({'detail':'Unlock your local vault'},401)
        req.state.fernet=s
    response=await call_next(req)
    if req.url.path.startswith('/api/import/'):
        with db() as c:c.execute('INSERT INTO import_history VALUES(?,?,?,?,?,?,?)',(uid(),req.url.path.rsplit('/',1)[-1],'user upload',int(req.headers.get('content-length','0')),'complete' if response.status_code<400 else 'failed',json.dumps({'http_status':response.status_code}),now()))
    response.headers['X-Content-Type-Options']='nosniff'; response.headers['Cache-Control']='no-store'
    response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
    return response
@app.exception_handler(sqlite3.IntegrityError)
async def integrity_error(req,exc):
    return JSONResponse({'detail':'Conflicting identifiers or missing referenced profile; no changes committed. Review the source records.'},409)
@app.get('/api/status')
def status(): return {'initialized':(DATA/'vault.json').exists(),'version':'0.1.0'}
@app.post('/api/unlock')
def unlock(d:dict):
    password=d.get('password','')
    if len(password)<12: raise HTTPException(422,'Use a passphrase of at least 12 characters')
    f=DATA/'vault.json'; cfg=json.loads(f.read_text()) if f.exists() else {'salt':base64.b64encode(os.urandom(16)).decode()}
    key=base64.urlsafe_b64encode(Scrypt(salt=base64.b64decode(cfg['salt']),length=32,n=2**15,r=8,p=1).derive(password.encode())); cipher=Fernet(key)
    if 'check' in cfg:
        try: cipher.decrypt(cfg['check'].encode())
        except InvalidToken: raise HTTPException(403,'Incorrect passphrase')
    else:
        cfg['check']=cipher.encrypt(b'worldtree-v1').decode(); f.write_text(json.dumps(cfg)); os.chmod(f,0o600)
    token=secrets.token_urlsafe(32); sessions[token]=cipher
    r=JSONResponse({'ok':True}); r.set_cookie('wt_session',token,httponly=True,samesite='strict'); return r
@app.post('/api/lock')
def lock(req:Request):
    from .familysearch import bridge
    bridge.disconnect(req.cookies.get('wt_session')); sessions.pop(req.cookies.get('wt_session'),None); r=JSONResponse({'ok':True}); r.delete_cookie('wt_session'); return r
@app.get('/api/people')
def people(q:str='',offset:int=0,limit:int=100):
    limit=max(1,min(limit,200)); offset=max(offset,0)
    with db() as c: return {'items':[dict(r) for r in c.execute('SELECT * FROM people WHERE name LIKE ? ORDER BY name,id LIMIT ? OFFSET ?',('%'+q+'%',limit,offset))],'total':c.execute('SELECT count(*) FROM people WHERE name LIKE ?',('%'+q+'%',)).fetchone()[0]}
@app.post('/api/people')
def add_person(d:dict):
    with db() as c:
        p=create_person(c,d); audit(c,'person created',{'id':p}); return {'id':p}
@app.get('/api/people/{p}')
def detail(p:str):
    with db() as c:
        result=person(c,p)
        for table in ('evidence','photos','dna','tasks'):
            cols={'photos':'id,person,permission','dna':'id,person,provider,build,markers,consent,authority,created'}.get(table,'*')
            result[table]=[dict(r) for r in c.execute(f'SELECT {cols} FROM {table} WHERE person=?',(p,))]
        return result
@app.patch('/api/people/{p}')
def edit(p:str,d:dict):
    with db() as c:
        person(c,p)
        for k in ('name','birth','death','place','aliases','notes','status','living'):
            if k in d: c.execute(f'UPDATE people SET {k}=? WHERE id=?',(d[k],p))
        audit(c,'profile edited',{'id':p}); return {'ok':True}
@app.post('/api/edges')
def edge(d:dict):
    if d.get('kind') not in ('parent','adoptive parent','partner'): raise HTTPException(422,'Unsupported relationship type')
    if d['a']==d['b']: raise HTTPException(422,'Self relationship rejected')
    if d.get('status')=='documented' and not d.get('citation'): raise HTTPException(422,'Documented edges need a citation')
    with db() as c:
        person(c,d['a']);person(c,d['b'])
        if d['kind'] in ('parent','adoptive parent'):
            rows=c.execute("WITH RECURSIVE descendants(id) AS (SELECT b FROM edges WHERE a=? AND kind IN ('parent','adoptive parent') UNION SELECT e.b FROM edges e JOIN descendants d ON e.a=d.id WHERE e.kind IN ('parent','adoptive parent')) SELECT id FROM descendants",(d['b'],)).fetchall()
            if d['a'] in [r[0] for r in rows]: raise HTTPException(422,'Ancestry cycle rejected')
        c.execute('INSERT OR IGNORE INTO edges VALUES(?,?,?,?,?,?)',(uid(),d['a'],d['b'],d['kind'],d.get('status','hypothesis'),d.get('citation',''),))
        return {'ok':True}
@app.get('/api/graph')
def graph(offset:int=0,limit:int=100,q:str=''):
    ps=people(q,offset,limit); ids=[p['id'] for p in ps['items']]
    with db() as c:
        edges=[dict(r) for r in c.execute('SELECT * FROM edges WHERE a IN ('+','.join('?' for _ in ids)+') AND b IN ('+','.join('?' for _ in ids)+')',ids+ids)] if ids else []
    return {'nodes':ps['items'],'edges':edges,'total':ps['total'],'next_offset':offset+len(ids)}
def relationship(c,a,b):
    person(c,a);person(c,b)
    if a==b:return {'label':'Same person','path':[a],'status':'documented'}
    def ancestors(p):
        found={p:(0,[p])}; queue=deque([p])
        while queue and len(found)<10000:
            x=queue.popleft()
            for r in c.execute("SELECT a FROM edges WHERE b=? AND kind='parent' AND status='documented'",(x,)):
                if r[0] not in found: found[r[0]]=(found[x][0]+1,found[x][1]+[r[0]]);queue.append(r[0])
        return found
    aa,bb=ancestors(a),ancestors(b); common=set(aa)&set(bb)
    if common:
        root=min(common,key=lambda x:aa[x][0]+bb[x][0]); da,pa=aa[root]; dbb,pb=bb[root]
        if min(da,dbb)==0:
            n=max(da,dbb); label=('Parent' if n==1 else 'Grandparent' if n==2 else f'{n-2}× great-grandparent') if da==0 else ('Child' if n==1 else 'Grandchild' if n==2 else f'{n-2}× great-grandchild')
        elif da==dbb==1: label='Siblings or half-siblings (shared documented parent)'
        elif min(da,dbb)==1: label=f'Aunt/uncle–niece/nephew line; generation difference {abs(da-dbb)}'
        else: label=f'{min(da,dbb)-1} cousin, {abs(da-dbb)} removed'
        return {'label':label,'common_ancestor':root,'path':pa+list(reversed(pb[:-1])),'generations':[da,dbb],'status':'documented','note':'Calculated from recorded biological parent links, not DNA proof; pedigree collapse may yield additional paths.'}
    queue=deque([(a,[a],[])]); seen={a}
    while queue and len(seen)<10000:
        x,path,kinds=queue.popleft()
        for e in c.execute("SELECT * FROM edges WHERE (a=? OR b=?) AND status='documented'",(x,x)):
            y=e['b'] if e['a']==x else e['a']
            if y==b:return {'label':'Documented family path (includes non-biological links)','path':path+[y],'kinds':kinds+[e['kind']],'status':'documented'}
            if y not in seen:seen.add(y);queue.append((y,path+[y],kinds+[e['kind']]))
    return {'label':'Unknown — no documented path found','path':[],'status':'unknown'}
@app.get('/api/relationship')
def relation(a:str,b:str):
    with db() as c:return relationship(c,a,b)
@app.get('/api/dashboard')
def dashboard():
    with db() as c:
        counts={t:c.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('people','matches','dna','tasks','photos')}
        counts['dna_profiles']=c.execute('SELECT count(DISTINCT person) FROM dna').fetchone()[0]
        counts['unresolved']=c.execute("SELECT count(*) FROM edges WHERE status!='documented'").fetchone()[0]
        counts['documented_links']=c.execute("SELECT count(*) FROM edges WHERE status='documented'").fetchone()[0]
        counts['synthetic']=c.execute('SELECT count(*) FROM people WHERE synthetic=1').fetchone()[0]
        counts['groups']=c.execute('SELECT count(*) FROM people WHERE id NOT IN (SELECT a FROM edges UNION SELECT b FROM edges)').fetchone()[0]
        counts['groups_note']='Isolated profiles; full component counting deferred for large graphs'
        return counts
async def upload_bytes(file):
    data=await file.read(80_000_001)
    if len(data)>80_000_000:raise HTTPException(413,'Per-file safety limit: 80 MB; no file-count limit')
    return data
@app.post('/api/import/dna')
async def import_dna(req:Request,file:UploadFile=File(...),owner:str=Form(...),consent:str=Form(...),authority:str=Form(...)):
    if consent!='authorized' or not authority.strip():raise HTTPException(422,'Explicit owner/manager authorization required')
    data=await upload_bytes(file)
    try:meta,markers=dna_parse(data)
    except (ValueError,UnicodeError,zipfile.BadZipFile,RuntimeError) as e:raise HTTPException(422,str(e))
    digest=hashlib.sha256(json.dumps(sorted((list(k),v) for k,v in markers.items())).encode()).hexdigest()
    with db() as c:
        person(c,owner); old=c.execute('SELECT id,person FROM dna WHERE digest=?',(digest,)).fetchone()
        if old:
            if old['person']!=owner:raise HTTPException(409,'This genotype file is already assigned to another owner; review ownership')
            return {'id':old['id'],'duplicate':True}
        ident=uid(); c.execute('INSERT INTO dna VALUES(?,?,?,?,?,?,?,?,?,?)',(ident,owner,meta['provider'],meta['build'],meta['markers'],digest,consent,authority,now(),req.state.fernet.encrypt(data)))
        audit(c,'DNA imported',{'id':ident,'owner':owner}); return {'id':ident,**meta}
@app.delete('/api/people/{p}/dna')
def revoke(p:str):
    with db() as c:
        person(c,p); c.execute('PRAGMA secure_delete=ON'); n=c.execute('DELETE FROM dna WHERE person=?',(p,)).rowcount
        c.execute('DELETE FROM matches WHERE owner=? OR person=?',(p,p)); c.execute('DELETE FROM ancient_comparisons WHERE person=?',(p,)); c.execute('DELETE FROM shared_matches WHERE owner=? OR a=? OR b=?',(p,p,p)); c.execute('DELETE FROM merge_history'); audit(c,'genetic consent revoked',{'person':p,'files_deleted':n})
    with db() as c:c.execute('VACUUM')
    return {'deleted':n,'note':'Prior backups must be deleted separately.'}
@app.get('/api/dna')
def dna_list():
    with db() as c:return [dict(r) for r in c.execute('SELECT id,person,provider,build,markers,consent,authority,created FROM dna')]
@app.get('/api/compare')
def compare(a:str,b:str,req:Request):
    with db() as c: files=[c.execute('SELECT * FROM dna WHERE id=?',(i,)).fetchone() for i in (a,b)]
    if any(f is None for f in files):raise HTTPException(404,'File missing or consent revoked')
    if files[0]['build']=='unknown' or files[0]['build']!=files[1]['build']:raise HTTPException(422,'Known matching genome builds required')
    parsed=[dna_parse(req.state.fernet.decrypt(f['blob']))[1] for f in files]; overlap=set(parsed[0])&set(parsed[1]); valid=[k for k in overlap if all(set(parsed[i][k])<=set('ACGT') for i in (0,1))]
    same=sum(sorted(parsed[0][k])==sorted(parsed[1][k]) for k in valid)
    return {'comparable_markers':len(valid),'identical_genotypes':same,'agreement':same/len(valid) if valid else None,'warning':'Technical SNP concordance only. Not IBD, centimorgans, kinship, or a relationship estimate.'}
@app.post('/api/import/gedcom')
async def gedcom(file:UploadFile=File(...),namespace:str=Form(...)):
    if not namespace.strip():raise HTTPException(422,'Stable source namespace required')
    data=await upload_bytes(file); digest=hashlib.sha256(namespace.encode()+data).hexdigest()
    try:ps,fs=gedcom_parse(data)
    except (ValueError,UnicodeError) as e:raise HTTPException(422,str(e))
    with db() as c:
        old=c.execute('SELECT result FROM imports WHERE digest=?',(digest,)).fetchone()
        if old:return {**json.loads(old[0]),'duplicate':True}
        ids={}; created=0
        for x,p in ps.items():
            old=c.execute('SELECT person FROM identities WHERE namespace=? AND external_id=?',(namespace,x)).fetchone()
            ids[x]=old[0] if old else create_person(c,{**p,'status':'hypothesis','living':not bool(p['death'])})
            if not old:c.execute('INSERT INTO identities VALUES(?,?,?)',(namespace,x,ids[x]));created+=1
            if p.get('familysearch_id'):c.execute('INSERT OR IGNORE INTO identities VALUES(?,?,?)',('FamilySearch',p['familysearch_id'],ids[x]))
        for f in fs.values():
            for a in f['parents']:
                for b in f['children']:c.execute('INSERT OR IGNORE INTO edges VALUES(?,?,?,?,?,?)',(uid(),ids[a],ids[b],'parent','hypothesis',f'GEDCOM source: {namespace}; imported assertion, not independently verified'))
            if len(f['parents'])==2:c.execute('INSERT OR IGNORE INTO edges VALUES(?,?,?,?,?,?)',(uid(),ids[f['parents'][0]],ids[f['parents'][1]],'partner','hypothesis',namespace))
        result={'created':created,'people':len(ps),'families':len(fs),'ids':ids};c.execute('INSERT INTO imports VALUES(?,?,?)',(digest,'gedcom',json.dumps(result)));audit(c,'GEDCOM imported',{'namespace':namespace,'created':created});return result
@app.get('/api/matches')
def matches():
    with db() as c:return [dict(r) for r in c.execute('SELECT m.*,p.name FROM matches m JOIN people p ON p.id=m.person ORDER BY cm DESC LIMIT 500')]
def insert_match(c,d):
    person(c,d['owner']); person(c,d['person'])
    for k in ('cm','pct'):
        if d.get(k) is not None and (float(d[k])<0 or float(d[k])>(100 if k=='pct' else 7500)):raise HTTPException(422,'Invalid shared DNA value')
    ident=uid();c.execute('INSERT INTO matches VALUES(?,?,?,?,?,?,?,?,?,?)',(ident,d['owner'],d['person'],d.get('provider','Manual'),d.get('external_id') or ident,d.get('cm'),d.get('pct'),d.get('prediction',''),d.get('notes',''),json.dumps(d.get('raw',{}))));return ident
@app.post('/api/matches')
def add_match(d:dict):
    with db() as c:return {'id':insert_match(c,d)}
@app.post('/api/import/relatives')
async def relatives(file:UploadFile=File(...),owner:str=Form(...),consent:str=Form(...)):
    if consent!='authorized':raise HTTPException(422,'Permission required')
    data=await upload_bytes(file); digest=hashlib.sha256(owner.encode()+data).hexdigest()
    try:rows=relatives_parse(data)
    except (ValueError,UnicodeError) as e:raise HTTPException(422,str(e))
    with db() as c:
        person(c,owner)
        if c.execute('SELECT 1 FROM imports WHERE digest=?',(digest,)).fetchone():return {'duplicate':True,'created':0}
        n=0
        for r in rows:
            ext=r['external_id']
            if ext and c.execute('SELECT 1 FROM matches WHERE owner=? AND provider=? AND external_id=?',(owner,'23andMe',ext)).fetchone():continue
            p=create_person(c,{'name':r['name'],'notes':'Imported DNA match; relationship unverified'})
            insert_match(c,{**r,'owner':owner,'person':p,'provider':'23andMe'});n+=1
        c.execute('INSERT INTO imports VALUES(?,?,?)',(digest,'relatives',json.dumps({'created':n})));return {'created':n}
@app.get('/api/duplicates')
def duplicates():
    with db() as c:return [dict(r) for r in c.execute("SELECT a.id a,b.id b,a.name,a.birth birth_a,b.birth birth_b,a.place place_a,b.place place_b FROM people a JOIN people b ON lower(a.name)=lower(b.name) AND a.id<b.id LIMIT 100")]
@app.post('/api/merge')
def merge(d:dict,req:Request):
    from .connected import merge as reviewed_merge
    if d.get('approved') is not True:raise HTTPException(422,'Review approval required')
    try:
        with db() as c:return reviewed_merge(c,d['keep'],d['remove'],d.get('reason',''),req.state.fernet)
    except ValueError as e:raise HTTPException(409,str(e))
@app.post('/api/evidence')
def evidence(d:dict):
    if d.get('url') and not d['url'].startswith(('https://','http://')):raise HTTPException(422,'Use an HTTP(S) citation URL')
    with db() as c:
        person(c,d['person']);ident=uid();c.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?)',(ident,d['person'],d['title'],d.get('url',''),d.get('notes',''),int(d.get('verified',False))));return {'id':ident}
@app.patch('/api/edges/{e}')
def verify_edge(e:str,d:dict):
    if not d.get('citation'):raise HTTPException(422,'Citation required')
    with db() as c:
        c.execute("UPDATE edges SET status='documented',citation=? WHERE id=?",(d['citation'],e));audit(c,'relationship reviewed',{'id':e});return {'ok':True}
@app.post('/api/photos')
async def photo(req:Request,file:UploadFile=File(...),owner:str=Form(...),permission:str=Form(...)):
    if not permission.strip():raise HTTPException(422,'Permission statement required, including guardian permission for minors')
    data=await upload_bytes(file)
    try:
        im=Image.open(io.BytesIO(data));im.verify();im=Image.open(io.BytesIO(data));im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((1200,1200));out=io.BytesIO();im.save(out,'JPEG')
    except Exception:raise HTTPException(422,'Invalid or unsupported image')
    with db() as c:
        person(c,owner);p=uid();c.execute('INSERT INTO photos VALUES(?,?,?,?,?)',(p,owner,permission,req.state.fernet.encrypt(data),req.state.fernet.encrypt(out.getvalue())));return {'id':p}
@app.get('/api/photos/{p}')
def get_photo(p:str,req:Request):
    with db() as c:r=c.execute('SELECT preview FROM photos WHERE id=?',(p,)).fetchone()
    if not r:raise HTTPException(404)
    return Response(req.state.fernet.decrypt(r[0]),media_type='image/jpeg')
@app.get('/api/tasks')
def tasks():
    with db() as c:return [dict(r) for r in c.execute('SELECT * FROM tasks ORDER BY created DESC LIMIT 200')]
@app.post('/api/tasks')
def task(d:dict):
    with db() as c:
        p=person(c,d['person']);missing=[k for k in ('birth','death','place') if not p[k]]
        result={'mode':'Local rule-based research planner; no external search performed','gaps':missing,'suggestions':['Review birth, census, and probate records for '+p['name'],'Compare cited parents with authorized match trees; retain competing hypotheses'],'sources_found':[],'proposed_edits':[]}
        ident=uid();c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?)',(ident,d['person'],d['question'],'needs research',json.dumps(result),now()));return {'id':ident,**result}
@app.get('/api/export')
def export():
    with db() as c:return {t:[dict(r) for r in c.execute(f'SELECT * FROM {t}')] for t in ('people','edges','evidence','matches','tasks','identities','audit')}
@app.get('/api/backup')
def backup(req:Request):
    target=sqlite3.connect(':memory:')
    with db() as c:c.backup(target)
    raw=target.serialize();target.close();out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('worldtree.sqlite.encrypted',req.state.fernet.encrypt(raw));z.writestr('vault.json',(DATA/'vault.json').read_bytes())
    return Response(out.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename=WorldTree_private_backup.zip'})
@app.get('/api/audit')
def history():
    with db() as c:return [dict(r) for r in c.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 100')]
@app.post('/api/demo')
def demo():
    with db() as c:
        if c.execute('SELECT count(*) FROM people').fetchone()[0]:raise HTTPException(409,'Demo can only initialize an empty database')
        ids=[create_person(c,{'name':n,'birth':b,'synthetic':1,'status':'synthetic','place':'Synthetic example'}) for n,b in [('Alex Example','2000'),('Morgan Example','1975'),('Robin Example','1973'),('Casey Example','1950'),('Jamie Example','1952'),('Taylor Example','1978'),('Sam Example','2002')]]
        for a,b in [(1,0),(2,0),(3,1),(4,1),(3,5),(4,5),(5,6)]:c.execute('INSERT INTO edges VALUES(?,?,?,?,?,?)',(uid(),ids[a],ids[b],'parent','documented','Synthetic fixture — not real genealogy'))
        insert_match(c,{'owner':ids[0],'person':ids[6],'provider':'SYNTHETIC','cm':850,'prediction':'Synthetic first cousin example'})
        audit(c,'synthetic demo initialized',{});return {'ok':True}
@app.get('/familysearch/callback')
def familysearch_callback(state:str='',code:str='',error:str=''):
    from .familysearch import bridge
    try:
        bridge.callback(state,code,error)
        return Response('FamilySearch sign-in completed. Return to WorldTree AI.',media_type='text/plain')
    except Exception:
        return Response('FamilySearch sign-in could not be completed. Return to WorldTree and start again. No credentials were stored.',status_code=400,media_type='text/plain')
from .api_v02 import router as connected_router
app.include_router(connected_router)
if (ROOT/'frontend/dist').exists():app.mount('/',StaticFiles(directory=ROOT/'frontend/dist',html=True),name='frontend')
