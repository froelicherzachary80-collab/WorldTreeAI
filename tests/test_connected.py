import json,io,zipfile,sqlite3,base64,os
from test_acceptance import client,module,person,GED
from backend.connected import calculate,compare_markers,snapshot
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

def link(a,b,kind='parent'):
    r=client.post('/api/edges',json={'a':a,'b':b,'kind':kind,'status':'documented','citation':'SYNTHETIC cited record'});assert r.status_code==200,r.text

def cousin(degree,removed=0):
    root=person('Common ancestor');ends=[]
    for length in [degree+1,degree+1+removed]:
        prev=root
        for i in range(length):p=person('Branch descendant');link(prev,p);prev=p
        ends.append(prev)
    return ends

def test_13_advanced_relationships():
    for degree,removed,title in [(1,0,'1st cousins'),(3,0,'3rd cousins'),(2,2,'2nd cousins, 2 time(s) removed')]:
        a,b=cousin(degree,removed);r=client.get('/api/v02/relationship',params={'a':a,'b':b}).json();assert r['relationships'][0]['label']==title,r
    a,b=person('Unrelated A'),person('Unrelated B');assert client.get('/api/v02/relationship',params={'a':a,'b':b}).json()['classification']=='unknown'

def test_14_half_siblings_and_nonbiological():
    x,y,z=[person('Parent '+str(i))for i in range(3)];a,b=person('Half sibling A'),person('Half sibling B')
    for p,c in [(x,a),(y,a),(x,b),(z,b)]:link(p,c)
    r=client.get('/api/v02/relationship',params={'a':a,'b':b}).json();assert r['relationships'][0]['label']=='Half-siblings'
    c=person('Adopted');link(a,c,'adoptive parent');assert client.get('/api/v02/relationship',params={'a':a,'b':c}).json()['classification']=='adoptive/nonbiological'
    d=person('Partner');link(a,d,'partner');assert client.get('/api/v02/relationship',params={'a':a,'b':d}).json()['classification']=='through marriage/partnership'

def test_15_famous_connection_and_notification():
    a,b=cousin(1);assert client.post('/api/v02/famous',json={'person':b,'category':'Synthetic notable','source':'https://example.org/synthetic-record'}).status_code==200
    rs=client.get('/api/v02/famous/'+a).json();assert any(r['person']==b and r['relationship']['relationships'] for r in rs)
    assert client.post('/api/v02/famous/notify',json={'reference':a,'person':b}).status_code==200

def test_16_familysearch_origin_local_edit():
    ged=GED.replace(b'1 NAME Ada /Example/',b'1 NAME Ada /Example/\n1 _FSFTID TEST-123').replace(b'2 VERS 5.5.1',b'2 VERS 7.0')
    r=client.post('/api/import/gedcom',data={'namespace':'FamilySearch-origin-test'},files={'file':('origin.ged',ged)});assert r.status_code==200,r.text
    p=r.json()['ids']['@I1@'];assert any(x['external_id']=='TEST-123' for x in client.get('/api/v02/identities/'+p).json())
    assert client.patch('/api/people/'+p,json={'name':'Edited only locally'}).status_code==200
    assert client.get('/api/people/'+p).json()['name']=='Edited only locally'

def test_17_undo_merge_preserves_identities():
    a,b=person('Duplicate Person'),person('Duplicate Person')
    for p,provider in [(a,'FamilySearch-test'),(b,'WikiTree-test')]:assert client.post('/api/v02/identities',json={'person':p,'namespace':provider,'external_id':'test-id'}).status_code==200
    r=client.post('/api/v02/merge',json={'keep':a,'remove':b,'approved':True,'reason':'Synthetic identity evidence'});assert r.status_code==200,r.text
    assert len(client.get('/api/v02/identities/'+a).json())==2
    r=client.post('/api/v02/merge/'+r.json()['merge_id']+'/undo',json={});assert r.status_code==200,r.text
    assert len(client.get('/api/v02/identities/'+a).json())==1;assert len(client.get('/api/v02/identities/'+b).json())==1

def test_18_undo_blocks_newer_edits():
    a,b=person('Undo A'),person('Undo B');r=client.post('/api/v02/merge',json={'keep':a,'remove':b,'approved':True,'reason':'fixture'});assert r.status_code==200
    person('Newer edit');assert client.post('/api/v02/merge/'+r.json()['merge_id']+'/undo',json={}).status_code==409

def test_19_duplicate_review_persistent():
    a,b=person('UniqueReview ExampleSurname'),person('UniqueReview ExampleSurname');rs=client.get('/api/v02/duplicates').json();assert any({r['a']['id'],r['b']['id']}=={a,b}for r in rs)
    client.post('/api/v02/duplicates/review',json={'a':a,'b':b,'state':'rejected','reason':'different people'})
    assert not any({r['a']['id'],r['b']['id']}=={a,b}for r in client.get('/api/v02/duplicates').json())

def test_20_shared_matches_not_triangulation():
    o,a,b=[person('Shared fixture '+str(i))for i in range(3)];r=client.post('/api/v02/shared-matches',json={'owner':o,'a':a,'b':b,'source':'Synthetic provider shared match report'});assert r.status_code==200
    r=client.get('/api/v02/clusters/'+o).json();assert set(r['groups'][0])=={a,b};assert 'not proven'in r['interpretation']

