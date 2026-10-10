import json,sqlite3,hashlib,io,zipfile,threading
from fastapi import APIRouter,HTTPException,Request,UploadFile,File,Form
from fastapi.responses import Response
from .app import db,uid,now,person,create_person,audit,DATA,DB,upload_bytes
from .connected import *
from .research import wikidata_search,wikidata_entity,propose,research_task,dataset_catalog
from .parsers import dna_parse
router=APIRouter(prefix='/api/v02')
migrate();init_blocks()
# Interrupted background research is recoverable by requeue, never marked successful.
with db() as c:c.execute("UPDATE tasks SET status='interrupted' WHERE status='running'")

@router.get('/status')
def status():return {'version':'0.2.0','desktop':'PySide6 native shell + bundled local graph UI','connectors':{'FamilySearch':'OAuth PKCE and bounded ancestor import implemented; registered approved client required; live authentication unverified; writes disabled','WikiTree':'Not implemented; use permitted GEDCOM export','Wikidata':'Public read-only API; requires network','AADR':'Metadata catalog and annotation import; requires public endpoint access'},'science':{'concordance':'experimental technical comparison','PCA':'not implemented','IBD':'not implemented','relationship_probabilities':'not implemented'},'research':'Wikidata-backed candidate queue; user approval required'}
@router.get('/relationship')
def relationship(a:str,b:str):
    with db() as c:return calculate(c,a,b)
@router.get('/search')
def search(q:str='',provider:str='',marker:str='',year:str='',place:str='',offset:int=0,limit:int=100):
    sql='SELECT p.* FROM people p WHERE (p.name LIKE ? OR p.aliases LIKE ?) AND p.place LIKE ? AND p.birth LIKE ?';args=['%'+q+'%','%'+q+'%','%'+place+'%','%'+year+'%']
    if provider:sql+=' AND EXISTS (SELECT 1 FROM identities i WHERE i.person=p.id AND i.namespace LIKE ?)';args.append('%'+provider+'%')
    if marker:sql+=' AND EXISTS (SELECT 1 FROM markers m WHERE m.person=p.id AND m.kind=?)';args.append(marker)
    with db() as c:return rows(c,sql+' ORDER BY p.name LIMIT ? OFFSET ?',args+[min(200,max(1,limit)),max(0,offset)])
@router.get('/vault')
def vault():
    with db() as c:
        counts={t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['people','edges','dna','matches','photos','sources','ancient_samples','findings','events']}
        counts['familysearch_profiles']=c.execute("SELECT count(DISTINCT person) FROM identities WHERE lower(namespace) LIKE '%familysearch%'").fetchone()[0]
        counts['local_bytes']=sum(p.stat().st_size for p in DATA.rglob('*') if p.is_file());counts['offline']='All imported records, retained sources, photos, analysis and edits remain local. Uncached source websites are not offline.'
        return counts
@router.get('/identities/{p}')
def identities(p:str):
    with db() as c:return rows(c,'SELECT * FROM identities WHERE person=?',(p,))
@router.post('/identities')
def identity(d:dict):
    with db() as c:
        person(c,d['person']);c.execute('INSERT INTO identities VALUES(?,?,?)',(d['namespace'],d['external_id'],d['person']));return {'ok':True}
@router.get('/duplicates')
def duplicates():
    init_blocks()
    with db() as c:return duplicate_candidates(c)
@router.post('/duplicates/review')
def review(d:dict):
    if d['state'] not in ('separate','rejected','possible','later'):raise HTTPException(422,'Invalid review state')
    with db() as c:c.execute('INSERT OR REPLACE INTO duplicate_reviews VALUES(?,?,?,?)',(*sorted([d['a'],d['b']]),d['state'],d.get('reason','')));return {'ok':True}
@router.post('/merge')
def merge_profiles(d:dict,req:Request):
    if d.get('approved') is not True:raise HTTPException(422,'Explicit approval required')
    try:
        with db() as c:return merge(c,d['keep'],d['remove'],d['reason'],req.state.fernet)
    except ValueError as e:raise HTTPException(409,str(e))
@router.get('/merges')
def merges():
    with db() as c:return rows(c,'SELECT id,created,keep_id,removed_id,undone FROM merge_history ORDER BY created DESC')
@router.post('/merge/{ident}/undo')
def undo(ident:str,req:Request):
    try:
        with db() as c:return undo_merge(c,ident,req.state.fernet)
    except ValueError as e:raise HTTPException(409,str(e))
