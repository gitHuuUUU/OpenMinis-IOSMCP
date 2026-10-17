#!/usr/bin/env python3
"""Dependency-free MCP stdio tools. No network listener or startup side effects."""
import argparse
import csv
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.parse
import zipfile

MAX_BYTES = 256 * 1024

def tool(name, description, properties, required=()):
    return dict(name=name, description=description, inputSchema=dict(type='object', properties=properties, required=list(required), additionalProperties=False))

S = {'type':'string'}
TOOLS = {
 'files': [tool('list_files','List up to 200 entries in a workspace directory.',{'path':S}),
           tool('read_text','Read bounded UTF-8 text with replacement for invalid bytes.',{'path':S},['path']),
           tool('write_text','Atomically write UTF-8 text; existing files require overwrite=true.',{'path':S,'text':S,'overwrite':{'type':'boolean'}},['path','text']),
           tool('sha256','Compute a file SHA256 without loading it all into memory.',{'path':S},['path'])],
 'project':[tool('search_text','Search text in workspace files, bounded traversal and 100 matches.',{'path':S,'query':S},['query']),
            tool('git_inspect','Git status/diff/log/show. No shell interpolation.',{'path':S,'action':{'enum':['status','diff','log','show']},'revision':S})],
 'database':[tool('sqlite_query','Read-only SQLite query with a 3s deadline and at most 200 rows.',{'path':S,'sql':S},['path','sql']),
             tool('sqlite_tables','Read-only SQLite table schema.',{'path':S},['path'])],
 'web':[tool('http_fetch','GET an HTTP(S) URL with a 15s timeout; bounded response, no saved credentials.',{'url':S},['url'])],
 'archive':[tool('zip_list','Inspect ZIP metadata without executing or extracting its entries.',{'path':S},['path'])],
 'data':[tool('json_format','Validate and pretty-print JSON (bounded input).',{'text':S},['text']),
         tool('csv_preview','Preview at most 100 CSV rows from a workspace file.',{'path':S},['path'])],
 'system':[tool('runtime_info','Report actual Python/platform/workspace/disk information.',{})]
}

