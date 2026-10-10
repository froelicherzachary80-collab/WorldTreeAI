import os,sys,tempfile,threading,time,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));os.environ['WORLDTREE_DATA']=tempfile.mkdtemp();os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QComboBox,QPushButton,QTextEdit
from PySide6.QtCore import QTimer
from desktop.main import Window,API
import uvicorn
from backend.app import app as backend
app=QApplication([]);server=uvicorn.Server(uvicorn.Config(backend,host='127.0.0.1',port=8765,log_config=None,access_log=False));threading.Thread(target=server.run,daemon=True).start()
for _ in range(100):
 if server.started:break
 time.sleep(.05)
api=API();api.call('unlock',{'password':'synthetic-desktop-test'});api.call('demo',{});w=Window(api,server);w.show();dest=Path(__file__).resolve().parents[1]/'screenshots';dest.mkdir(exist_ok=True);results={}
def capture():
 w.grab().save(str(dest/'WorldTreeAI-V02-Dashboard.png'))
 try:
  for n in w.builders:w.navigate(n)
  results['native_pages_constructed']=len(w.modules)==len(w.builders)
 except Exception as e:results['native_error']=str(e)
 results['qt_window_visible']=w.isVisible();results['embedded_webengine_available']=w.web_available;results['synthetic_profiles']=api.call('dashboard')['synthetic'];w.nav.setCurrentRow(8)
 combos=w.modules[8].findChildren(QComboBox)
 for i in range(combos[1].count()):
  if combos[1].itemText(i).startswith('Sam Example'):combos[1].setCurrentIndex(i)
 for button in w.modules[8].findChildren(QPushButton):
  if button.text()=='Calculate relationship':button.click()
 QTimer.singleShot(1500,finish)
def finish():
 results['native_relationship_calculated']=any('1st cousins' in o.toPlainText() for o in w.modules[8].findChildren(QTextEdit));w.grab().save(str(dest/'WorldTreeAI-V02-Relationship.png'));print(json.dumps(results));(dest/'native-smoke-results.json').write_text(json.dumps(results,indent=2));w.close();app.quit()
QTimer.singleShot(1500,capture);QTimer.singleShot(15000,finish);app.exec()
assert results.get('native_pages_constructed') and results.get('qt_window_visible'),results