MARKERS=['DNA Relative','Famous Connection','Ancient Connection','Direct Ancestor','Shared Ancestor','Paternal Branch','Maternal Branch','Record Verified','Research Needed','Disputed Connection','Royal Connection','Migration History','Photo Available','Unconnected Person']
@router.get('/markers/{p}')
def markers(p:str):
    with db() as c:
        person(c,p);result=rows(c,'SELECT * FROM markers WHERE person=?',(p,))
        if c.execute('SELECT 1 FROM matches WHERE person=?',(p,)).fetchone():result.append({'kind':'DNA Relative','status':'provider reported','reason':'Imported DNA match entry; not possession of raw genotype'})
        if c.execute('SELECT 1 FROM photos WHERE person=?',(p,)).fetchone():result.append({'kind':'Photo Available','status':'stored','reason':'Authorized local photograph'})
        reference=c.execute("SELECT value FROM settings WHERE key='reference'").fetchone()
        if reference and reference[0]!=p:
            anc,truncated=ancestry(c,reference[0])
            if p in anc:result.append({'kind':'Direct Ancestor','status':'documented genealogy','reason':'Recorded biological parent path to selected reference profile'})
            elif calculate(c,reference[0],p)['classification']=='unknown':result.append({'kind':'Unconnected Person','status':'no documented path','reason':'No connection found within traversal limits to selected reference'})
        if c.execute('SELECT 1 FROM events WHERE person=?',(p,)).fetchone():result.append({'kind':'Migration History','status':'recorded events','reason':'Cited geographic event data stored locally'})
        return result
@router.post('/markers')
def marker(d:dict):
    if d['kind'] not in MARKERS or not d.get('reason'):raise HTTPException(422,'Known marker and evidence explanation required')
    if d.get('status')=='verified' and not d.get('source'):raise HTTPException(422,'Verified markers require source reference')
    with db() as c:
        person(c,d['person']);c.execute('INSERT OR IGNORE INTO markers VALUES(?,?,?,?,?,?)',(uid(),d['person'],d['kind'],d.get('status','proposed'),d['reason'],d.get('source','')));return {'ok':True}
@router.post('/shared-matches')
def shared(d:dict):
    if not d.get('source') or len({d['owner'],d['a'],d['b']})<3:raise HTTPException(422,'Three distinct profiles and provider evidence required')
    with db() as c:
        for p in [d['owner'],d['a'],d['b']]:person(c,p)
        c.execute('INSERT OR REPLACE INTO shared_matches VALUES(?,?,?,?)',(d['owner'],*sorted([d['a'],d['b']]),d['source']));return {'ok':True}
@router.get('/clusters/{owner}')
def clusters(owner:str):
    with db() as c:return cluster(c,owner)
@router.post('/branch')
def branch(d:dict):
    if d['branch'] not in ('maternal','paternal','both','unknown') or not d.get('evidence'):raise HTTPException(422,'Branch and supporting evidence required')
    with db() as c:c.execute('INSERT OR REPLACE INTO branches VALUES(?,?,?,?)',(d['owner'],d['person'],d['branch'],d['evidence']));return {'ok':True}
@router.get('/match-intelligence/{owner}')
def intelligence(owner:str):
    with db() as c:
        ms=rows(c,'SELECT m.*,p.name FROM matches m JOIN people p ON p.id=m.person WHERE owner=? LIMIT 200',(owner,))
        for m in ms:
            m['genealogy']=calculate(c,owner,m['person']);m['branch']=rows(c,'SELECT branch,evidence FROM branches WHERE owner=? AND person=?',(owner,m['person']));m['segments']='Not validated; raw CSV fields retained; triangulation unavailable'
        return {'matches':ms,'clusters':cluster(c,owner),'probabilities':'No validated probability model installed; source predictions preserved'}
@router.post('/famous')
def famous(d:dict):
    if not d.get('source'):raise HTTPException(422,'Public biography/source reference required')
    with db() as c:
        person(c,d['person']);c.execute('INSERT OR REPLACE INTO famous VALUES(?,?,?)',(d['person'],d.get('category','Other'),d['source']));return {'ok':True}
@router.get('/famous/{reference}')
def famous_connections(reference:str):
    with db() as c:
        result=[]
        for r in rows(c,'SELECT f.*,p.name FROM famous f JOIN people p ON p.id=f.person LIMIT 200'):
            r['relationship']=calculate(c,reference,r['person']);r['status']='evidence review required' if r['relationship']['relationships'] else 'no documented connection';result.append(r)
        return result
