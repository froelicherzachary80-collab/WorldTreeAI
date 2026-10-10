"""Official native-app OAuth PKCE; read-only ancestry transport.
Credentials are entered only at FamilySearch. Tokens remain in process memory.
"""
import secrets,hashlib,base64,time,json,re,urllib.request,urllib.parse
from threading import Lock
REDIRECT='http://127.0.0.1:8765/familysearch/callback'
ENVS={'beta':('https://identbeta.familysearch.org','https://apibeta.familysearch.org'),'production':('https://ident.familysearch.org','https://api.familysearch.org')}
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
class FamilySearch:
    def __init__(self):self.pending={};self.tokens={};self.lock=Lock()
    def start(self,session,client_id,environment):
        if not re.fullmatch(r'[A-Za-z0-9_-]{5,200}',client_id):raise ValueError('Enter your registered FamilySearch application client ID')
        if environment not in ENVS:raise ValueError('Unknown environment')
        state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48);challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        with self.lock:
            self.pending={k:v for k,v in self.pending.items() if v['expires']>time.monotonic() and v['session']!=session}
            self.pending[state]={'session':session,'client':client_id,'verifier':verifier,'environment':environment,'expires':time.monotonic()+600}
        return {'authorization_url':ENVS[environment][0]+'/cis-web/oauth2/v3/authorization?'+urllib.parse.urlencode({'client_id':client_id,'redirect_uri':REDIRECT,'response_type':'code','state':state,'code_challenge':challenge,'code_challenge_method':'S256'}),'redirect_uri':REDIRECT,'environment':environment}
    def callback(self,state,code,error='',transport=None):
        with self.lock:flow=self.pending.pop(state,None)
        if not flow or flow['expires']<time.monotonic():raise ValueError('Invalid, expired or already-used OAuth state')
        if error:raise ValueError('FamilySearch authorization was declined or failed')
        if not code or len(code)>4096:raise ValueError('Missing or invalid authorization code')
        body=urllib.parse.urlencode({'client_id':flow['client'],'code':code,'grant_type':'authorization_code','redirect_uri':REDIRECT,'code_verifier':flow['verifier']}).encode()
        req=urllib.request.Request(ENVS[flow['environment']][0]+'/cis-web/oauth2/v3/token',data=body,headers={'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'})
        if transport:payload=transport(req)
        else:
            with urllib.request.build_opener(NoRedirect()).open(req,timeout=30) as r:payload=json.loads(r.read(100000))
        if not isinstance(payload.get('access_token'),str):raise ValueError('Provider did not return an access token')
        with self.lock:self.tokens[flow['session']]={'token':payload['access_token'],'environment':flow['environment'],'expires':time.monotonic()+min(int(payload.get('expires_in',3600)),86400)}
        return {'connected':True,'environment':flow['environment']}
    def status(self,session):
        with self.lock:
            t=self.tokens.get(session)
            return {'connected':bool(t and t['expires']>time.monotonic()),'environment':t['environment'] if t else None,'write_operations':'disabled'}
    def disconnect(self,session):
        with self.lock:
            self.tokens.pop(session,None);self.pending={k:v for k,v in self.pending.items() if v['session']!=session}
    def ancestry(self,session,pid,generations,transport=None):
        if not re.fullmatch(r'[A-Za-z0-9-]{3,40}',pid) or not 1<=int(generations)<=8:raise ValueError('Valid person ID and 1–8 generations required')
        with self.lock:t=self.tokens.get(session)
        if not t or t['expires']<time.monotonic():raise ValueError('Sign in to FamilySearch using the approved application first')
        url=ENVS[t['environment']][1]+'/platform/tree/ancestry?'+urllib.parse.urlencode({'person':pid,'generations':int(generations),'personDetails':'true'})
        req=urllib.request.Request(url,headers={'Authorization':'Bearer '+t['token'],'Accept':'application/x-fs-v1+json','User-Agent':'WorldTreeAI/0.2.1'},method='GET')
        if transport:return transport(req)
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=30) as r:
            raw=r.read(8000001)
            if len(raw)>8000000:raise ValueError('Response exceeded safe branch-import size')
            return json.loads(raw)
bridge=FamilySearch()

def import_ancestry(c,payload,environment,permission):
    from .app import uid,now,create_person,audit
    if not permission.strip():raise ValueError('Record your permission to retain this independent offline copy')
    namespace='FamilySearch' if environment=='production' else 'FamilySearch-beta';ids={};ahnen={};count=0
    source=uid();c.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)',(source,namespace,'https://www.familysearch.org','Provider terms; user authorization recorded','authorized independent import',now(),'',json.dumps({'permission':permission,'payload':payload})))
    for record in payload.get('persons',[]):
        external=record.get('id');display=record.get('display',{})
        if not external:continue
        name=display.get('name') or next((form.get('fullText') for n in record.get('names',[]) for form in n.get('nameForms',[]) if form.get('fullText')),None)
        if not name:continue
        old=c.execute('SELECT person FROM identities WHERE namespace=? AND external_id=?',(namespace,external)).fetchone()
        p=old[0] if old else create_person(c,{'name':name,'birth':display.get('birthDate',''),'death':display.get('deathDate',''),'place':display.get('birthPlace',''),'status':'hypothesis'})
        if not old:c.execute('INSERT INTO identities VALUES(?,?,?)',(namespace,external,p));count+=1
        ids[external]=p
        number=str(display.get('ascendancyNumber',''))
        if number.isdigit():ahnen[int(number)]=p
        c.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?)',(uid(),p,'FamilySearch person record',('https://www.familysearch.org' if environment=='production' else 'https://beta.familysearch.org')+'/tree/person/details/'+external,'Imported source assertion; underlying citations retained in source payload; review required',0))
    edges=0
    for number,parent in ahnen.items():
        if number>1 and number//2 in ahnen and parent!=ahnen[number//2]:edges+=c.execute('INSERT OR IGNORE INTO edges VALUES(?,?,?,?,?,?)',(uid(),parent,ahnen[number//2],'parent','hypothesis',namespace+' authorized ancestry response; source '+source)).rowcount
    audit(c,'FamilySearch independent import',{'source':source,'created':count,'edges':edges});return {'created':count,'mapped':len(ids),'edges_added':edges,'source':source,'writes_to_familysearch':0,'status':'Source assertions require review'}
