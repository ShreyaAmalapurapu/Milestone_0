import socket, threading, sqlite3, os, re
DB='/app/huddle.db'; clients=[]; lk=threading.RLock()
def db():
 c=sqlite3.connect(DB,timeout=10);c.row_factory=sqlite3.Row;return c
def send(s,x):
 try:s.sendall((x+'\r\n').encode())
 except:pass
def user(token):
 c=db();r=c.execute('select user_id from tokens where token=?',(token,)).fetchone();c.close();return r['user_id'] if r else None
def handle(sock,addr):
 token=None; uid=None; nick=None; registered=False; joined=[]
 with lk: clients.append((sock,lambda: joined,nick))
 try:
  f=sock.makefile('rb')
  for raw in f:
   line=raw.decode(errors='replace').strip('\r\n'); parts=line.split(' ',2)
   if not parts:continue
   cmd=parts[0].upper(); arg=parts[1] if len(parts)>1 else ''; tail=parts[2][1:] if len(parts)>2 and parts[2].startswith(':') else (parts[2] if len(parts)>2 else '')
   if cmd=='PASS':
    token=arg;uid=user(token)
    if not uid:send(sock,':huddle 464 * :Password incorrect')
   elif cmd=='NICK':
    n=arg
    with lk: collision=any(x[2]==n and x[0] is not sock for x in clients)
    if collision:send(sock,':huddle 433 * '+n+' :Nickname is already in use')
    else:nick=n
   elif cmd=='USER' and nick and uid and not registered:
    registered=True
    for code,text in [('001','Welcome to Huddle'),('002','Your host is huddle'),('003','This server was created today'),('004','huddle huddle 1 ao'),('005','CHANTYPES=# PREFIX=(oh)@+ :are supported'),('422','MOTD File is missing')]:send(sock,':huddle '+code+' '+nick+' :'+text)
   elif cmd=='PING':send(sock,':huddle PONG huddle :'+tail)
   elif cmd=='PONG':pass
   elif cmd=='JOIN' and registered:
    chan=arg
    m=re.fullmatch(r'#([^/]+)/([^/]+)',chan)
    if not m:send(sock,':huddle 403 '+nick+' '+chan+' :No such channel');continue
    c=db();r=c.execute('select c.*,w.slug from channels c join workspaces w on w.id=c.workspace_id where w.slug=? and c.name=?',(m.group(1),m.group(2))).fetchone()
    if not r:c.close();send(sock,':huddle 403 '+nick+' '+chan+' :No such channel');continue
    joined.append((r['id'],chan)); names=[]
    for row in c.execute('select u.username from users u join channel_members cm on cm.user_id=u.id where cm.channel_id=?',(r['id'],)):names.append(row['username'])
    c.close();send(sock,':'+nick+'!'+str(uid)+'@localhost JOIN '+chan);send(sock,':huddle 353 '+nick+' = '+chan+' :'+(' '.join(names)));send(sock,':huddle 366 '+nick+' '+chan+' :End of /NAMES list.')
   elif cmd=='NAMES' and registered:
    chan=arg;send(sock,':huddle 353 '+nick+' = '+chan+' :'+nick);send(sock,':huddle 366 '+nick+' '+chan+' :End of /NAMES list.')
   elif cmd=='PRIVMSG' and registered:
    chan=arg; body=tail; match=next((x for x in joined if x[1]==chan),None)
    if not match:send(sock,':huddle 442 '+nick+' '+chan+' :You are not on that channel');continue
    cid=match[0];c=db();q=c.execute('select event_id from seq where channel_id=?',(cid,)).fetchone();ev=(q['event_id']+1 if q else 1);c.execute('insert or replace into seq values(?,?)',(cid,ev));c.execute('insert into messages(channel_id,author_id,body,created_at,event_id) values(?,?,?,?,?)',(cid,uid,body,__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),ev));c.commit();c.close()
    with lk:
     for so,gj,n in clients:
      if so is not sock and any(x[1]==chan for x in gj()):send(so,':'+str(nick)+'!'+str(uid)+'@localhost PRIVMSG '+chan+' :'+body)
   elif cmd=='QUIT':break
   elif cmd in ('WHO','LIST','TOPIC','MODE'):pass
   elif registered:send(sock,':huddle 421 '+nick+' '+cmd+' :Unknown command')
 finally:
  with lk: clients[:]=[x for x in clients if x[0] is not sock]
  try:sock.close()
  except:pass
def main():
 s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('0.0.0.0',6667));s.listen(50)
 while True:
  so,ad=s.accept();threading.Thread(target=handle,args=(so,ad),daemon=True).start()
if __name__=='__main__':main()