@router.post('/famous/notify')
def famous_notify(d:dict):
    with db() as c:
        r=calculate(c,d['reference'],d['person'])
        if not r['relationships']:raise HTTPException(422,'No documented path available')
        c.execute('INSERT INTO notifications VALUES(?,?,?,?)',(uid(),'Potential famous relative connection — evidence review required',d['person'],now()));return r
@router.get('/notifications')
def notices():
    with db() as c:return rows(c,'SELECT * FROM notifications ORDER BY created DESC LIMIT 100')
@router.get('/gaps/{p}')
def gap(p:str):
    with db() as c:return gaps(c,p)
@router.post('/research')
def queue(d:dict):
    if d.get('allow_public_name_search') is not True:raise HTTPException(422,'Authorize sending selected profile name to Wikidata; DNA never sent')
    with db() as c:
        person(c,d['person']);ident=uid();c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?)',(ident,d['person'],d.get('question','Research public records'),'queued','{}',now()))
    threading.Thread(target=research_task,args=(ident,),daemon=True).start();return {'id':ident,'status':'queued'}
@router.get('/findings')
def findings():
    with db() as c:return rows(c,'SELECT * FROM findings ORDER BY rowid DESC LIMIT 200')
@router.post('/findings/{ident}/review')
def finding_review(ident:str,d:dict):
    if d.get('decision') not in ('approve','reject'):raise HTTPException(422,'Choose approve/reject')
    with db() as c:
        r=c.execute('SELECT * FROM findings WHERE id=?',(ident,)).fetchone()
        if not r or r['status']!='proposed':raise HTTPException(409,'Finding unavailable or already reviewed')
        p=None
        if d['decision']=='approve':
            payload=json.loads(r['payload']);old=c.execute('SELECT person FROM identities WHERE namespace=? AND external_id=?',(r['provider'],r['external_id'])).fetchone()
            p=old[0] if old else create_person(c,{'name':payload['name'],'birth':payload.get('birth',''),'death':payload.get('death',''),'status':'hypothesis','notes':'Public record candidate; connection unverified'})
            if not old:c.execute('INSERT INTO identities VALUES(?,?,?)',(r['provider'],r['external_id'],p))
            c.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?)',(uid(),p,'Imported public record',payload['url'],'Review underlying records; no parent links inferred',0))
        c.execute('UPDATE findings SET status=? WHERE id=?',(d['decision'],ident));audit(c,'finding reviewed',{'finding':ident,'decision':d['decision'],'person':p});return {'person':p,'relationship_added':False}
@router.get('/public/search')
def public_search(q:str):
    try:return wikidata_search(q)
    except Exception as e:raise HTTPException(502,'Public search unavailable: '+str(e))
@router.post('/public/propose')
def public_propose(d:dict):
    try:r=wikidata_entity(d['qid'])
    except Exception as e:raise HTTPException(502,str(e))
    with db() as c:person(c,d['person']);return {'finding':propose(c,r,d['person'])}
@router.get('/ancient/catalog')
def catalog():
    try:return dataset_catalog()
    except Exception as e:raise HTTPException(502,'AADR metadata unavailable: '+str(e))
@router.get('/ancient')
def ancient(q:str='',offset:int=0):
    with db() as c:return rows(c,'SELECT * FROM ancient_samples WHERE sample_id LIKE ? OR site LIKE ? OR country LIKE ? ORDER BY sample_id LIMIT 100 OFFSET ?',('%'+q+'%',)*3+(max(offset,0),))
@router.post('/ancient/import')
async def ancient_import(file:UploadFile=File(...),dataset:str=Form(...),version:str=Form(...),license:str=Form(...),citation:str=Form(...),sample_ids:str=Form('')):
    data=await upload_bytes(file)
    try:
        with db() as c:
            result=sample_import(c,data,dataset,version,license,citation,set(x.strip() for x in sample_ids.split(',') if x.strip()) or None)
            c.execute('INSERT INTO import_history VALUES(?,?,?,?,?,?,?)',(uid(),'ancient metadata',dataset,len(data),'complete',json.dumps(result),now()));return result
    except (ValueError,UnicodeError) as e:raise HTTPException(422,str(e))
