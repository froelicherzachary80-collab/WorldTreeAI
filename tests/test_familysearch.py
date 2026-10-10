import json,urllib.parse,pytest
from backend.familysearch import FamilySearch,REDIRECT

def test_pkce_state_and_readonly_transport():
    fs=FamilySearch();start=fs.start('local-session','registered-test-key','beta');query=urllib.parse.parse_qs(urllib.parse.urlsplit(start['authorization_url']).query);state=query['state'][0]
    assert query['code_challenge_method']==['S256'];assert query['redirect_uri']==[REDIRECT]
    def exchange(req):
        assert req.full_url=='https://identbeta.familysearch.org/cis-web/oauth2/v3/token';body=urllib.parse.parse_qs(req.data.decode());assert body['grant_type']==['authorization_code'];assert len(body['code_verifier'][0])>=43;return {'access_token':'SYNTHETIC-TOKEN'}
    fs.callback(state,'SYNTHETIC-CODE',transport=exchange);assert fs.status('local-session')['connected']
    with pytest.raises(ValueError):fs.callback(state,'replay',transport=exchange)
    def read(req):
        assert req.method=='GET';assert req.full_url.startswith('https://apibeta.familysearch.org/platform/tree/ancestry?');assert req.headers['Authorization']=='Bearer SYNTHETIC-TOKEN';return {'persons':[]}
    assert fs.ancestry('local-session','TEST-123',3,transport=read)=={'persons':[]};fs.disconnect('local-session');assert not fs.status('local-session')['connected']

def test_oauth_wrong_state_and_denial():
    fs=FamilySearch()
    with pytest.raises(ValueError):fs.callback('wrong','code')
    state=urllib.parse.parse_qs(urllib.parse.urlsplit(fs.start('x','registered-key','production')['authorization_url']).query)['state'][0]
    with pytest.raises(ValueError):fs.callback(state,'',error='access_denied')
    assert not fs.status('x')['connected']

def test_source_payload_import_stays_local():
    from test_acceptance import module,client
    from backend.familysearch import import_ancestry
    payload={'persons':[{'id':'TEST-A','display':{'name':'Synthetic FS Child','ascendancyNumber':'1'}},{'id':'TEST-B','display':{'name':'Synthetic FS Parent','ascendancyNumber':'2'}}]}
    with module.db() as c:r=import_ancestry(c,payload,'beta','Synthetic fixture permission');assert r['created']==2 and r['edges_added']==1 and r['writes_to_familysearch']==0
    with module.db() as c:r=import_ancestry(c,payload,'beta','Synthetic fixture permission');assert r['created']==0

def test_expired_flow_and_token_are_rejected():
    import time
    fs=FamilySearch();state=urllib.parse.parse_qs(urllib.parse.urlsplit(fs.start('x','registered-key','beta')['authorization_url']).query)['state'][0];fs.pending[state]['expires']=time.monotonic()-1
    with pytest.raises(ValueError):fs.callback(state,'code')
    with pytest.raises(ValueError):fs.ancestry('x','TEST-123',9)
