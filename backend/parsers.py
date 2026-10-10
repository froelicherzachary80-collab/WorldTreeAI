import csv,io,re,zipfile

def unpack(data):
    if data[:2]==b'PK':
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            files=[f for f in z.infolist() if not f.is_dir()]
            if len(files)!=1 or files[0].file_size>80_000_000: raise ValueError('ZIP must contain one TXT file below 80 MB')
            data=z.read(files[0])
    return data.decode('utf-8-sig')

def dna_parse(data):
    text=unpack(data); rows={}; source='compatible SNP'; build='unknown'
    if 'ancestry' in text.lower(): source='AncestryDNA'
    if '23andme' in text.lower(): source='23andMe'
    m=re.search(r'(?:build|grch)[\s:=]*(37|38|36)',text,re.I)
    if m: build=m.group(1)
    for n,line in enumerate(text.splitlines(),1):
        if not line.strip() or line.startswith('#'): continue
        cells=re.split(r'\s+',line.strip())
        if cells[0].lower() in ('rsid','rs_id'): continue
        if len(cells) not in (4,5): raise ValueError(f'Invalid SNP columns at line {n}')
        rs,ch,pos=cells[:3]; gt=''.join(cells[3:]).upper()
        ch=ch.upper().removeprefix('CHR'); ch={'23':'X','24':'Y','25':'XY','26':'MT','M':'MT'}.get(ch,ch)
        if ch not in [str(i) for i in range(1,23)]+['X','Y','XY','MT'] or not pos.isdigit() or int(pos)<1: raise ValueError(f'Invalid coordinate at line {n}')
        if not re.fullmatch(r'[ACGTID\-0]{1,2}',gt): raise ValueError(f'Invalid genotype at line {n}')
        key=(ch,int(pos),rs)
        if key in rows and rows[key]!=gt: raise ValueError('Conflicting duplicate marker')
        rows[key]=gt
    if not rows: raise ValueError('No SNP markers found')
    return {'provider':source,'build':build,'markers':len(rows)},rows

def relatives_parse(data):
    reader=csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
    if not reader.fieldnames or 'Display Name' not in reader.fieldnames: raise ValueError('Expected DNA Relatives CSV with Display Name header')
    result=[]
    for row in reader:
        if not row['Display Name'].strip(): raise ValueError('Missing display name')
        def number(*keys):
            value=next((row[k] for k in keys if row.get(k)),None)
            if value is None: return None
            v=float(value.strip().removesuffix('%'))
            if v<0: raise ValueError('Negative DNA sharing value')
            return v
        pct=number('Percent DNA Shared','Shared DNA Percentage'); cm=number('Shared cM','Genetic Distance')
        if pct is not None and pct>100: raise ValueError('Invalid percentage')
        result.append({'name':row['Display Name'],'external_id':row.get('Profile URL') or row.get('Profile ID') or '', 'pct':pct,'cm':cm,'prediction':row.get('Predicted Relationship',''),'raw':row})
    return result

def gedcom_parse(data):
    text=data.decode('utf-8-sig'); people={}; families={}; current=None; event=None
    if '0 HEAD' not in text or '0 TRLR' not in text: raise ValueError('Expected GEDCOM HEAD and TRLR')
    for line in text.splitlines():
        m=re.match(r'^(\d+) (?:(@[^@]+@) )?(\S+)(?: (.*))?$',line)
        if not m: raise ValueError('Malformed GEDCOM line')
        level,ident,tag,value=m.groups(); level=int(level); value=value or ''
        if level==0:
            event=None; current=None
            if tag=='INDI': current=people.setdefault(ident,{'name':'Unnamed','birth':'','death':'','place':''})
            if tag=='FAM': current=families.setdefault(ident,{'parents':[],'children':[]})
        elif current is not None:
            if level==1: event=tag
            if tag=='NAME': current['name']=value.replace('/','').strip()
            elif tag in ('HUSB','WIFE'): current['parents'].append(value)
            elif tag=='CHIL': current['children'].append(value)
            elif tag in ('_FSFTID','_FSID'): current['familysearch_id']=value
            elif tag=='EXID': current['external_id']=value
            elif tag=='DATE' and event in ('BIRT','DEAT'): current['birth' if event=='BIRT' else 'death']=value
            elif tag=='PLAC' and event=='BIRT': current['place']=value
    if not people: raise ValueError('No individuals found')
    for f in families.values():
        if any(x not in people for x in f['parents']+f['children']): raise ValueError('Unresolved family pointer')
    return people,families