@router.post('/ancient/compare')
async def ancient_compare(req:Request,file:UploadFile=File(...),dna_id:str=Form(...),sample_id:str=Form(...),ancient_strand:str=Form(...),modern_strand:str=Form(...)):
    data=await upload_bytes(file)
    try:
        meta,ancient=dna_parse(data)
        with db() as c:
            d=c.execute('SELECT * FROM dna WHERE id=?',(dna_id,)).fetchone();s=c.execute('SELECT * FROM ancient_samples WHERE id=?',(sample_id,)).fetchone()
            if not d or not s:raise ValueError('Select an authorized DNA file and indexed ancient sample')
            _,modern=dna_parse(req.state.fernet.decrypt(d['blob']));result=compare_markers(modern,ancient,d['build'],meta['build'],modern_strand,ancient_strand)
            result['input_hash']=hashlib.sha256(data).hexdigest();result['sample_link']='User-assigned sample association; independently verify provenance'
            c.execute('INSERT INTO ancient_comparisons VALUES(?,?,?,?,?)',(uid(),s['id'],d['person'],json.dumps(result),now()));return result
    except ValueError as e:raise HTTPException(422,str(e))
@router.get('/ancient/results')
def ancient_results():
    with db() as c:return rows(c,'SELECT * FROM ancient_comparisons ORDER BY created DESC LIMIT 100')
@router.post('/events')
def event(d:dict):
    if not d.get('citation') or not -90<=float(d['lat'])<=90 or not -180<=float(d['lon'])<=180:raise HTTPException(422,'Valid coordinates and citation required')
    with db() as c:
        person(c,d['person']);c.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?)',(uid(),d['person'],d.get('kind','residence'),d.get('date',''),d['place'],float(d['lat']),float(d['lon']),d['citation']));return {'ok':True}
@router.get('/events')
def events(person_id:str=''):
    with db() as c:return rows(c,'SELECT * FROM events'+(' WHERE person=?' if person_id else '')+' ORDER BY date LIMIT 1000',(person_id,) if person_id else ())
@router.get('/tree-compare')
def tree_compare(a:str,b:str):
    with db() as c:
        aa=rows(c,'SELECT i.*,p.name,p.birth FROM identities i JOIN people p ON p.id=i.person WHERE namespace=?',(a,));bb=rows(c,'SELECT i.*,p.name,p.birth FROM identities i JOIN people p ON p.id=i.person WHERE namespace=?',(b,));shared={x['person'] for x in aa}&{x['person'] for x in bb}
        return {'shared_mapped_people':list(shared),'only_a':[x for x in aa if x['person'] not in shared],'only_b':[x for x in bb if x['person'] not in shared],'note':'Compares approved identity mappings; unmerged lookalikes remain distinct'}
@router.get('/sources')
def sources():
    with db() as c:return rows(c,'SELECT * FROM sources ORDER BY retrieved DESC LIMIT 100')
@router.get('/graph')
def graph(p:str='',mode:str='family',limit:int=100):
    limit=min(200,max(1,limit))
    with db() as c:
        if p:
            person(c,p);ids=[p]+[r[0] for r in c.execute('SELECT CASE WHEN a=? THEN b ELSE a END FROM edges WHERE a=? OR b=? LIMIT ?',(p,p,p,limit-1))]
        else:ids=[r[0] for r in c.execute('SELECT id FROM people ORDER BY name LIMIT ?',(limit,))]
        if mode=='dna' and p:ids=list(dict.fromkeys(ids+[r[0] for r in c.execute('SELECT person FROM matches WHERE owner=? LIMIT ?',(p,limit))]))[:limit]
        qs=','.join('?'for _ in ids)
        if not ids:return {'nodes':[],'edges':[]}
        ns=rows(c,f'SELECT * FROM people WHERE id IN ({qs})',ids);es=rows(c,f'SELECT * FROM edges WHERE a IN ({qs}) AND b IN ({qs})',ids+ids)
        if mode=='dna':es+= [{'id':m['id'],'a':m['owner'],'b':m['person'],'kind':'DNA provider match','status':'provider reported','citation':m['provider']} for m in rows(c,f'SELECT * FROM matches WHERE owner IN ({qs}) AND person IN ({qs})',ids+ids)]
        return {'nodes':ns,'edges':es,'bounded':True,'limit':limit,'total':c.execute('SELECT count(*) FROM people').fetchone()[0]}
@router.post('/ancient/download')
def download(d:dict):
    from .research import download_annotation
    try:r=download_annotation(d['file_id'],d.get('accept_terms') is True)
    except Exception as e:raise HTTPException(502,str(e))
    with db() as c:c.execute('INSERT INTO import_history VALUES(?,?,?,?,?,?,?)',(uid(),'public annotation download',r['url'],r['bytes'],'complete',json.dumps(r),now()))
    return r
