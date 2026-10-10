import os,tempfile,importlib,io,zipfile
os.environ['WORLDTREE_DATA']=tempfile.mkdtemp()
from fastapi.testclient import TestClient
from backend import app as module
client=TestClient(module.app)
assert client.post('/api/unlock',json={'password':'synthetic-testing-only'}).status_code==200

def person(name):return client.post('/api/people',json={'name':name,'synthetic':1}).json()['id']
def upload(kind,data,**fields):return client.post('/api/import/'+kind,data=fields,files={'file':('fixture.txt',data)})
A=b'# AncestryDNA raw data\n# build 37\nrsid chromosome position allele1 allele2\nrs1 1 100 A G\nrs2 1 200 C C\n'
B=b'# 23andMe raw data\n# build 37\n# rsid chromosome position genotype\nrs1 1 100 AG\nrs2 1 200 CT\n'
GED=b'0 HEAD\n1 SOUR SYNTHETIC\n1 GEDC\n2 VERS 5.5.1\n1 CHAR UTF-8\n0 @I1@ INDI\n1 NAME Ada /Example/\n1 BIRT\n2 DATE 1 JAN 1900\n2 PLAC Exampletown\n0 @I2@ INDI\n1 NAME Ben /Example/\n0 @F1@ FAM\n1 HUSB @I1@\n1 CHIL @I2@\n0 TRLR\n'
CSV=b'Display Name,Profile URL,Percent DNA Shared,Predicted Relationship,Chromosome Number,Chromosome Start Point,Chromosome End Point\nPat Example,https://example.org/pat,1.2,Third Cousin,1,100,200\n'

def test_01_two_dna_owners():
    a,b=person('Owner A'),person('Owner B')
    x=upload('dna',A,owner=a,consent='authorized',authority='synthetic owner'); y=upload('dna',B,owner=b,consent='authorized',authority='synthetic owner')
    assert x.status_code==y.status_code==200,(x.text,y.text)
    assert client.get('/api/people/'+a).json()['dna'][0]['id']==x.json()['id']
    assert client.get('/api/people/'+b).json()['dna'][0]['id']==y.json()['id']
    assert upload('dna',A,owner=b,consent='authorized',authority='owner').status_code==409
    with module.db() as c:assert b'rs1' not in c.execute('SELECT blob FROM dna LIMIT 1').fetchone()[0]
    assert client.get('/api/compare',params={'a':x.json()['id'],'b':y.json()['id']}).json()['agreement']==.5

def test_02_gedcom():
    r=upload('gedcom',GED,namespace='fixture-tree');assert r.status_code==200,r.text
    assert r.json()['created']==2
    assert client.get('/api/people/'+r.json()['ids']['@I1@']).json()['birth']=='1 JAN 1900'

def test_03_relatives_csv():
    owner=person('CSV owner');r=upload('relatives',CSV,owner=owner,consent='authorized');assert r.status_code==200,r.text
    assert r.json()['created']==1
    assert upload('relatives',CSV,owner=owner,consent='authorized').json()['duplicate']
    assert upload('relatives',b'name,cm\nwrong,2',owner=owner,consent='authorized').status_code==422

def test_04_dedup_incremental():
    r=upload('gedcom',GED,namespace='fixture-tree');assert r.json()['duplicate']
    changed=GED.replace(b'0 TRLR',b'0 @I3@ INDI\n1 NAME New /Example/\n0 TRLR')
    assert upload('gedcom',changed,namespace='fixture-tree').json()['created']==1

def test_05_generations():
    ids=[person('Generation '+str(i)) for i in range(5)]
    for a,b in zip(ids,ids[1:]):assert client.post('/api/edges',json={'a':a,'b':b,'kind':'parent','status':'documented','citation':'Synthetic record'}).status_code==200
    r=client.get('/api/relationship',params={'a':ids[0],'b':ids[4]}).json();assert r['label']=='2× great-grandparent';assert len(r['path'])==5
    assert client.post('/api/edges',json={'a':ids[-1],'b':ids[0],'kind':'parent'}).status_code==422

def test_06_uncertain_unknown():
    a,b=person('Unknown A'),person('Unknown B');client.post('/api/edges',json={'a':a,'b':b,'kind':'parent','status':'hypothesis'})
    assert client.get('/api/relationship',params={'a':a,'b':b}).json()['status']=='unknown'

def test_07_restart_persistence():
    old=client.get('/api/graph').json();importlib.reload(module); fresh=TestClient(module.app)
    assert fresh.post('/api/unlock',json={'password':'synthetic-testing-only'}).status_code==200
    new=fresh.get('/api/graph').json();assert new==old
    client.cookies.update(fresh.cookies)

def test_08_malformed_and_consent():
    p=person('Invalid');n=len(client.get('/api/dna').json())
    for data in (b'garbage',b'# build 37\nrs1 99 -1 QZ\n',b'# no SNPs'):
        assert upload('dna',data,owner=p,consent='authorized',authority='owner').status_code==422
    assert upload('dna',A,owner=p,consent='no',authority='').status_code==422
    assert len(client.get('/api/dna').json())==n

def test_09_revoke():
    d=client.get('/api/dna').json()[0];p=d['person'];assert client.delete('/api/people/'+p+'/dna').json()['deleted']==1
    assert client.get('/api/people/'+p).json()['dna']==[]
    assert client.get('/api/compare',params={'a':d['id'],'b':d['id']}).status_code==404

def test_10_large_network_pagination():
    with module.db() as c:
        ids=[module.create_person(c,{'name':f'Large fixture {i:05}','synthetic':1}) for i in range(10000)]
        c.executemany('INSERT INTO edges VALUES(?,?,?,?,?,?)',[(module.uid(),ids[i],ids[i+1],'parent','hypothesis','synthetic performance fixture') for i in range(9999)])
    r=client.get('/api/graph?limit=10000').json();assert len(r['nodes'])==200;assert r['total']>=10000
    assert len(client.get('/api/graph?offset=200&limit=100').json()['nodes'])==100

def test_11_merge_and_evidence():
    a,b=person('Merge Example'),person('Merge Example');client.post('/api/evidence',json={'person':b,'title':'Synthetic record','url':'https://example.org'})
    assert client.post('/api/merge',json={'keep':a,'remove':b,'approved':True,'reason':'Synthetic identity review'}).status_code==200
    assert len(client.get('/api/people/'+a).json()['evidence'])==1
    assert client.get('/api/people/'+b).status_code==404

def test_12_backup_photo_security():
    from PIL import Image
    p=person('Photo Example');im=io.BytesIO();Image.new('RGB',(20,20),'green').save(im,'PNG')
    r=client.post('/api/photos',data={'owner':p,'permission':'Synthetic picture'},files={'file':('test.png',im.getvalue())});assert r.status_code==200,r.text
    assert client.get('/api/photos/'+r.json()['id']).headers['content-type']=='image/jpeg'
    backup=client.get('/api/backup');assert backup.status_code==200
    with zipfile.ZipFile(io.BytesIO(backup.content)) as z:assert 'worldtree.sqlite.encrypted' in z.namelist()
    assert TestClient(module.app).get('/api/export').status_code==401
    assert client.post('/api/people',json={'name':'blocked'},headers={'origin':'https://evil.example'}).status_code==403