class Server:
    def __init__(self, root, profile):
        self.root = Path(root).resolve()
        self.profile = profile
        self.tools = TOOLS[profile]

    def path(self, value='.'):
        p = Path(value)
        p = (p if p.is_absolute() else self.root/p).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError('Path escapes selected workspace root: '+str(self.root))
        return p

    def call(self, name, a):
        if name not in {t['name'] for t in self.tools}:
            raise ValueError('Tool not available in this MCP profile')
        if name == 'runtime_info':
            import shutil
            return dict(python=sys.version.split()[0],platform=platform.platform(),root=str(self.root),disk_free=shutil.disk_usage(self.root).free)
        if name == 'json_format':
            if len(a['text'].encode()) > MAX_BYTES: raise ValueError('Input too large')
            return json.dumps(json.loads(a['text']),ensure_ascii=False,indent=2)
        if name == 'http_fetch':
            url=a['url']
            if urllib.parse.urlparse(url).scheme not in ('http','https'): raise ValueError('HTTP(S) required')
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'MinisBuiltinMCP/1.0'}),timeout=15) as r:
                raw=r.read(MAX_BYTES+1)
                return dict(status=r.status,url=r.url,content_type=r.headers.get('Content-Type'),text=raw[:MAX_BYTES].decode('utf-8','replace'),truncated=len(raw)>MAX_BYTES)
        p=self.path(a.get('path','.'))
        if name=='list_files':
            import itertools
            entries=list(itertools.islice(p.iterdir(),201))
            return dict(entries=[dict(name=x.name,directory=x.is_dir(),symlink=x.is_symlink()) for x in entries[:200]],truncated=len(entries)>200)
        if name=='read_text':
            with p.open('rb') as f: raw=f.read(MAX_BYTES+1)
            return dict(text=raw[:MAX_BYTES].decode('utf-8','replace'),truncated=len(raw)>MAX_BYTES)
        if name=='write_text':
            raw=a['text'].encode('utf-8')
            if len(raw)>MAX_BYTES: raise ValueError('Input too large')
            if p.exists() and not a.get('overwrite',False): raise ValueError('Existing file: set overwrite=true explicitly')
            p.parent.mkdir(parents=True,exist_ok=True)
            fd, tmp=tempfile.mkstemp(prefix='.minis-write-',dir=p.parent)
            try:
                with os.fdopen(fd,'wb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
                # Hard-link creation is atomic and fails if another writer created p.
                if a.get('overwrite',False): os.replace(tmp,p)
                else: os.link(tmp,p)
            finally:
                if os.path.exists(tmp): os.unlink(tmp)
            return dict(path=str(p),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        if name=='sha256':
            with p.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
            return dict(path=str(p),sha256=digest,bytes=p.stat().st_size)
        if name=='search_text':
            query=a['query']
            if not query: raise ValueError('Empty query')
            matches=[]; count=0; deadline=time.monotonic()+5; truncated=False
            for directory,dirs,files in os.walk(p,followlinks=False):
                dirs[:]=[d for d in dirs if d not in ('.git','node_modules','.build','sdks','__pycache__') and not (Path(directory)/d).is_symlink()]
                for filename in files:
                    count+=1
                    if count>2000 or time.monotonic()>deadline: truncated=True; break
                    f=Path(directory)/filename
                    if f.is_symlink() or f.stat().st_size>MAX_BYTES: continue
                    try: text=f.read_text(encoding='utf-8')
                    except (UnicodeError,OSError): continue
                    for number,line in enumerate(text.splitlines(),1):
                        if query in line: matches.append(dict(path=str(f.relative_to(self.root)),line=number,text=line[:500]))
                        if len(matches)>=100: truncated=True; break
                    if truncated: break
                if truncated: break
            return dict(matches=matches,files_scanned=count,truncated=truncated)
        if name=='git_inspect':
            action=a.get('action','status')
            commands={'status':['status','--short'],'diff':['diff','--stat'],'log':['log','-10','--oneline'],'show':['show','--stat',a.get('revision','HEAD')]}
            if action not in commands or a.get('revision','HEAD').startswith('-'): raise ValueError('Invalid git action/revision')
            r=subprocess.run(['git','-C',str(p),*commands[action]],capture_output=True,timeout=20)
            return dict(exit_code=r.returncode,stdout=r.stdout[:MAX_BYTES].decode('utf-8','replace'),stderr=r.stderr[:4096].decode('utf-8','replace'))
        if name in ('sqlite_query','sqlite_tables'):
            sql=a.get('sql','SELECT name, sql FROM sqlite_master WHERE type IN (\'table\',\'view\')')
            deadline=time.monotonic()+3
            with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=2)) as c:
                c.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_BYTES)
                c.set_authorizer(lambda action,*_: sqlite3.SQLITE_DENY if action in (sqlite3.SQLITE_ATTACH,sqlite3.SQLITE_DETACH) else sqlite3.SQLITE_OK)
                c.execute('PRAGMA query_only=ON')
                c.enable_load_extension(False)
                c.set_progress_handler(lambda: int(time.monotonic()>deadline),1000)
                cur=c.execute(sql); rows=cur.fetchmany(201)
                def scalar(x): return {'hex':x.hex()} if isinstance(x,bytes) else x
                return dict(columns=[x[0] for x in (cur.description or [])],rows=[[scalar(v) for v in row] for row in rows[:200]],truncated=len(rows)>200)
        if name=='zip_list':
            with zipfile.ZipFile(p) as z:
                entries=z.infolist()
                return dict(entries=[dict(name=e.filename,bytes=e.file_size,compressed=e.compress_size) for e in entries[:500]],total=len(entries),truncated=len(entries)>500)
        if name=='csv_preview':
            with p.open('rb') as f: raw=f.read(MAX_BYTES+1)
            rows=[]
            for row in csv.reader(io.StringIO(raw[:MAX_BYTES].decode('utf-8-sig','replace'))):
                rows.append(row)
                if len(rows)>=100: break
            return dict(rows=rows,truncated=len(raw)>MAX_BYTES or len(rows)>=100)
        raise ValueError('Unknown tool')

    def handle(self, request):
        if 'id' not in request: return None
        response=dict(jsonrpc='2.0',id=request['id'])
        method=request.get('method'); params=request.get('params') or {}
        if method=='initialize':
            response['result']=dict(protocolVersion=params.get('protocolVersion','2025-06-18'),capabilities={'tools':{}},serverInfo={'name':'minis-builtin-'+self.profile,'version':'1.0.0'})
        elif method=='ping': response['result']={}
        elif method=='tools/list': response['result']={'tools':self.tools}
        elif method=='tools/call':
            try:
                value=self.call(params['name'],params.get('arguments') or {})
                text=json.dumps(value,ensure_ascii=False,default=str)
                if len(text.encode())>MAX_BYTES*2: raise ValueError('Result too large; narrow the query')
                response['result']={'content':[{'type':'text','text':text}],'isError':False}
            except Exception as e:
                response['result']={'content':[{'type':'text','text':str(e)[:2000]}],'isError':True}
        else: response['error']={'code':-32601,'message':'Method not found'}
        return response

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--profile',choices=TOOLS,required=True); parser.add_argument('--root',default='/var/minis')
    a=parser.parse_args(); server=Server(a.root,a.profile)
    # read bounded lines; stdout contains JSON-RPC only
    while True:
        line=sys.stdin.buffer.readline(MAX_BYTES*2+1)
        if not line: break
        if len(line)>MAX_BYTES*2: return 2
        try: response=server.handle(json.loads(line))
        except Exception: response={'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Invalid JSON-RPC request'}}
        if response is not None: print(json.dumps(response,ensure_ascii=False),flush=True)
    return 0

if __name__=='__main__': sys.exit(main())
