"""Fixed-endpoint public research. No account scraping and no genotype uploads."""
import json,re,time,urllib.request,urllib.parse,threading
from .app import db,uid,now,person,create_person,audit
from .connected import rows,gaps
_lock=threading.Lock();_last=0.0

def fetch_json(url,limit=4_000_000):
    global _last
    with _lock:
        pause=1-(time.monotonic()-_last)
        if pause>0:time.sleep(pause)
        _last=time.monotonic()
    req=urllib.request.Request(url,headers={'User-Agent':'WorldTreeAI/0.2 (personal genealogy research; local desktop)','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=25) as r:
        raw=r.read(limit+1)
        if len(raw)>limit:raise ValueError('Response exceeds metadata limit')
        return json.loads(raw)

def wikidata_search(term):
    if len(term)>200:raise ValueError('Search is too long')
    url='https://www.wikidata.org/w/api.php?'+urllib.parse.urlencode({'action':'wbsearchentities','format':'json','language':'en','limit':10,'search':term})
    data=fetch_json(url)
    return [{'id':r['id'],'name':r.get('label',r['id']),'description':r.get('description',''),'url':'https://www.wikidata.org/wiki/'+r['id']} for r in data.get('search',[])]

def wikidata_entity(qid):
    if not re.fullmatch('Q[1-9][0-9]*',qid):raise ValueError('Valid Wikidata Q identifier required')
    data=fetch_json('https://www.wikidata.org/w/api.php?'+urllib.parse.urlencode({'action':'wbgetentities','format':'json','ids':qid,'props':'labels|descriptions|claims','languages':'en'}))
    e=data.get('entities',{}).get(qid)
    if not e or 'missing'in e:raise ValueError('Public entity not found')
    def value(prop):
        claims=e.get('claims',{}).get(prop,[])
        return [v['mainsnak']['datavalue']['value'] for v in claims if 'datavalue'in v.get('mainsnak',{})]
    def date(prop):
        v=value(prop);return v[0].get('time','').lstrip('+') if v else ''
    return {'id':qid,'name':e.get('labels',{}).get('en',{}).get('value',qid),'description':e.get('descriptions',{}).get('en',{}).get('value',''),'birth':date('P569'),'death':date('P570'),'parent_ids':[v.get('id') for prop in ('P22','P25') for v in value(prop)],'claims':e.get('claims',{}),'raw':e,'url':'https://www.wikidata.org/wiki/'+qid,'license':'CC0 structured data','retrieved':now()}

def propose(c,record,target,task=''):
    # Candidate only; no person or relationship inserted until explicit approval.
    source=uid();c.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)',(source,'Wikidata',record['url'],record['license'],'public',record['retrieved'],record['id'],json.dumps(record)))
    ident=uid();c.execute('INSERT INTO findings VALUES(?,?,?,?,?,?,?,?,?)',(ident,task,target,'Wikidata',record['id'],record['name'],json.dumps(record),source,'proposed'));return ident

def research_task(ident):
    try:
        with db() as c:
            task=c.execute('SELECT * FROM tasks WHERE id=?',(ident,)).fetchone()
            if not task:return
            p=person(c,task['person']);c.execute("UPDATE tasks SET status='running' WHERE id=?",(ident,))
        # An explicit public-research task authorizes sending only selected name, not DNA.
        candidates=wikidata_search(p['name']);found=[]
        for item in candidates[:3]:
            record=wikidata_entity(item['id'])
            with db() as c:found.append(propose(c,record,p['id'],ident))
        with db() as c:
            report={'sources_searched':['Wikidata public API'],'records_retrieved':len(found),'findings':found,'gaps':gaps(c,p['id']),'conclusion':'Search candidates need identity and relationship review. No parentage established.'}
            c.execute("UPDATE tasks SET status='review required',result=? WHERE id=?",(json.dumps(report),ident))
    except Exception as e:
        with db() as c:c.execute("UPDATE tasks SET status='blocked',result=? WHERE id=?",(json.dumps({'error':type(e).__name__+': '+str(e),'sources_searched':['Wikidata'],'records_retrieved':0,'discovery':False}),ident))

def dataset_catalog():
    d=fetch_json('https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId=doi:10.7910/DVN/FFIDCW')
    v=d['data']['latestVersion'];license=v.get('license',{});files=[]
    for item in v.get('files',[]):
        f=item['dataFile'];name=f['filename']
        if name.lower().endswith(('.anno','.tsv','.csv','.txt')):
            files.append({'id':f['id'],'name':name,'bytes':f.get('filesize'),'checksum':f.get('checksum'),'restricted':item.get('restricted',False)})
    return {'dataset':'AADR','doi':'10.7910/DVN/FFIDCW','version':str(v.get('versionNumber'))+'.'+str(v.get('versionMinorNumber')),'license':license,'termsOfUse':v.get('termsOfUse',''),'files':files,'note':'Metadata files only. No whole genotype collections downloaded.'}

def download_annotation(file_id,accept_terms):
    """Resume public metadata only; IDs must be present in the official catalog."""
    from pathlib import Path
    import hashlib
    from .app import DATA
    if not accept_terms:raise ValueError('Review and accept the displayed dataset reuse terms first')
    catalog=dataset_catalog();item=next((f for f in catalog['files'] if str(f['id'])==str(file_id)),None)
    if not item or item['restricted']:raise ValueError('Only unrestricted catalog annotation files can be downloaded')
    size=item.get('bytes')
    if not isinstance(size,int) or size>50_000_000:raise ValueError('Only known-size metadata files up to 50 MB are supported; genotype collections are excluded')
    folder=DATA/'public_metadata';folder.mkdir(exist_ok=True);partial=folder/(str(file_id)+'.part');final=folder/(str(file_id)+'.annotation')
    offset=partial.stat().st_size if partial.exists() else 0
    headers={'User-Agent':'WorldTreeAI/0.2'}
    if offset:headers['Range']=f'bytes={offset}-'
    url='https://dataverse.harvard.edu/api/access/datafile/'+str(int(file_id))
    req=urllib.request.Request(url,headers=headers)
    with urllib.request.urlopen(req,timeout=30) as r:
        append=offset>0 and r.status==206
        if not append:offset=0
        if append and not r.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise ValueError('Unexpected resumed range')
        with partial.open('ab' if append else 'wb') as f:
            while True:
                chunk=r.read(65536)
                if not chunk:break
                offset+=len(chunk)
                if offset>size:raise ValueError('Download exceeds catalog size')
                f.write(chunk)
    if partial.stat().st_size!=size:raise ValueError('Incomplete download retained for resume')
    check=item.get('checksum') or {};algorithm=check.get('type','').lower().replace('-','')
    if algorithm not in ('md5','sha1','sha256','sha512'):raise ValueError('Unsupported/missing repository checksum; file not promoted')
    if hashlib.new(algorithm,partial.read_bytes()).hexdigest().lower()!=check.get('value','').lower():partial.unlink();raise ValueError('Repository checksum mismatch; partial file discarded')
    partial.replace(final);manifest={**item,'dataset':catalog['dataset'],'version':catalog['version'],'license':catalog['license'],'termsOfUse':catalog['termsOfUse'],'retrieved':now(),'url':url,'local_path':str(final)}
    (folder/(str(file_id)+'.json')).write_text(json.dumps(manifest,indent=2));return manifest

def ena_metadata(accession,accept_terms=False):
    """Retrieve public study run metadata only, not personal genotypes or raw reads."""
    import csv,io,hashlib
    from .app import DATA
    if not accept_terms:raise ValueError('Review ENA/EMBL-EBI repository terms before retaining metadata')
    if not re.fullmatch(r'(PRJEB|PRJNA|PRJDB)[0-9]{1,12}',accession):raise ValueError('A public study accession is required')
    url='https://www.ebi.ac.uk/ena/portal/api/filereport?'+urllib.parse.urlencode({'accession':accession,'result':'read_run','fields':'run_accession,sample_accession,scientific_name','format':'tsv'})
    req=urllib.request.Request(url,headers={'User-Agent':'WorldTreeAI/0.2.1'})
    with urllib.request.urlopen(req,timeout=30) as r:
        data=r.read(4000001)
        if len(data)>4000000:raise ValueError('Study metadata exceeds 4 MB; select a narrower study')
    reader=csv.DictReader(io.StringIO(data.decode()),delimiter='\t')
    if reader.fieldnames!=['run_accession','sample_accession','scientific_name']:raise ValueError('Unexpected ENA metadata schema')
    records=list(reader)
    if not records:raise ValueError('No public run metadata found')
    result={'repository':'ENA','accession':accession,'retrieved':now(),'url':url,'terms_url':'https://ena-browser-docs.readthedocs.io/en/latest/about/policies.html','reuse_status':'Repository terms apply; no blanket license asserted for separately linked data','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'runs':records,'scope':'Run/sample accession metadata only; specimen age and ancient status require the cited study; no genotypes downloaded or relatedness inferred'}
    folder=DATA/'public_metadata';folder.mkdir(exist_ok=True);(folder/(accession+'.tsv')).write_bytes(data);(folder/(accession+'.json')).write_text(json.dumps(result,indent=2));return result