def test_21_ancient_metadata_and_safe_comparison():
    csv=b'sample_id,site,country,period,age,sex,haplogroup,build\nSYNTHETIC-ANCIENT,Test site,Test country,Neolithic,6000 BP,unknown,unknown,37\n'
    r=client.post('/api/v02/ancient/import',data={'dataset':'SYNTHETIC','version':'1','license':'Synthetic test fixture','citation':'https://example.org/synthetic'},files={'file':('sample.csv',csv)});assert r.status_code==200,r.text;assert r.json()['indexed']==1
    a={('1',1,'rs1'):'AG',('1',2,'rs2'):'AT'};b={('1',1,'rs1'):'TC',('1',2,'rs2'):'AT'}
    r=compare_markers(a,b,'37','37','forward','reverse');assert r['agreement']==1;assert r['excluded_ambiguous']==1;assert r['direct_ancestor_claim'] is False
    import pytest
    with pytest.raises(ValueError):compare_markers(a,b,'37','38')

def test_22_research_proposals_require_approval():
    from backend.research import propose
    target=person('Research target');before=client.get('/api/people').json()['total']
    record={'id':'SYNTHETIC-Q','name':'Synthetic candidate','url':'https://example.org','license':'Synthetic fixture','retrieved':'2026-10-10','birth':'1900'}
    with module.db() as c:f=propose(c,record,target)
    assert client.get('/api/people').json()['total']==before
    r=client.post('/api/v02/findings/'+f+'/review',json={'decision':'approve'});assert r.status_code==200;assert r.json()['relationship_added'] is False
    assert client.get('/api/people').json()['total']==before+1

def test_23_complete_backup_clean_restore():
    r=client.get('/api/backup');assert r.status_code==200
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        cfg=json.loads(z.read('vault.json'));key=base64.urlsafe_b64encode(Scrypt(salt=base64.b64decode(cfg['salt']),length=32,n=2**15,r=8,p=1).derive(b'synthetic-testing-only'));raw=Fernet(key).decrypt(z.read('worldtree.sqlite.encrypted'))
    c=sqlite3.connect(':memory:');c.deserialize(raw);assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok';assert c.execute('SELECT count(*) FROM migrations WHERE version=2').fetchone()[0]==1;assert c.execute('SELECT count(*) FROM ancient_samples').fetchone()[0]>=1;c.close()

def test_24_bounded_branch_expansion_and_private_views():
    ps=client.get('/api/v02/search?q=Large fixture&limit=5000').json();assert len(ps)==200
    r=client.get('/api/v02/graph',params={'p':ps[0]['id'],'limit':5000}).json();assert len(r['nodes'])<=200
    from fastapi.testclient import TestClient
    anonymous=TestClient(module.app);assert anonymous.get('/api/v02/search').status_code==401;assert anonymous.get('/api/dna').status_code==401

def test_25_events_markers_and_offline_vault():
    p=person('Migration example');r=client.post('/api/v02/events',json={'person':p,'date':'1900-01-01','place':'Synthetic site','lat':42,'lon':-77,'citation':'synthetic citation'});assert r.status_code==200,r.text
    r=client.post('/api/v02/markers',json={'person':p,'kind':'Migration History','status':'proposed','reason':'recorded location event'});assert r.status_code==200
    assert client.get('/api/v02/markers/'+p).json()[0]['kind']=='Migration History'
    assert client.get('/api/v02/vault').json()['events']>=1

def test_26_real_public_specimen_metadata():
    from pathlib import Path
    data=(Path(__file__).resolve().parents[1]/'fixtures/ancient_public_kotias.csv').read_bytes()
    r=client.post('/api/v02/ancient/import',data={'dataset':'Jones et al. 2015 published specimen metadata','version':'publication 2015; excerpt 1','license':'CC BY 4.0 article metadata excerpt','citation':'https://doi.org/10.1038/ncomms9912'},files={'file':('kotias.csv',data)})
    assert r.status_code==200 and r.json()['indexed']==1
    r=client.get('/api/v02/ancient?q=Kotias').json()[0];assert r['sample_id']=='Kotias' and r['country']=='Georgia' and 'CC BY 4.0'in r['license'];assert r['build']=='unknown'

def test_27_no_network_needed_for_local_edits(monkeypatch):
    import urllib.request
    def blocked(*args,**kwargs):raise RuntimeError('Network disconnected for test')
    monkeypatch.setattr(urllib.request,'urlopen',blocked)
    p=person('Offline creation');assert client.patch('/api/people/'+p,json={'place':'Offline edited location'}).status_code==200
    assert client.get('/api/v02/search?q=Offline creation').json()[0]['place']=='Offline edited location'
    assert client.get('/api/v02/vault').status_code==200

def test_28_v01_migration_retains_rows(tmp_path):
    import subprocess,sys
    from pathlib import Path
    root=Path(__file__).resolve().parents[1];d=tmp_path/'old';d.mkdir();c=sqlite3.connect(d/'worldtree.sqlite');c.executescript((root/'backend/schema.sql').read_text());c.execute("INSERT INTO people(id,name) VALUES('legacy-1','Legacy Person')");c.commit();c.close()
    env={**os.environ,'WORLDTREE_DATA':str(d)}
    result=subprocess.run([sys.executable,'-c',"from backend.app import db; c=__import__('sqlite3').connect(__import__('os').environ['WORLDTREE_DATA']+'/worldtree.sqlite'); assert c.execute(\"SELECT name FROM people WHERE id='legacy-1'\").fetchone()[0]=='Legacy Person'; assert c.execute('SELECT count(*) FROM migrations').fetchone()[0]==2"],cwd=root,env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr;assert (d/'worldtree.pre_v02.sqlite').exists()