@router.get('/import-history')
def import_history():
    with db() as c:return {'v02':rows(c,'SELECT * FROM import_history ORDER BY created DESC LIMIT 100'),'v01_receipts':rows(c,'SELECT digest,kind,result FROM imports LIMIT 100')}
@router.post('/reference')
def reference(d:dict):
    with db() as c:person(c,d['person']);c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('reference',d['person']));return {'ok':True}
@router.get('/dashboard')
def dashboard02():
    with db() as c:
        counts={'profiles':c.execute('SELECT count(*) FROM people').fetchone()[0],'dna_relatives':c.execute('SELECT count(DISTINCT person) FROM matches').fetchone()[0],'ancient_samples':c.execute('SELECT count(*) FROM ancient_samples').fetchone()[0],'familysearch_profiles':c.execute("SELECT count(DISTINCT person) FROM identities WHERE lower(namespace) LIKE '%familysearch%'").fetchone()[0],'stored_documents':c.execute('SELECT count(*) FROM sources').fetchone()[0]}
        ref=c.execute("SELECT value FROM settings WHERE key='reference'").fetchone();counts['reference']=ref[0] if ref else None
        counts['verified_direct_ancestors']=len(ancestry(c,ref[0])[0])-1 if ref else None
        counts['proposed_famous_connections']=c.execute("SELECT count(*) FROM markers WHERE kind='Famous Connection' AND status!='verified'").fetchone()[0]
        counts['verified_famous_markers']=c.execute("SELECT count(*) FROM markers WHERE kind='Famous Connection' AND status='verified'").fetchone()[0]
        counts['profiles_with_incomplete_documented_parentage']=c.execute("SELECT count(*) FROM people p WHERE (SELECT count(*) FROM edges e WHERE e.b=p.id AND e.kind='parent' AND e.status='documented')<2").fetchone()[0]
        counts['duplicate_reviews_pending']=c.execute("SELECT count(*) FROM duplicate_reviews WHERE state IN ('possible','later')").fetchone()[0]
        # Use SQLite temp tables rather than transferring every node and edge into Python.
        c.execute('CREATE TEMP TABLE visited(id TEXT PRIMARY KEY)');groups=0
        while True:
            root=c.execute('SELECT id FROM people WHERE id NOT IN (SELECT id FROM visited) LIMIT 1').fetchone()
            if not root:break
            c.execute('WITH RECURSIVE component(id) AS (SELECT ? UNION SELECT CASE WHEN e.a=x.id THEN e.b ELSE e.a END FROM edges e JOIN component x ON e.a=x.id OR e.b=x.id) INSERT OR IGNORE INTO visited SELECT id FROM component',(root[0],));groups+=1
        counts['family_networks']=groups;return counts
@router.post('/familysearch/start')
def fs_start(d:dict,req:Request):
    from .familysearch import bridge
    if d.get('registered_application') is not True:raise HTTPException(422,'An application registered for this environment and redirect URI is required')
    try:return bridge.start(req.cookies['wt_session'],d['client_id'],d.get('environment','beta'))
    except ValueError as e:raise HTTPException(422,str(e))
@router.get('/familysearch/status')
def fs_status(req:Request):
    from .familysearch import bridge
    return bridge.status(req.cookies['wt_session'])
@router.post('/familysearch/disconnect')
def fs_disconnect(req:Request):
    from .familysearch import bridge
    bridge.disconnect(req.cookies['wt_session']);return {'connected':False}
@router.post('/familysearch/import')
def fs_import(d:dict,req:Request):
    from .familysearch import bridge,import_ancestry
    if not d.get('retention_permission'):raise HTTPException(422,'Permission to retain independent local records is required')
    try:
        session=req.cookies['wt_session'];payload=bridge.ancestry(session,d['person_id'],int(d.get('generations',3)))
        with db() as c:return import_ancestry(c,payload,bridge.status(session)['environment'],d['retention_permission'])
    except Exception as e:raise HTTPException(502,'FamilySearch import unavailable: '+type(e).__name__)
@router.post('/ancient/ena-metadata')
def ena_download(d:dict):
    from .research import ena_metadata
    try:r=ena_metadata(d['accession'],d.get('accept_terms') is True)
    except Exception as e:raise HTTPException(502,str(e))
    with db() as c:
        c.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)',(uid(),'ENA',r['url'],r['reuse_status'],'public metadata',r['retrieved'],r['accession'],json.dumps(r)))
        c.execute('INSERT INTO import_history VALUES(?,?,?,?,?,?,?)',(uid(),'ENA metadata',r['url'],r['bytes'],'complete',json.dumps(r),now()))
    return r
