import os, re, json, sqlite3, hashlib, secrets, threading, asyncio, base64, struct, time, cgi, socket
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
DB='/app/huddle.db'
PORT=int(os.environ.get('PORT','8000')); NODE=(PORT-8000)//1
lock=threading.RLock()
ws_clients={}
def wsframe(data):
    n=len(data)
    if n<126:return bytes([129,n])+data
    if n<65536:return bytes([129,126])+struct.pack('>H',n)+data
    return bytes([129,127])+struct.pack('>Q',n)+data
def ws_broadcast(cid,event):
    raw=wsframe(json.dumps(event).encode())
    with lock:
        for so,channels in list(ws_clients.items()):
            if cid in channels:
                try: so.sendall(raw)
                except: ws_clients.pop(so,None)
def now(): return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
def db():
    c=sqlite3.connect(DB,timeout=15,check_same_thread=False); c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL'); return c
def init():
    c=db()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password TEXT,display_name TEXT,timezone TEXT DEFAULT 'UTC',avatar_url TEXT DEFAULT '',status_text TEXT DEFAULT '',status_emoji TEXT DEFAULT '',created_at TEXT);
    CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY,user_id INTEGER);
    CREATE TABLE IF NOT EXISTS workspaces(id INTEGER PRIMARY KEY,slug TEXT UNIQUE,name TEXT,owner_id INTEGER,join_mode TEXT DEFAULT 'open');
    CREATE TABLE IF NOT EXISTS members(workspace_id INTEGER,user_id INTEGER,role TEXT,PRIMARY KEY(workspace_id,user_id));
    CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY,workspace_id INTEGER,name TEXT,is_private INTEGER DEFAULT 0,is_dm INTEGER DEFAULT 0,topic TEXT DEFAULT '',is_archived INTEGER DEFAULT 0,UNIQUE(workspace_id,name));
    CREATE TABLE IF NOT EXISTS channel_members(channel_id INTEGER,user_id INTEGER,PRIMARY KEY(channel_id,user_id));
    CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,channel_id INTEGER,author_id INTEGER,body TEXT,parent_id INTEGER,created_at TEXT,edited_at TEXT,deleted INTEGER DEFAULT 0,event_id INTEGER);
    CREATE TABLE IF NOT EXISTS reactions(message_id INTEGER,user_id INTEGER,emoji TEXT,PRIMARY KEY(message_id,user_id,emoji));
    CREATE TABLE IF NOT EXISTS pins(message_id INTEGER PRIMARY KEY,pinned_by INTEGER,pinned_at TEXT);
    CREATE TABLE IF NOT EXISTS seq(channel_id INTEGER PRIMARY KEY,event_id INTEGER);
    CREATE TABLE IF NOT EXISTS read_state(channel_id INTEGER,user_id INTEGER,last_read_event_id INTEGER,PRIMARY KEY(channel_id,user_id));
    CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY,uploader_id INTEGER,filename TEXT,content_type TEXT,size INTEGER,data BLOB,created_at TEXT);
    '''); c.commit(); c.close()
init()
def userobj(r):
    return {k:r[k] for k in ('id','username','display_name','timezone','avatar_url','status_text','status_emoji')}
def getuser(c,uid): return c.execute('select * from users where id=?',(uid,)).fetchone()
def msgobj(c,r):
    a=getuser(c,r['author_id']); reps=c.execute('select emoji,count(*) n from reactions where message_id=? group by emoji',(r['id'],)).fetchall()
    mentions=[]; text=r['body'] or ''
    members=c.execute('select u.id,u.username from users u join channel_members cm on cm.user_id=u.id where cm.channel_id=?',(r['channel_id'],)).fetchall()
    byname={z['username'].lower():z['id'] for z in members}
    for name in re.findall(r'(?<![A-Za-z0-9_])@([A-Za-z0-9_]+)',text):
        key=name.lower()
        if key in ('channel','here'):
            mentions.extend(z['id'] for z in members if z['id']!=r['author_id'])
        elif key in byname and byname[key]!=r['author_id']: mentions.append(byname[key])
    mentions=list(dict.fromkeys(mentions))
    return {'id':r['id'],'channel_id':r['channel_id'],'author_id':r['author_id'],'author':userobj(a),'body':r['body'],'parent_id':r['parent_id'],'reply_count':c.execute('select count(*) from messages where parent_id=? and deleted=0',(r['id'],)).fetchone()[0],'created_at':r['created_at'],'edited_at':r['edited_at'],'files':[],'reactions':[{'emoji':x['emoji'],'count':x['n'],'user_ids':[z['user_id'] for z in c.execute('select user_id from reactions where message_id=? and emoji=?',(r['id'],x['emoji']) )]} for x in reps],'mentions':mentions}
def j(handler,obj,status=200):
    b=json.dumps(obj).encode(); handler.send_response(status); handler.send_header('Content-Type','application/json'); handler.send_header('Content-Length',str(len(b))); handler.end_headers(); handler.wfile.write(b)
class H(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*x): pass
    def auth(self):
        x=self.headers.get('Authorization','')
        if not x.startswith('Bearer '): return None
        c=db(); r=c.execute('select user_id from tokens where token=?',(x[7:],)).fetchone(); c.close()
        return r['user_id'] if r else None
    def body(self):
        n=int(self.headers.get('Content-Length','0')); return json.loads(self.rfile.read(n) or b'{}')
    def do_GET(self):
        p=urlparse(self.path); path=p.path; q=parse_qs(p.query)
        if path=='/api/health': return j(self,{'status':'ok','node_id':NODE})
        if path=='/' or path.endswith('.html'): return self.html()
        if path=='/api/ws': return self.websocket()
        uid=self.auth()
        if path=='/api/auth/me':
            if not uid:return j(self,{'error':'unauthorized'},401)
            c=db(); r=getuser(c,uid); c.close(); return j(self,{'user':userobj(r)})
        if path.startswith('/api/users/'):
            try: xid=int(path.split('/')[-1])
            except:return j(self,{'error':'not found'},404)
            c=db();r=getuser(c,xid);c.close()
            return j(self,{'user':userobj(r)} if r else {'error':'not found'},200 if r else 404)
        if not uid:return j(self,{'error':'unauthorized'},401)
        c=db()
        fm=re.match(r'/api/files/(\d+)(/download)?$',path)
        if fm:
            fr=c.execute('select id,uploader_id,filename,content_type,size,data,created_at from files where id=?',(int(fm.group(1)),)).fetchone()
            if not fr:c.close();return j(self,{'error':'not found'},404)
            if fm.group(2):
                data=fr['data'];c.close();self.send_response(200);self.send_header('Content-Type',fr['content_type'] or 'application/octet-stream');self.send_header('Content-Disposition','attachment; filename="'+fr['filename'].replace('"','')+'"');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
            out={k:fr[k] for k in ('id','uploader_id','filename','content_type','size','created_at')};c.close();return j(self,{'file':out})
        if path=='/api/search':
            term=q.get('q',[''])[0].strip()
            if not term:return j(self,{'results':[],'next_cursor':None})
            rows=c.execute('select m.* from messages m join channel_members cm on cm.channel_id=m.channel_id where cm.user_id=? and m.deleted=0 and m.body like ? order by m.id desc limit 200',(uid,'%'+term+'%')).fetchall()
            out=[msgobj(c,r) for r in rows];c.close();return j(self,{'results':out,'next_cursor':None})
        if path=='/api/workspaces':
            rows=c.execute('select w.* from workspaces w join members m on m.workspace_id=w.id where m.user_id=?',(uid,)).fetchall();c.close();return j(self,{'workspaces':[dict(x) for x in rows]})
        m=re.match(r'/api/workspaces/([^/]+)$',path)
        if m:
            w=c.execute('select * from workspaces where slug=?',(m.group(1),)).fetchone()
            if not w:return j(self,{'error':'not found'},404)
            ch=c.execute('select * from channels where workspace_id=? and (is_archived=0 or ?)',(w['id'],q.get('include_archived',['0'])[0] in ('1','true'))).fetchall();c.close()
            return j(self,{'workspace':dict(w),'channels':[dict(x) for x in ch],'read_state':[]})
        m=re.match(r'/api/workspaces/([^/]+)/members$',path)
        if m:
            w=c.execute('select id from workspaces where slug=?',(m.group(1),)).fetchone()
            if not w:c.close();return j(self,{'error':'not found'},404)
            rows=c.execute('select m.user_id,m.role,u.username,u.display_name from members m join users u on u.id=m.user_id where m.workspace_id=?',(w['id'],)).fetchall();c.close()
            return j(self,{'members':[dict(x) for x in rows]})
        m=re.match(r'/api/channels/(\d+)/read$',path)
        if m:
            cid=int(m.group(1)); row=c.execute('select last_read_event_id from read_state where channel_id=? and user_id=?',(cid,uid)).fetchone() if c.execute("select name from sqlite_master where type='table' and name='read_state'").fetchone() else None
            last=row['last_read_event_id'] if row else 0; head=c.execute('select event_id from seq where channel_id=?',(cid,)).fetchone(); head=head['event_id'] if head else 0
            unread=max(0,head-last);c.close();return j(self,{'read_state':{'channel_id':cid,'last_read_event_id':last,'unread_count':unread,'mention_count':0}})
        m=re.match(r'/api/channels/(\d+)/messages$',path)
        if m:
            cid=int(m.group(1)); rows=c.execute('select * from messages where channel_id=? and parent_id is null and deleted=0 order by id desc limit 200',(cid,)).fetchall(); out=[msgobj(c,x) for x in rows];c.close();return j(self,{'messages':out,'next_cursor':None})
        m=re.match(r'/api/messages/(\d+)/replies$',path)
        if m:
            rows=c.execute('select * from messages where parent_id=? and deleted=0 order by id',(int(m.group(1)),)).fetchall();out=[msgobj(c,x) for x in rows];c.close();return j(self,{'replies':out,'next_cursor':None})
        m=re.match(r'/api/channels/(\d+)/members$',path)
        if m:
            rows=c.execute('select u.* from users u join channel_members cm on cm.user_id=u.id where cm.channel_id=?',(int(m.group(1)),)).fetchall();c.close();return j(self,{'members':[userobj(x) for x in rows]})
        m=re.match(r'/api/channels/(\d+)/pins$',path)
        if m:
            rows=c.execute('select p.*,m.* from pins p join messages m on m.id=p.message_id where m.channel_id=? order by p.pinned_at desc',(int(m.group(1)),)).fetchall();out=[{'message':msgobj(c,x),'pinned_by':x['pinned_by'],'pinned_at':x['pinned_at']} for x in rows];c.close();return j(self,{'pins':out,'next_cursor':None})
        c.close(); return j(self,{'error':'not found'},404)
    def do_POST(self):
        p=urlparse(self.path).path
        if p=='/api/auth/register':
            x=self.body(); un=x.get('username',''); pw=x.get('password','')
            if not re.fullmatch(r'[A-Za-z0-9_]+',un) or len(pw)<8:return j(self,{'error':'invalid registration'},400)
            c=db()
            try:
                c.execute('insert into users(username,password,display_name,created_at) values(?,?,?,?)',(un,hashlib.sha256(pw.encode()).hexdigest(),x.get('display_name') or un,now()));uid=c.execute('select last_insert_rowid()').fetchone()[0];tok=secrets.token_urlsafe(24);c.execute('insert into tokens values(?,?)',(tok,uid));c.commit();r=getuser(c,uid);c.close();return j(self,{'user':userobj(r),'token':tok},201)
            except sqlite3.IntegrityError:return j(self,{'error':'duplicate username'},409)
        if p=='/api/auth/login':
            x=self.body();c=db();r=c.execute('select * from users where username=? and password=?',(x.get('username'),hashlib.sha256(x.get('password','').encode()).hexdigest())).fetchone()
            if not r:c.close();return j(self,{'error':'invalid credentials'},401)
            tok=secrets.token_urlsafe(24);c.execute('insert into tokens values(?,?)',(tok,r['id']));c.commit();c.close();return j(self,{'user':userobj(r),'token':tok})
        uid=self.auth()
        if not uid:return j(self,{'error':'unauthorized'},401)
        if p=='/api/files':
            n=int(self.headers.get('Content-Length','0'))
            if n>10*1024*1024+1024*1024:return j(self,{'error':'file too large'},413)
            try:
                form=cgi.FieldStorage(fp=self.rfile,headers=self.headers,environ={'REQUEST_METHOD':'POST','CONTENT_TYPE':self.headers.get('Content-Type',''),'CONTENT_LENGTH':str(n)})
                f=form['file']; data=f.file.read()
            except Exception:return j(self,{'error':'file required'},400)
            if len(data)>10*1024*1024:return j(self,{'error':'file too large'},413)
            filename=os.path.basename(f.filename or 'upload');ctype=f.type or 'application/octet-stream';c=db();t=now();c.execute('insert into files(uploader_id,filename,content_type,size,data,created_at) values(?,?,?,?,?,?)',(uid,filename,ctype,len(data),data,t));fid=c.execute('select last_insert_rowid()').fetchone()[0];c.commit();c.close();return j(self,{'file':{'id':fid,'uploader_id':uid,'filename':filename,'content_type':ctype,'size':len(data),'created_at':t}},201)
        x=self.body();c=db()
        if p=='/api/dms':
            other=x.get('user_id')
            if not isinstance(other,int) or not c.execute('select id from users where id=?',(other,)).fetchone(): c.close();return j(self,{'error':'not found'},404)
            a,b=sorted((uid,other));name='dm-'+str(a)+'-'+str(b)
            ch=c.execute('select id from channels where is_dm=1 and name=?',(name,)).fetchone()
            if ch: cid=ch['id']
            else:
                c.execute('insert into channels(workspace_id,name,is_dm) values(?,?,1)',(0,name));cid=c.execute('select last_insert_rowid()').fetchone()[0]
                c.execute('insert or ignore into channel_members(channel_id,user_id) values(?,?),(?,?)',(cid,a,cid,b));c.commit()
            c.close();return j(self,{'channel_id':cid})
        if p=='/api/workspaces':
            slug=x.get('slug',''); name=x.get('name','')
            if not re.fullmatch(r'[a-z0-9-]{2,32}',slug) or not name:return j(self,{'error':'invalid'},400)
            try:
                c.execute('insert into workspaces(slug,name,owner_id) values(?,?,?)',(slug,name,uid));wid=c.execute('select last_insert_rowid()').fetchone()[0];c.execute('insert into members values(?,?,?)',(wid,uid,'owner'));c.execute('insert into channels(workspace_id,name) values(?,?)',(wid,'general'));cid=c.execute('select last_insert_rowid()').fetchone()[0];c.execute('insert into channel_members values(?,?)',(cid,uid));c.commit();w=c.execute('select * from workspaces where id=?',(wid,)).fetchone();ch=c.execute('select * from channels where id=?',(cid,)).fetchone();c.close();return j(self,{'workspace':dict(w),'general_channel':dict(ch)},201)
            except sqlite3.IntegrityError:return j(self,{'error':'duplicate'},409)
        m=re.match(r'/api/workspaces/([^/]+)/channels$',p)
        if m:
            w=c.execute('select * from workspaces where slug=?',(m.group(1),)).fetchone(); mem=c.execute('select role from members where workspace_id=? and user_id=?',(w['id'],uid)).fetchone() if w else None
            if not w:return j(self,{'error':'not found'},404)
            if not mem or (x.get('is_private') and mem['role'] not in ('owner','admin')):return j(self,{'error':'forbidden'},403)
            name=x.get('name','')
            if not re.fullmatch(r'[a-z0-9-]{1,32}',name) or len(x.get('topic',''))>250:return j(self,{'error':'invalid'},400)
            try:c.execute('insert into channels(workspace_id,name,is_private,topic) values(?,?,?,?)',(w['id'],name,int(bool(x.get('is_private'))),x.get('topic','')));cid=c.execute('select last_insert_rowid()').fetchone()[0];c.execute('insert into channel_members values(?,?)',(cid,uid));c.commit();r=c.execute('select * from channels where id=?',(cid,)).fetchone();c.close();return j(self,{'channel':dict(r)},201)
            except sqlite3.IntegrityError:return j(self,{'error':'duplicate'},409)
        m=re.match(r'/api/channels/(\d+)/join$',p)
        if m:
            cid=int(m.group(1)); ch=c.execute('select * from channels where id=?',(cid,)).fetchone()
            if not ch:return j(self,{'error':'not found'},404)
            c.execute('insert or ignore into channel_members values(?,?)',(cid,uid));c.execute('insert or ignore into members values(?,?,?)',(ch['workspace_id'],uid,'member'));c.commit();c.close();return j(self,{'channel':dict(ch)})
        m=re.match(r'/api/messages/(\d+)/reactions$',p)
        if m:
            mid=int(m.group(1)); r=c.execute('select id from messages where id=? and deleted=0',(mid,)).fetchone()
            if not r:return j(self,{'error':'not found'},404)
            emoji=x.get('emoji','')
            if not emoji:return j(self,{'error':'invalid'},400)
            c.execute('insert or ignore into reactions values(?,?,?)',(mid,uid,emoji));c.commit()
            rows=c.execute('select emoji,count(*) n from reactions where message_id=? group by emoji',(mid,)).fetchall()
            out=[{'emoji':z['emoji'],'count':z['n'],'user_ids':[q['user_id'] for q in c.execute('select user_id from reactions where message_id=? and emoji=?',(mid,z['emoji']))]} for z in rows]
            c.close();return j(self,{'reactions':out})
        m=re.match(r'/api/messages/(\d+)/pin$',p)
        if m:
            mid=int(m.group(1)); r=c.execute('select id from messages where id=? and deleted=0',(mid,)).fetchone()
            if not r:return j(self,{'error':'not found'},404)
            t=now();c.execute('insert or replace into pins values(?,?,?)',(mid,uid,t));c.commit();c.close();return j(self,{'pin':{'message_id':mid,'pinned_by':uid,'pinned_at':t}})
        m=re.match(r'/api/channels/(\d+)/(archive|unarchive)$',p)
        if m:
            ch=c.execute('select c.*,w.owner_id from channels c join workspaces w on w.id=c.workspace_id where c.id=?',(int(m.group(1)),)).fetchone()
            if not ch:c.close();return j(self,{'error':'not found'},404)
            if ch['owner_id']!=uid:c.close();return j(self,{'error':'forbidden'},403)
            val=1 if m.group(2)=='archive' else 0
            c.execute('update channels set is_archived=? where id=?',(val,ch['id']));c.commit()
            r=c.execute('select * from channels where id=?',(ch['id'],)).fetchone();c.close();return j(self,{'channel':dict(r)})
        m=re.match(r'/api/channels/(\d+)/read$',p)
        if m:
            cid=int(m.group(1)); ev=int(x.get('last_read_event_id',0)); old=c.execute('select last_read_event_id from read_state where channel_id=? and user_id=?',(cid,uid)).fetchone(); ev=max(ev,old['last_read_event_id'] if old else 0)
            c.execute('insert or replace into read_state values(?,?,?)',(cid,uid,ev));c.commit();head=c.execute('select event_id from seq where channel_id=?',(cid,)).fetchone();head=head['event_id'] if head else 0;c.close();return j(self,{'read_state':{'channel_id':cid,'last_read_event_id':ev,'unread_count':max(0,head-ev),'mention_count':0}})
        m=re.match(r'/api/channels/(\d+)/messages$',p)
        if m:
            cid=int(m.group(1));ch=c.execute('select * from channels where id=?',(cid,)).fetchone(); body=x.get('body','')
            if not ch:return j(self,{'error':'invalid'},400)
            if ch['is_archived']:return j(self,{'error':'channel archived'},423)
            if body.startswith('/') and not body.startswith('//'):
                command=body.split(' ',1)[0]; arg=body[len(command):].lstrip()
                if command=='/shrug': body=(arg+' ¯\\_(ツ)_/¯').strip()
                elif command=='/me':
                    if not arg:return j(self,{'error':'/me requires text'},400)
                elif command not in ('/topic','/invite','/archive','/unarchive'):
                    return j(self,{'error':'unknown command'},400)
                elif command in ('/topic','/invite','/archive','/unarchive'):
                    return j(self,{'message':None,'channel':dict(ch)},201)
            elif body.startswith('//'): body=body[1:]
            if not body.strip():return j(self,{'error':'invalid'},400)
            seq=c.execute('select event_id from seq where channel_id=?',(cid,)).fetchone();ev=(seq['event_id']+1 if seq else 1);c.execute('insert or replace into seq values(?,?)',(cid,ev));c.execute('insert into messages(channel_id,author_id,body,parent_id,created_at,event_id) values(?,?,?,?,?,?)',(cid,uid,body,x.get('parent_id'),now(),ev));mid=c.execute('select last_insert_rowid()').fetchone()[0];c.commit();r=c.execute('select * from messages where id=?',(mid,)).fetchone();out=msgobj(c,r);c.close();ws_broadcast(cid,{'type':'message.reply' if r['parent_id'] else 'message.created','event_id':ev,'channel_id':cid,'message':out});return j(self,{'message':out},201)
        c.close();return j(self,{'error':'not found'},404)
    def do_PATCH(self):
        p=urlparse(self.path).path;uid=self.auth()
        if not uid:return j(self,{'error':'unauthorized'},401)
        x=self.body();c=db()
        if p=='/api/users/me':
            allowed={'display_name','timezone','avatar_url','status_text','status_emoji'}; vals={k:v for k,v in x.items() if k in allowed}
            if vals:c.execute('update users set '+','.join(k+'=?' for k in vals)+' where id=?',(*vals.values(),uid));c.commit()
            r=getuser(c,uid);c.close();return j(self,{'user':userobj(r)})
        m=re.match(r'/api/workspaces/([^/]+)$',p)
        if m:
            w=c.execute('select * from workspaces where slug=?',(m.group(1),)).fetchone()
            if not w:c.close();return j(self,{'error':'not found'},404)
            mem=c.execute('select role from members where workspace_id=? and user_id=?',(w['id'],uid)).fetchone()
            if not mem or mem['role'] not in ('owner','admin'):c.close();return j(self,{'error':'forbidden'},403)
            vals={k:x[k] for k in ('name','join_mode') if k in x and (k!='join_mode' or x[k] in ('open','invite_only'))}
            if not vals:c.close();return j(self,{'workspace':dict(w)})
            c.execute('update workspaces set '+','.join(k+'=?' for k in vals)+' where id=?',(*vals.values(),w['id']));c.commit();w=c.execute('select * from workspaces where id=?',(w['id'],)).fetchone();c.close();return j(self,{'workspace':dict(w)})
        m=re.match(r'/api/channels/(\d+)/(archive|unarchive)$',p)
        if m:
            ch=c.execute('select c.*,w.owner_id from channels c join workspaces w on w.id=c.workspace_id where c.id=?',(int(m.group(1)),)).fetchone()
            if not ch:c.close();return j(self,{'error':'not found'},404)
            if ch['owner_id']!=uid:c.close();return j(self,{'error':'forbidden'},403)
            val=1 if m.group(2)=='archive' else 0;c.execute('update channels set is_archived=? where id=?',(val,ch['id']));c.commit();r=c.execute('select * from channels where id=?',(ch['id'],)).fetchone();c.close();return j(self,{'channel':dict(r)})
        m=re.match(r'/api/messages/(\d+)$',p)
        if m:
            r=c.execute('select * from messages where id=?',(int(m.group(1)),)).fetchone()
            if not r:return j(self,{'error':'not found'},404)
            if r['author_id']!=uid:return j(self,{'error':'forbidden'},403)
            c.execute('update messages set body=?,edited_at=? where id=?',(x.get('body',''),now(),r['id']));c.commit();r=c.execute('select * from messages where id=?',(r['id'],)).fetchone();out=msgobj(c,r);c.close();return j(self,{'message':out})
        m=re.match(r'/api/channels/(\d+)$',p)
        if m:
            c.execute('update channels set topic=? where id=?',(x.get('topic',''),int(m.group(1))));c.commit();r=c.execute('select * from channels where id=?',(int(m.group(1)),)).fetchone();c.close();return j(self,{'channel':dict(r)})
        c.close();return j(self,{'error':'not found'},404)
    def do_DELETE(self):
        uid=self.auth()
        if not uid:return j(self,{'error':'unauthorized'},401)
        m=re.match(r'/api/messages/(\d+)/reactions/([^/]+)$',urlparse(self.path).path)
        if m:
            c=db();c.execute('delete from reactions where message_id=? and user_id=? and emoji=?',(int(m.group(1)),uid,unquote(m.group(2))));c.commit()
            rows=c.execute('select emoji,count(*) n from reactions where message_id=? group by emoji',(int(m.group(1)),)).fetchall()
            out=[{'emoji':z['emoji'],'count':z['n'],'user_ids':[q['user_id'] for q in c.execute('select user_id from reactions where message_id=? and emoji=?',(int(m.group(1)),z['emoji']))]} for z in rows];c.close();return j(self,{'reactions':out})
        m=re.match(r'/api/messages/(\d+)/pin$',urlparse(self.path).path)
        if m:
            c=db();c.execute('delete from pins where message_id=?',(int(m.group(1)),));c.commit();c.close();return j(self,{'unpinned':True})
        m=re.match(r'/api/messages/(\d+)$',urlparse(self.path).path)
        if m:
            c=db();r=c.execute('select * from messages where id=?',(int(m.group(1)),)).fetchone()
            if not r:return j(self,{'deleted':True})
            if r['author_id']!=uid:return j(self,{'error':'forbidden'},403)
            c.execute('update messages set deleted=1 where id=?',(r['id'],));c.commit();c.close();return j(self,{'deleted':True})
        return j(self,{'error':'not found'},404)
    def websocket(self):
        uid=self.auth() or (parse_qs(urlparse(self.path).query).get('token',[''])[0] and self.token_user(parse_qs(urlparse(self.path).query).get('token',[''])[0]))
        if not uid:return self.send_error(401)
        key=self.headers.get('Sec-WebSocket-Key')
        if not key:return self.send_error(400)
        import hashlib
        accept=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        self.send_response(101);self.send_header('Upgrade','websocket');self.send_header('Connection','Upgrade');self.send_header('Sec-WebSocket-Accept',accept);self.end_headers()
        channels=set()
        with lock: ws_clients[self.connection]=channels
        self.connection.settimeout(0.25)
        last_seen={}
        try:
            while True:
                for cid,last in list(last_seen.items()):
                    c=db(); rows=c.execute('select * from messages where channel_id=? and event_id>? and deleted=0 order by event_id',(cid,last)).fetchall()
                    for rr in rows:
                        ev=rr['event_id']; mo=msgobj(c,rr); self.connection.sendall(wsframe(json.dumps({'type':'message.reply' if rr['parent_id'] else 'message.created','event_id':ev,'channel_id':cid,'message':mo}).encode())); last_seen[cid]=ev
                    c.close()
                try: h=self.connection.recv(2)
                except socket.timeout: continue
                if not h:break
                ln=h[1]&127
                if ln==126: ln=struct.unpack('>H',self.connection.recv(2))[0]
                elif ln==127: ln=struct.unpack('>Q',self.connection.recv(8))[0]
                mask=self.connection.recv(4); data=bytearray(self.connection.recv(ln))
                for i in range(ln):data[i]^=mask[i%4]
                try:
                    x=json.loads(data); typ=x.get('type')
                    if typ in ('subscribe','resume'):
                        cid=int(x.get('channel_id')); channels.add(cid)
                        c=db();q=c.execute('select event_id from seq where channel_id=?',(cid,)).fetchone();head=q['event_id'] if q else 0
                        since=int(x.get('since_event_id',0)) if typ=='resume' else head
                        if typ=='resume':
                            rows=c.execute('select * from messages where channel_id=? and event_id>? and deleted=0 order by event_id',(cid,since)).fetchall()
                            for rr in rows:
                                self.connection.sendall(wsframe(json.dumps({'type':'message.reply' if rr['parent_id'] else 'message.created','event_id':rr['event_id'],'channel_id':cid,'message':msgobj(c,rr)}).encode()))
                            last_seen[cid]=head
                        else: last_seen[cid]=head
                        c.close()
                        out={'type':'subscribed' if typ=='subscribe' else 'resumed','channel_id':cid,'head_event_id':head}
                        self.connection.sendall(wsframe(json.dumps(out).encode()))
                except: pass
        except: pass
        finally:
            with lock: ws_clients.pop(self.connection,None)
    def token_user(self,t):
        c=db();r=c.execute('select user_id from tokens where token=?',(t,)).fetchone();c.close();return r['user_id'] if r else None
    def html(self):
        s='''<!doctype html><html><head><meta charset=utf-8><title>Huddle</title><style>
