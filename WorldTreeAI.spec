# Build ONLY on Windows x64. PyInstaller collects PySide6/QtWebEngine runtime hooks.
from pathlib import Path
root=Path(SPECPATH)
a=Analysis([str(root/'WorldTreeAI.py')],pathex=[str(root)],binaries=[],datas=[(str(root/'frontend/dist'),'frontend/dist'),(str(root/'backend/schema.sql'),'backend'),(str(root/'backend/schema_v02.sql'),'backend')],hiddenimports=['uvicorn.logging','uvicorn.loops.auto','uvicorn.protocols.http.auto','uvicorn.protocols.websockets.auto','uvicorn.lifespan.on','backend.app','backend.api_v02','rapidfuzz.fuzz'],hookspath=[],runtime_hooks=[],excludes=['tkinter'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='WorldTreeAI',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False,disable_windowed_traceback=False)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='WorldTreeAI')
