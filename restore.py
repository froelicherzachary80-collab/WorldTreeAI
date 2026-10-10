"""Offline restore into a NEW directory; never overwrite a current vault."""
import argparse,base64,getpass,json,zipfile,sqlite3
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
p=argparse.ArgumentParser();p.add_argument('backup');p.add_argument('destination');a=p.parse_args();dest=Path(a.destination)
if dest.exists():raise SystemExit('Destination must not exist. Stop WorldTree before restoring.')
with zipfile.ZipFile(a.backup) as z:
    cfg=json.loads(z.read('vault.json'));password=getpass.getpass('Backup passphrase: ')
    key=base64.urlsafe_b64encode(Scrypt(salt=base64.b64decode(cfg['salt']),length=32,n=2**15,r=8,p=1).derive(password.encode()))
    raw=Fernet(key).decrypt(z.read('worldtree.sqlite.encrypted'))
c=sqlite3.connect(':memory:');c.deserialize(raw)
if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise SystemExit('Backup integrity check failed')
c.close();dest.mkdir(parents=True);(dest/'worldtree.sqlite').write_bytes(raw);(dest/'vault.json').write_text(json.dumps(cfg));print('Restored. Set WORLDTREE_DATA to this directory before starting.')
