"""Native Qt application. Embedded loopback service is owned by this process.
No terminal or user-started development server. Data always lives outside bundle.
"""
import os,sys,json,threading,time,urllib.request,urllib.parse,http.cookiejar,sqlite3,shutil,base64,zipfile
from pathlib import Path
from PySide6.QtCore import Qt,QUrl,QTimer,QStandardPaths,Signal,QObject,QRunnable,QThreadPool
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,QListWidget,QStackedWidget,QLineEdit,QComboBox,QFormLayout,QTextEdit,QTableWidget,QTableWidgetItem,QFileDialog,QMessageBox,QInputDialog,QSplitter,QCheckBox)
from PySide6.QtGui import QPainter,QColor,QPen,QFont,QDesktopServices
from PySide6.QtNetwork import QNetworkCookie
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
import uvicorn

class Signals(QObject):
    done=Signal(object);error=Signal(str)
class Job(QRunnable):
    def __init__(self,fn):super().__init__();self.fn=fn;self.signals=Signals()
    def run(self):
        try:self.signals.done.emit(self.fn())
        except Exception as e:self.signals.error.emit(str(e))

class API:
    def __init__(self):self.jar=http.cookiejar.CookieJar();self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
    def call(self,path,data=None,method=None):
        req=urllib.request.Request('http://127.0.0.1:8765/api/'+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'},method=method or ('POST' if data is not None else 'GET'))
        try:
            with self.opener.open(req,timeout=60) as r:return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:message=json.loads(e.read()).get('detail',str(e))
            except Exception:message=str(e)
            raise ValueError(message)
    def upload(self,path,filename,fields):
        import uuid
        boundary=uuid.uuid4().hex;data=bytearray()
        for k,v in fields.items():data.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        data.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="upload.dat"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode());data.extend(Path(filename).read_bytes());data.extend(f'\r\n--{boundary}--\r\n'.encode())
        req=urllib.request.Request('http://127.0.0.1:8765/api/'+path,data=bytes(data),headers={'Content-Type':'multipart/form-data; boundary='+boundary})
        try:
            with self.opener.open(req,timeout=120) as r:return json.loads(r.read())
        except urllib.error.HTTPError as e:raise ValueError(e.read().decode())
    def download(self,path,dest):
        with self.opener.open('http://127.0.0.1:8765/api/'+path,timeout=120) as r:Path(dest).write_bytes(r.read())

class MapCanvas(QWidget):
    def __init__(self):super().__init__();self.events=[];self.setMinimumHeight(400)
    def paintEvent(self,event):
        p=QPainter(self);p.fillRect(self.rect(),QColor('#0c2027'));p.setRenderHint(QPainter.Antialiasing);w,h=self.width(),self.height();p.setPen(QPen(QColor('#2c4449'),1))
        for lon in range(-180,181,30):x=(lon+180)/360*w;p.drawLine(int(x),0,int(x),h)
        for lat in range(-90,91,30):y=(90-lat)/180*h;p.drawLine(0,int(y),w,int(y))
        groups={}
        for e in self.events:groups.setdefault(e['person'],[]).append(e)
        for es in groups.values():
            es.sort(key=lambda e:e['date']);prev=None
            for e in es:
                x=(e['lon']+180)/360*w;y=(90-e['lat'])/180*h;p.setPen(QPen(QColor('#d8bb70'),2))
                if prev:p.drawLine(int(prev[0]),int(prev[1]),int(x),int(y))
                p.setBrush(QColor('#67c5a8'));p.drawEllipse(int(x)-4,int(y)-4,8,8);p.drawText(int(x)+7,int(y)-5,e['place']);prev=(x,y)
        p.setPen(QColor('#afc0bd'));p.drawText(12,h-12,'Offline longitude/latitude plot · reported events, not inferred travel routes · no basemap')

