"""Linux/offscreen source GUI verification; does not validate a Windows EXE."""
import os,tempfile,sys,threading,time,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['WORLDTREE_DATA']=tempfile.mkdtemp();os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
if sys.platform!='win32':os.environ['QTWEBENGINE_DISABLE_SANDBOX']='1' # root-only CI test, never set by packaged app
from PySide6.QtWidgets import QApplication,QLabel,QTableWidget
from PySide6.QtCore import QTimer
from desktop.main import Window,API
import uvicorn
from backend.app import app as backend
app=QApplication([]);server=uvicorn.Server(uvicorn.Config(backend,host='127.0.0.1',port=8765,log_config=None,access_log=False));threading.Thread(target=server.run,daemon=True).start()
for _ in range(100):
 if server.started:break
 time.sleep(.05)
api=API();api.call('unlock',{'password':'synthetic-desktop-test'});api.call('demo',{})
w=Window(api,server);w.show();dest=Path(__file__).resolve().parents[1]/'screenshots';dest.mkdir(exist_ok=True);results={}
def inspect():
 results['dashboard_loaded']=any('WorldTree Master' in label.text() for label in w.modules[0].findChildren(QLabel))
 results['synthetic_label_visible']=any('7 fictional profiles' in label.text() for label in w.modules[0].findChildren(QLabel))
 w.grab().save(str(dest/'WorldTreeAI-V02-Dashboard.png'));w.nav.setCurrentRow(1);QTimer.singleShot(2500,graph)
def graph():
 w.web.page().runJavaScript("JSON.stringify({canvas:document.querySelectorAll('canvas').length,text:document.body.innerText})",graph_data)
def graph_data(data):
 data=json.loads(data or '{}');results['graph_labels_present']='Global Family Tree' in data.get('text','') and 'fictional profiles' in data.get('text','');graph_result(data.get('canvas',0))
def graph_result(count):
 results['graph_canvas_rendered']=count>0;w.grab().save(str(dest/'WorldTreeAI-V02-Graph.png'))
 try:
  for n in w.builders:w.navigate(n)
  results['native_pages_constructed']=len(w.modules)==len(w.builders)
 except Exception as e:results['native_error']=str(e)
 w.navigate(8);w.grab().save(str(dest/'WorldTreeAI-V02-Relationship.png'));QTimer.singleShot(1000,finish)
def finish():
 print(json.dumps(results));(dest/'desktop-smoke-results.json').write_text(json.dumps(results,indent=2));w.close();app.quit()
QTimer.singleShot(4500,inspect);QTimer.singleShot(20000,finish);app.exec()
assert results.get('dashboard_loaded') and results.get('synthetic_label_visible') and results.get('graph_labels_present') and results.get('graph_canvas_rendered') and results.get('native_pages_constructed'),results