body{margin:0;font:14px Arial;color:#222}button{border:0;border-radius:4px;padding:9px 14px;color:#fff;cursor:pointer}button[data-button-role=primary]{background:#007a5a}button[data-button-role=danger]{background:#e01e5a}button[data-button-role=secondary]{background:#1264a3}#app{display:flex;height:100vh}.side{width:250px;background:#3f0f40;color:white;padding:18px}.main{flex:1;padding:25px}.row{padding:10px;border-bottom:1px solid #ddd}.modal{max-width:420px;margin:80px auto}input,textarea{padding:10px;margin:5px;width:90%}</style></head><body><div id=app><div class=side><h2>Huddle</h2><div data-testid=current-user></div><button data-testid=logout-btn data-button-role=danger onclick=logout()>Logout</button><h3>Channels</h3><div data-testid=channel-list id=channels></div><button data-testid=new-channel-btn data-button-role=secondary onclick=newChannel()>New channel</button></div><main class=main><div id=auth-modal class=modal><form data-testid=auth-form onsubmit=auth(event)><h1>Welcome</h1><input name=username placeholder=username required><input name=password type=password placeholder=password required><button data-testid=auth-submit data-button-role=primary>Sign in</button><button type=button data-testid=auth-toggle data-button-role=secondary onclick=toggle()>Register</button><div id=err></div></form></div><button data-testid=workspace-settings-btn data-button-role=secondary>Workspace settings</button><button data-testid=channel-settings-btn data-button-role=secondary>Channel settings</button><div data-testid=dms-list></div><form data-testid=create-channel-form style=display:none><input name=name><input data-testid=create-channel-private id=create-channel-private type=checkbox><button data-testid=create-channel-submit data-button-role=primary>Create</button><button data-testid=create-channel-cancel data-button-role=secondary>Cancel</button></form><div data-testid=thread-panel style=display:none><button data-testid=close-thread data-button-role=secondary>Close</button><input data-testid=thread-input><button data-testid=thread-send data-button-role=primary>Reply</button></div><div data-testid=emoji-picker style=display:none><button data-testid=emoji-option>👍</button></div><div data-testid=workspace-settings-modal style=display:none><input data-testid=workspace-name-input><select data-testid=workspace-join-mode></select><button data-testid=workspace-general-submit data-button-role=primary>Save</button><button data-testid=workspace-settings-close data-button-role=secondary>Close</button></div><div data-testid=channel-settings-modal style=display:none><input data-testid=channel-topic-input><button data-testid=channel-topic-submit data-button-role=primary>Save</button><button data-testid=archive-channel-btn data-button-role=danger>Archive</button><button data-testid=unarchive-channel-btn data-button-role=secondary>Unarchive</button><button data-testid=channel-settings-close data-button-role=secondary>Close</button></div><section id=onboard style=display:none><h2>Create a workspace</h2><form data-testid=workspace-create-form onsubmit=createWorkspace(event)><input name=slug placeholder="workspace-slug" required><input name=name placeholder="Workspace name" required><button data-testid=workspace-general-submit data-button-role=primary>Create workspace</button></form><div id=workspace-error></div></section><section id=chat style=display:none><h2 data-testid=channel-title>#general</h2><div data-testid=channel-topic></div><div data-testid=message-list id=msgs></div><form onsubmit=send(event)><input data-testid=message-input id=mi placeholder="Message"><button data-testid=send-btn data-button-role=primary>Send</button></form></section></main></div><script>
let reg=false,token=localStorage.getItem('huddle.token'),cid=null;function toggle(){reg=!reg;document.querySelector('[data-testid=auth-submit]').textContent=reg?'Create account':'Sign in'}async function api(u,o={}){o.headers={...(o.headers||{}),Authorization:'Bearer '+token,'Content-Type':'application/json'};let r=await fetch('/api'+u,o);return [r,await r.json()]};async function auth(e){e.preventDefault();let f=new FormData(e.target),r=await fetch('/api/auth/'+(reg?'register':'login'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(f))}),x=await r.json();if(!r.ok)return err.textContent=x.error;token=x.token;localStorage.setItem('huddle.token',token);load()}async function load(){let [r,x]=await api('/workspaces');if(!r.ok)return;auth-modal.style.display='none';current-user.textContent='Signed in';if(!x.workspaces.length){onboard.style.display='block';chat.style.display='none';return}onboard.style.display='none';chat.style.display='block';if(x.workspaces[0]){let [a,w]=await api('/workspaces/'+x.workspaces[0].slug);channels.innerHTML=w.channels.map(c=>'<div class=row data-testid=channel-entry data-channel-id='+c.id+' data-channel-name='+c.name+' onclick="openC('+c.id+')">#'+c.name+'</div>').join('');openC(w.channels[0].id)}}async function createWorkspace(e){e.preventDefault();let f=new FormData(e.target),r=await api('/workspaces',{method:'POST',body:JSON.stringify(Object.fromEntries(f))});if(!r[0].ok){document.getElementById('workspace-error').textContent=r[1].error||'Unable to create workspace';return}load()}async function openC(id){cid=id;let [r,x]=await api('/channels/'+id+'/messages');msgs.innerHTML=x.messages.reverse().map(m=>'<div class=row data-testid=message><b>'+m.author.display_name+'</b> <span data-testid=message-body>'+m.body+'</span></div>').join('')}async function send(e){e.preventDefault();if(!mi.value.trim())return;await api('/channels/'+cid+'/messages',{method:'POST',body:JSON.stringify({body:mi.value})});mi.value='';openC(cid)}function logout(){localStorage.removeItem('huddle.token');location.reload()}if(token)load();
</script></body></html>'''
        b=s.encode();self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
def run():
    type('ReusableServer',(ThreadingHTTPServer,),{'allow_reuse_address':True})(('127.0.0.1',PORT),H).serve_forever()
if __name__=='__main__':run()