STYLE='''QMainWindow,QWidget{background:#101d25;color:#dbe7e3;font-family:Segoe UI;font-size:13px}QListWidget{background:#0c171e;border:0;padding:12px;min-width:235px}QListWidget::item{padding:12px 8px}QListWidget::item:selected{background:#254e43;color:#e9dbb2;border-radius:5px}QLineEdit,QComboBox,QTextEdit,QTableWidget{background:#152a31;border:1px solid #36504f;border-radius:5px;padding:8px;selection-background-color:#38775f}QPushButton{background:#285443;border:1px solid #457463;border-radius:5px;padding:10px 16px}QPushButton:hover{background:#36705a}QLabel#title{font-size:30px;color:#ddc788;font-weight:500}QLabel#subtitle{color:#9eb8b0;padding:8px 0}QHeaderView::section{background:#244039;color:#e0dfbd;padding:7px;border:0}QMenuBar,QMenu{background:#14292d;color:#dae5df}'''

class Window(QMainWindow):
    def __init__(self,api,server):
        super().__init__();self.api=api;self.server=server;self.pool=QThreadPool();self.jobs=[];self.setWindowTitle('WorldTree AI — V0.2 Connected Ancestry');self.resize(1450,940);self.setStyleSheet(STYLE)
        root=QWidget();self.setCentralWidget(root);layout=QHBoxLayout(root);layout.setContentsMargins(0,0,0,0);self.nav=QListWidget();self.nav.setMaximumWidth(280);layout.addWidget(self.nav);self.stack=QStackedWidget();layout.addWidget(self.stack,1)
        self.web_available=False;self.pending_web=0
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtWebEngineCore import QWebEngineProfile,QWebEnginePage
            self.web=QWebEngineView();self.webprofile=QWebEngineProfile(self);self.webprofile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache);self.webprofile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies);self.web.setPage(QWebEnginePage(self.webprofile,self.web));self.webprofile.downloadRequested.connect(self.web_download)
            for cookie in self.api.jar:
                q=QNetworkCookie(cookie.name.encode(),cookie.value.encode());q.setHttpOnly(True);q.setPath('/');self.webprofile.cookieStore().setCookie(q,QUrl('http://127.0.0.1:8765'))
            self.web_available=True;self.web.load(QUrl('http://127.0.0.1:8765/?desktop=1'));self.web.loadFinished.connect(self.web_ready)
        except ImportError as e:
            self.web=QTextEdit();self.web.setReadOnly(True);self.web.setPlainText('Embedded graph/browser tools unavailable in this environment: '+str(e)+'\nNative tools remain available. Use a complete Windows portable build for the bundled WebEngine runtime.')
        self.stack.addWidget(self.web)
        self.modules={};self.builders={0:self.dashboard,2:self.familysearch,3:self.vault,4:self.matches,5:self.famous,6:self.ancient,7:self.duplicates,8:self.relationship,9:self.detective,11:self.map_page,13:self.research,15:self.import_manager,17:self.settings}
        self.names=['WorldTree Dashboard','Global Family Tree','FamilySearch Bridge','Offline Family Vault','DNA Match Intelligence','Famous Relative Explorer','Ancient Connection Explorer','Smart Duplicate Finder','Advanced Relationship Calculator','Missing Ancestor Detective','Historical Timeline','World Migration Map','Ancestral Portrait Studio','Research Center','Genetic Data Laboratory','Import & Export Manager','Privacy & Permissions','Application Settings']
        self.nav.addItems(self.names);self.nav.currentRowChanged.connect(self.navigate);self.nav.setCurrentRow(0)
        menu=self.menuBar().addMenu('Vault');menu.addAction('Encrypted backup…',self.backup);menu.addAction('Restore backup into a new vault…',self.restore);menu.addAction('Import V0.1 vault…',self.migrate_v01);menu.addAction('Lock and exit',self.close)
        self.statusBar().showMessage('Local private workspace • V0.2 • No external DNA uploads')
    def web_ready(self,ok):
        if ok:
            self.web.page().runJavaScript("window.dispatchEvent(new Event('worldtree-desktop-unlocked'));")
            QTimer.singleShot(500,lambda:self.web_select(self.pending_web))
    def web_select(self,n):
        if self.web_available:self.web.page().runJavaScript(f"document.querySelectorAll('nav button')[{n}]?.click()")
    def navigate(self,n):
        if n in self.builders:
            if n not in self.modules:
                widget=self.builders[n]();self.modules[n]=widget;self.stack.addWidget(widget)
            self.stack.setCurrentWidget(self.modules[n])
        else:
            mapping={0:0,1:1,10:7,12:6,14:3,16:10};self.pending_web=mapping.get(n,0);self.stack.setCurrentWidget(self.web);self.web_select(self.pending_web)
    def page(self,title,subtitle):
        w=QWidget();l=QVBoxLayout(w);l.setContentsMargins(30,22,30,22);a=QLabel(title);a.setObjectName('title');l.addWidget(a);b=QLabel(subtitle);b.setWordWrap(True);b.setObjectName('subtitle');l.addWidget(b);return w,l
    def output(self,l):
        o=QTextEdit();o.setReadOnly(True);l.addWidget(o,1);return o
    def button(self,l,text,fn):
        b=QPushButton(text);b.clicked.connect(fn);l.addWidget(b);return b
    def field(self,l,label,placeholder=''):
        l.addWidget(QLabel(label));i=QLineEdit();i.setPlaceholderText(placeholder);l.addWidget(i);return i
    def person_picker(self,l,label):
        l.addWidget(QLabel(label));row=QHBoxLayout();search=QLineEdit();search.setPlaceholderText('Search all profiles by name');combo=QComboBox();combo.setMinimumWidth(250);row.addWidget(search);row.addWidget(combo,1);l.addLayout(row)
        def load():
            try:
                ps=self.api.call('v02/search?q='+urllib.parse.quote(search.text()));combo.clear()
                for p in ps:combo.addItem(p['name']+' · '+(p['birth']or'?'),p['id'])
            except Exception as e:self.error(str(e))
        search.returnPressed.connect(load);load();return combo
    def display_result(self,out,data):out.setPlainText(json.dumps(data,indent=2,ensure_ascii=False) if not isinstance(data,str) else data)
    def error(self,msg):QMessageBox.warning(self,'WorldTree',msg)
    def work(self,fn,out=None,callback=None):
        job=Job(fn);self.jobs.append(job);self.statusBar().showMessage('Working…')
        def done(result):
            if out:self.display_result(out,result)
            if callback:callback(result)
            self.statusBar().showMessage('Completed • Local records preserved');self.jobs.remove(job)
        def failed(msg):
            if out:self.display_result(out,{'status':'blocked','reason':msg})
            else:self.error(msg)
            self.statusBar().showMessage('Action could not complete');self.jobs.remove(job)
        job.signals.done.connect(done);job.signals.error.connect(failed);self.pool.start(job)
    def dashboard(self):
        w,l=self.page('WorldTree Master','CONNECTED ANCESTRY  /  VERSION 0.2  /  PRIVATE LOCAL WORKSPACE')
        hero=QLabel('Every connection starts with evidence.');hero.setStyleSheet('font-size:32px;padding:30px;background:#203e36;color:#e9dab0;border-radius:12px');l.addWidget(hero)
        table=QTableWidget(0,2);table.setHorizontalHeaderLabels(['Your local collection','Records']);table.horizontalHeader().setStretchLastSection(True);table.setColumnWidth(0,400);l.addWidget(table,1)
        note=QLabel('Loading local counts…');note.setWordWrap(True);l.addWidget(note)
        def loaded(data):
            stats={**data['vault'],**data['connected']};table.setRowCount(0)
            labels={'people':'Family profiles','edges':'Family relationships','dna':'Authorized DNA files','matches':'Imported DNA matches','photos':'Stored photographs','sources':'Retained public source records','ancient_samples':'Indexed ancient sample records','familysearch_profiles':'FamilySearch-origin profiles','events':'Documented location events','family_networks':'Disconnected family networks','verified_direct_ancestors':'Documented direct ancestors (set reference)','profiles_with_incomplete_documented_parentage':'Profiles with incomplete documented parentage','proposed_famous_connections':'Proposed famous markers','verified_famous_markers':'User-verified famous markers'}
            for k,title in labels.items():
                row=table.rowCount();table.insertRow(row);table.setItem(row,0,QTableWidgetItem(title));table.setItem(row,1,QTableWidgetItem('Reference not set' if stats.get(k)==None else str(stats.get(k,0))))
            n=data['dashboard'].get('synthetic',0);note.setText(('SYNTHETIC DEMONSTRATION — '+str(n)+' fictional profiles. ' if n else '')+'No ancestors, DNA results or discoveries are invented. Online research is optional.')
        def refresh():self.work(lambda:{'vault':self.api.call('v02/vault'),'dashboard':self.api.call('dashboard'),'connected':self.api.call('v02/dashboard')},callback=loaded)
        self.button(l,'Refresh dashboard',refresh)
        self.button(l,'Initialize synthetic demo (empty vault only)',lambda:self.work(lambda:self.api.call('demo',{}),callback=lambda _:refresh()))
        refresh();return w
    def familysearch(self):
        w,l=self.page('FamilySearch Bridge','Official browser-based PKCE sign-in requires your approved client ID and registered callback. FamilySearch writes are disabled. Live authentication remains unverified.')
        clientid=self.field(l,'Registered FamilySearch application client ID (not your account password)');environment=QComboBox();environment.addItems(['beta','production']);l.addWidget(environment);registered=QCheckBox('My application is registered for this environment and callback: http://127.0.0.1:8765/familysearch/callback');l.addWidget(registered)
        pid=self.field(l,'FamilySearch person ID');generations=self.field(l,'Ancestor generations (1–8)');generations.setText('3');permission=self.field(l,'Authorization to retain an independent offline copy')
        source=self.field(l,'Source namespace','familysearch-my-tree');source.setText('familysearch-import');out=self.output(l)
        def signin():
            data={'client_id':clientid.text(),'environment':environment.currentText(),'registered_application':registered.isChecked()};self.work(lambda:self.api.call('v02/familysearch/start',data),callback=lambda r:QDesktopServices.openUrl(QUrl(r['authorization_url'])))
        self.button(l,'Sign in through FamilySearch',signin)
        self.button(l,'Check sign-in status',lambda:self.work(lambda:self.api.call('v02/familysearch/status'),out))
        self.button(l,'Import authorized ancestor branch',lambda:self.work(lambda:self.api.call('v02/familysearch/import',{'person_id':pid.text(),'generations':generations.text(),'retention_permission':permission.text()}),out))
        self.button(l,'Import a legitimate GEDCOM export',lambda:self.upload_dialog('import/gedcom',{'namespace':source.text()},out))
        self.button(l,'List imported FamilySearch identities',lambda:self.work(lambda:self.api.call('v02/search?provider=FamilySearch'),out))
        self.display_result(out,'Import a GEDCOM exported by a compatible genealogy application. _FSFTID/_FSID identifiers are retained. Editing the local copy never sends writes to FamilySearch. OAuth PKCE and bounded ancestor retrieval are implemented but require an approved app registration; live sign-in is not yet verified.');return w
    def vault(self):
        w,l=self.page('Offline Family Vault','Locally imported profiles, photos, citations, DNA matches and research results remain available offline.');out=self.output(l);self.button(l,'Refresh storage inventory',lambda:self.work(lambda:self.api.call('v02/vault'),out));self.button(l,'Create encrypted backup',self.backup);self.button(l,'Restore into a new vault',self.restore);self.work(lambda:self.api.call('v02/vault'),out);return w
    def relationship(self):
        w,l=self.page('Advanced Relationship Calculator','Recorded biological descent is evaluated before adoptive or marriage paths. Multiple ancestral paths retain their citations.');a=self.person_picker(l,'Person A');b=self.person_picker(l,'Person B');out=self.output(l)
        def calc():
            import html
            x,y=a.currentData(),b.currentData()
            def compute():
                result=self.api.call(f'v02/relationship?a={x}&b={y}');ids={p for r in result['relationships'] for p in r['path']};names={p:self.api.call('people/'+p)['name'] for p in ids};parts=[]
                for r in result['relationships']:
                    parts.append('<h2 style="color:#ddc788">'+html.escape(r['label'])+'</h2><p>'+html.escape(r.get('classification',result['classification']))+'</p><p style="font-size:16px">'+' → '.join(html.escape(names[p]) for p in r['path'])+'</p>')
                    if r.get('common_ancestor'):parts.append('<p>Common ancestor: <b>'+html.escape(names[r['common_ancestor']])+'</b></p>')
                    parts.append('<h3>Supporting relationship records</h3>')
                    for e in r.get('evidence',[]):parts.append('<p>'+html.escape(names[e['a']])+' → '+html.escape(names[e['b']])+': '+html.escape(e['kind'])+'<br><span style="color:#acc4ba">'+html.escape(e['citation'])+'</span></p>')
                    parts.append('<hr>')
                if not parts:parts=['<h2>No documented connection found</h2><p>'+html.escape(result.get('message',''))+'</p>']
                parts.append('<p>Calculated from recorded family evidence, not independent DNA proof.'+(' Search limits reached; additional paths may exist.' if result.get('truncated') else '')+'</p>');return ''.join(parts)
            self.work(compute,callback=out.setHtml)
        self.button(l,'Calculate relationship',calc);self.button(l,'Export displayed relationship report',lambda:self.save_text(out.toPlainText(),'relationship-report.txt'));return w
    def matches(self):
        w,l=self.page('DNA Match Intelligence','Shared-match groups are research clusters, not proven ancestral branches. Provider predictions are preserved; cM probabilities and IBD are not implemented.');owner=self.person_picker(l,'Reference DNA owner');a=self.person_picker(l,'Shared match A');b=self.person_picker(l,'Shared match B');source=self.field(l,'Provider evidence for shared match');out=self.output(l)
        self.button(l,'Inspect matches, common ancestors and clusters',lambda:self.work(lambda:self.api.call('v02/match-intelligence/'+owner.currentData()),out))
        self.button(l,'Record authorized shared-match evidence',lambda:self.work(lambda:self.api.call('v02/shared-matches',{'owner':owner.currentData(),'a':a.currentData(),'b':b.currentData(),'source':source.text()}),out));return w
    def famous(self):
        w,l=self.page('Famous Relative Explorer','Tag a sourced notable profile, then calculate connections through your local documented tree. No connections are invented.');ref=self.person_picker(l,'Your reference profile');p=self.person_picker(l,'Notable profile');source=self.field(l,'Public source citation URL');cat=self.field(l,'Category','Scientist, author, historical leader…');out=self.output(l)
        self.button(l,'Register sourced notable profile',lambda:self.work(lambda:self.api.call('v02/famous',{'person':p.currentData(),'source':source.text(),'category':cat.text()}),out));self.button(l,'Find documented famous connections',lambda:self.work(lambda:self.api.call('v02/famous/'+ref.currentData()),out));self.button(l,'Create evidence-review notification for selected pair',lambda:self.work(lambda:self.api.call('v02/famous/notify',{'reference':ref.currentData(),'person':p.currentData()}),out));return w
    def ancient(self):
        w,l=self.page('Ancient Connection Explorer','Metadata browser and experimental marker concordance. Population affinity, IBD, PCA and direct ancestry inference are not implemented.');row=QHBoxLayout();l.addLayout(row);dataset=self.field(row,'Dataset','AADR');version=self.field(row,'Version');license=self.field(row,'Reuse terms','CC0 only if verified in source');citation=self.field(l,'Dataset/study citation URL');selected=self.field(l,'Target sample IDs (comma-separated; blank imports all eligible metadata)');out=self.output(l)
        self.button(l,'Inspect public AADR metadata catalog (online)',lambda:self.work(lambda:self.api.call('v02/ancient/catalog'),out))
        self.button(l,'Import local annotation CSV/TSV',lambda:self.upload_dialog('v02/ancient/import',{'dataset':dataset.text(),'version':version.text(),'license':license.text(),'citation':citation.text(),'sample_ids':selected.text()},out))
        fileid=self.field(l,'Catalog annotation file ID (metadata only, max 50 MB)');terms=QCheckBox('I reviewed and accept the repository terms shown in the catalog');l.addWidget(terms);self.button(l,'Download / resume public annotation file',lambda:self.work(lambda:self.api.call('v02/ancient/download',{'file_id':fileid.text(),'accept_terms':terms.isChecked()}),out))
        ena=self.field(l,'ENA public study accession','PRJEB6272');self.button(l,'Download ENA public study metadata',lambda:self.work(lambda:self.api.call('v02/ancient/ena-metadata',{'accession':ena.text(),'accept_terms':terms.isChecked()}),out))
        q=self.field(l,'Search indexed samples by ID, site or country');self.button(l,'Browse offline samples',lambda:self.work(lambda:self.api.call('v02/ancient?q='+urllib.parse.quote(q.text())),out));self.button(l,'View saved comparison results',lambda:self.work(lambda:self.api.call('v02/ancient/results'),out));self.button(l,'Experimental comparison with selected ancient SNP file',lambda:self.ancient_compare_dialog(out));return w
    def ancient_compare_dialog(self,out):
        try:
            files=self.api.call('dna');samples=self.api.call('v02/ancient')
            if not files or not samples:raise ValueError('Import an authorized DNA file and index an ancient sample first.')
            options=[f"{i+1}. {d['provider']} | build {d['build']} | {d['id']}" for i,d in enumerate(files)]
            chosen,ok=QInputDialog.getItem(self,'Authorized DNA file','Choose a consented modern file',options,0,False)
            if not ok:return
            dna=files[options.index(chosen)]
            options=[f"{i+1}. {s['sample_id']} | {s['dataset']}" for i,s in enumerate(samples)]
            chosen,ok=QInputDialog.getItem(self,'Ancient reference','Choose the sample corresponding to your authorized SNP file',options,0,False)
            if not ok:return
            sample=samples[options.index(chosen)];a,ok=QInputDialog.getItem(self,'Modern strand','Verified strand from source documentation',['forward','reverse'],0,False)
            if not ok:return
            b,ok=QInputDialog.getItem(self,'Ancient strand','Verified strand from source documentation',['forward','reverse'],0,False)
            if not ok:return
            self.upload_dialog('v02/ancient/compare',{'dna_id':dna['id'],'sample_id':sample['id'],'modern_strand':a,'ancient_strand':b},out)
        except Exception as e:self.error(str(e))
    def duplicates(self):
        w,l=self.page('Smart Duplicate Finder','Indexed surname candidates with matching fields and conflicts. Merges require review. Undo is available before further database changes.');combo=QComboBox();l.addWidget(combo);out=self.output(l);self.candidates=[]
        def loaded(rs):
            self.candidates=rs;combo.clear()
            for r in rs:combo.addItem(r['a']['name']+' ↔ '+r['b']['name']+f"  [{r['score']}]")
        def display(i):
            if 0<=i<len(self.candidates):self.display_result(out,self.candidates[i])
        combo.currentIndexChanged.connect(display)
        self.button(l,'Find candidates',lambda:self.work(lambda:self.api.call('v02/duplicates'),callback=loaded))
        reason=self.field(l,'Review reason and supporting evidence')
        def act(state):
            i=combo.currentIndex()
            if i<0:return
            r=self.candidates[i];a,b=r['a']['id'],r['b']['id'];why=reason.text()
            if state=='merge':
                if QMessageBox.question(self,'Approve merge','Keep the first profile and merge the second? Original facts are retained in history.')!=QMessageBox.Yes:return
                self.work(lambda:self.api.call('v02/merge',{'keep':a,'remove':b,'approved':True,'reason':why}),out)
            else:self.work(lambda:self.api.call('v02/duplicates/review',{'a':a,'b':b,'state':state,'reason':why}),out)
        row=QHBoxLayout();l.addLayout(row)
        for text,state in [('Merge profiles','merge'),('Keep separate','separate'),('Possible duplicate','possible'),('Reject match','rejected'),('Review later','later')]:self.button(row,text,lambda checked=False,s=state:act(s))
        self.button(l,'Show merge history',lambda:self.work(lambda:self.api.call('v02/merges'),out))
        def undo():
            ident,ok=QInputDialog.getText(self,'Undo merge','Merge ID from history:')
            if ok:self.work(lambda:self.api.call('v02/merge/'+ident+'/undo',{}),out)
        self.button(l,'Undo reviewed merge',undo);return w
    def detective(self):
        w,l=self.page('WorldTree Ancestor Detective','Background public-record search creates evidence candidates only. Approve records in Research Center; relationships are never silently added.');p=self.person_picker(l,'Research target');question=self.field(l,'Research question','Research this person’s parents');consent=QCheckBox('Allow sending this selected profile name to the public Wikidata API (no DNA or private notes)');l.addWidget(consent);out=self.output(l)
        self.button(l,'Find local evidence gaps',lambda:self.work(lambda:self.api.call('v02/gaps/'+p.currentData()),out))
        self.button(l,'Queue public research',lambda:self.work(lambda:self.api.call('v02/research',{'person':p.currentData(),'question':question.text(),'allow_public_name_search':consent.isChecked()}),out))
        self.button(l,'Refresh research progress',lambda:self.work(lambda:self.api.call('tasks'),out));return w
    def research(self):
        w,l=self.page('Research Center','Public-source candidates remain separate until review. Approving imports a source profile, not a family connection.');p=self.person_picker(l,'Reference research profile');qid=self.field(l,'Wikidata identifier','Q42');out=self.output(l)
        self.button(l,'Retrieve public record as a proposal',lambda:self.work(lambda:self.api.call('v02/public/propose',{'person':p.currentData(),'qid':qid.text()}),out));self.button(l,'List proposed findings',lambda:self.work(lambda:self.api.call('v02/findings'),out));fid=self.field(l,'Finding ID to review');row=QHBoxLayout();l.addLayout(row)
        for decision in ['approve','reject']:self.button(row,decision.title(),lambda checked=False,d=decision:self.work(lambda:self.api.call('v02/findings/'+fid.text()+'/review',{'decision':d}),out))
        self.button(l,'View retained sources',lambda:self.work(lambda:self.api.call('v02/sources'),out));return w
    def map_page(self):
        w,l=self.page('World Migration Map','Offline coordinate view of cited events. No inferred coordinates or downloaded basemap. Dates are sorted as entered; use ISO dates for chronological routes.');p=self.person_picker(l,'Profile');row=QHBoxLayout();l.addLayout(row);date=self.field(row,'Date','YYYY-MM-DD');place=self.field(row,'Place');lat=self.field(row,'Latitude');lon=self.field(row,'Longitude');cite=self.field(l,'Supporting citation');canvas=MapCanvas();l.addWidget(canvas,1)
        def load(rs):canvas.events=rs;canvas.update()
        self.button(l,'Refresh recorded movements',lambda:self.work(lambda:self.api.call('v02/events'),callback=load))
        self.button(l,'Add documented event',lambda:self.work(lambda:self.api.call('v02/events',{'person':p.currentData(),'date':date.text(),'place':place.text(),'lat':lat.text(),'lon':lon.text(),'citation':cite.text()}),callback=lambda _:self.work(lambda:self.api.call('v02/events'),callback=load)));return w
    def import_manager(self):
        w,l=self.page('Import & Export Manager','V0.1 imports and encrypted backups remain compatible. Import FamilySearch-origin GEDCOM through the bridge.');self.button(l,'Open DNA / GEDCOM / CSV import tools',lambda:(self.stack.setCurrentWidget(self.web),self.web_select(9)));self.button(l,'Encrypted full backup',self.backup);self.button(l,'Restore backup into a new vault',self.restore);self.button(l,'Import V0.1 vault',self.migrate_v01);out=self.output(l)
        self.button(l,'Show import history',lambda:self.work(lambda:self.api.call('v02/import-history'),out));return w
    def settings(self):
        w,l=self.page('Application Settings','Feature availability is explicit. This build performs no provider writes or external genetic uploads.');out=self.output(l);reference=self.person_picker(l,'Reference person for direct-ancestor and unconnected markers');self.button(l,'Set reference person',lambda:self.work(lambda:self.api.call('v02/reference',{'person':reference.currentData()}),out));self.button(l,'Feature and connector status',lambda:self.work(lambda:self.api.call('v02/status'),out));self.button(l,'Show notifications',lambda:self.work(lambda:self.api.call('v02/notifications'),out));self.work(lambda:self.api.call('v02/status'),out);return w
    def upload_dialog(self,path,fields,out):
        filename,_=QFileDialog.getOpenFileName(self,'Choose authorized import')
        if filename:self.work(lambda:self.api.upload(path,filename,fields),out)
    def save_text(self,text,default):
        name,_=QFileDialog.getSaveFileName(self,'Save report',default)
        if name:Path(name).write_text(text,encoding='utf-8')
    def backup(self):
        name,_=QFileDialog.getSaveFileName(self,'Save encrypted backup','WorldTree-backup.zip','ZIP (*.zip)')
        if name:self.work(lambda:self.api.download('backup',name),callback=lambda _:QMessageBox.information(self,'Backup','Encrypted backup saved. Keep the passphrase separately.'))
    def web_download(self,download):
        name,_=QFileDialog.getSaveFileName(self,'Save file',download.downloadFileName())
        if name:download.setDownloadDirectory(str(Path(name).parent));download.setDownloadFileName(Path(name).name);download.accept()
        else:download.cancel()
    def restore(self):
        name,_=QFileDialog.getOpenFileName(self,'Choose encrypted backup','','ZIP (*.zip)')
        if not name:return
        parent=QFileDialog.getExistingDirectory(self,'Choose parent folder for new restored vault')
        if not parent:return
        password,ok=QInputDialog.getText(self,'Backup passphrase','Enter passphrase',QLineEdit.Password)
        if not ok:return
        def restore_job():
            with zipfile.ZipFile(name) as z:
                cfg=json.loads(z.read('vault.json'));key=base64.urlsafe_b64encode(Scrypt(salt=base64.b64decode(cfg['salt']),length=32,n=2**15,r=8,p=1).derive(password.encode()));raw=Fernet(key).decrypt(z.read('worldtree.sqlite.encrypted'))
            c=sqlite3.connect(':memory:');c.deserialize(raw)
            if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Invalid backup')
            c.close();dest=Path(parent)/('WorldTree-restored-'+str(int(time.time())));dest.mkdir();(dest/'worldtree.sqlite').write_bytes(raw);(dest/'vault.json').write_text(json.dumps(cfg));return str(dest)
        self.work(restore_job,callback=lambda d:QMessageBox.information(self,'Restored','Restored into '+d+'. Restart WorldTree, choose No at the default-vault prompt, then select this folder.'))
    def migrate_v01(self):
        source=QFileDialog.getExistingDirectory(self,'Select V0.1 data folder containing worldtree.sqlite and vault.json')
        if not source:return
        src=Path(source)
        if not (src/'worldtree.sqlite').exists() or not (src/'vault.json').exists():self.error('Select a complete V0.1 data directory.');return
        parent=QFileDialog.getExistingDirectory(self,'Choose parent folder for migrated copy')
        if not parent:return
        def copy():
            dest=Path(parent)/('WorldTree-migrated-'+str(int(time.time())));dest.mkdir();a=sqlite3.connect(src/'worldtree.sqlite');b=sqlite3.connect(dest/'worldtree.sqlite');a.backup(b);a.close();b.close();shutil.copy2(src/'vault.json',dest/'vault.json');return str(dest)
        self.work(copy,callback=lambda d:QMessageBox.information(self,'Copied','Original V0.1 vault unchanged. Reopen WorldTree and select '+d+'; schema migration runs automatically.'))
    def closeEvent(self,event):
        try:self.api.call('lock',{})
        except Exception:pass
        self.server.should_exit=True;event.accept()

def main():
    app=QApplication(sys.argv);app.setApplicationName('WorldTreeAI');app.setOrganizationName('WorldTreeAI')
    default=Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation));default.mkdir(parents=True,exist_ok=True)
    chosen=os.getenv('WORLDTREE_DATA')
    if not chosen:
        choice=QMessageBox.question(None,'WorldTree AI vault','Open the default local vault? Choose No to select a migrated or restored vault.',QMessageBox.Yes|QMessageBox.No)
        chosen=str(default) if choice==QMessageBox.Yes else QFileDialog.getExistingDirectory(None,'Choose existing vault folder')
        if not chosen:return 0
    os.environ['WORLDTREE_DATA']=chosen
    # Preflight refuses an occupied fixed port instead of attaching to an unknown service.
    import socket
    sock=socket.socket()
    try:sock.bind(('127.0.0.1',8765))
    except OSError:QMessageBox.critical(None,'Already running','Port 8765 is occupied. Close the other WorldTree instance.');return 1
    finally:sock.close()
    from backend.app import app as backend
    server=uvicorn.Server(uvicorn.Config(backend,host='127.0.0.1',port=8765,log_config=None,access_log=False));thread=threading.Thread(target=server.run,daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    api=API()
    while True:
        password,ok=QInputDialog.getText(None,'Unlock WorldTree','Create or enter your vault passphrase (12+ characters):',QLineEdit.Password)
        if not ok:server.should_exit=True;return 0
        try:api.call('unlock',{'password':password});break
        except Exception as e:QMessageBox.warning(None,'Unlock failed',str(e))
    window=Window(api,server);window.show();return app.exec()
if __name__=='__main__':raise SystemExit(main())
