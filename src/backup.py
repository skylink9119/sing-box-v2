"""Private managed backups: integrity, preflight, bounded archive import and opt-in pruning."""
import hashlib,json,os,pathlib,shutil,subprocess,sys,tarfile,tempfile,time
base,backups,conf,binary,action,*args=sys.argv[1:];base=pathlib.Path(base);backups=pathlib.Path(backups);conf=pathlib.Path(conf)
OWNER='SKYBYTE backup v1'
def contained(value):
 p=pathlib.Path(value)
 if p.is_symlink() or p.resolve().parent!=backups.resolve() or not p.is_dir():raise ValueError('Not a managed backup directory')
 return p

def files(root):
 result={}
 for p in root.rglob('*'):
  if p.is_symlink():raise ValueError('Backup contains symlinks')
  if p.is_file() and p.name not in ('backup-manifest.json','.incomplete'):result[str(p.relative_to(root))]=p
 return result

def file_digest(path):
 digest=hashlib.sha256()
 with open(path,'rb') as source:
  for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
 return digest.hexdigest()

def replace_from_file(path,source,mode=0o600):
 if path.is_symlink() or path.parent.is_symlink() or source.is_symlink():raise ValueError('Restore file symlink')
 fd,tmp=tempfile.mkstemp(dir=path.parent)
 try:
  with os.fdopen(fd,'wb') as target,open(source,'rb') as original:
   shutil.copyfileobj(original,target,1024*1024);target.flush();os.fsync(target.fileno())
  os.chmod(tmp,mode);os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)

def manifest(root,replace=False):
 contents=files(root)
 if len(contents)>10000:raise ValueError('Too many backup files')
 d={'owner':OWNER,'schema':1,'created_at':int(time.time()),'files':{n:file_digest(p) for n,p in contents.items()}}
 target=root/'backup-manifest.json'
 if target.is_symlink():raise ValueError('Manifest symlink')
 if target.exists():
  old=json.loads(target.read_text())
  if not replace or old.get('owner')!=OWNER or old.get('schema')!=1:raise ValueError('Manifest exists or ownership mismatch')
  d['created_at']=old['created_at']
 fd,tmp=tempfile.mkstemp(dir=root)
 with os.fdopen(fd,'w') as f:json.dump(d,f,indent=2);f.flush();os.fsync(f.fileno())
 os.replace(tmp,target)

def verify(root,required=False):
 if (root/'.incomplete').exists() or (root/'.incomplete').is_symlink():raise ValueError('Incomplete backup; refusing restore')
 contents=files(root);p=root/'backup-manifest.json'
 if not p.exists():
  if required:raise ValueError('Archive has no integrity manifest')
  print('Legacy backup: no digest manifest; configuration checks still required',file=sys.stderr);return
 d=json.loads(p.read_text())
 if d.get('owner')!=OWNER or d.get('schema')!=1 or set(d['files'])!=set(contents):raise ValueError('Backup manifest mismatch')
 for n,f in contents.items():
  if file_digest(f)!=d['files'][n]:raise ValueError('Backup integrity check failed')

def check(root):
 verify(root)
 for name in ('config/config.json','state.json','sing-box.bin'):
  if not (root/name).is_file():raise ValueError('Incomplete backup')
 json.loads((root/'state.json').read_text())
 paths=[root/'config/config.json']
 paths+=list((root/'users').glob('*/server.json'))
 paths += [root/n for n in ('argo-server.json','warp-gateway.json') if (root/n).exists()]
 for path in paths:
  cfg=json.loads(path.read_text())
  for i in cfg.get('inbounds',[]):
   tls=i.get('tls',{})
   for field,name in (('certificate_path','hy2-backup.crt'),('key_path','hy2-backup.key')):
    if field in tls:
     candidate=root/'config'/name if path==paths[0] else path.parent/('certificate.crt' if field=='certificate_path' else 'private.key')
     if not candidate.is_file():raise ValueError('Backed-up certificate/key missing')
     tls[field]=str(candidate)
  fd,tmp=tempfile.mkstemp(dir=base)
  try:
   with os.fdopen(fd,'w') as f:json.dump(cfg,f)
   r=subprocess.run([binary,'check','-c',tmp],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
   if r.returncode:raise ValueError('Backed-up configuration does not validate')
  finally:os.unlink(tmp)

def managed():
 result=[]
 for p in backups.iterdir():
  if p.is_symlink() or not p.is_dir():continue
  try:
   d=json.loads((p/'backup-manifest.json').read_text())
   if d.get('owner')==OWNER and d.get('schema')==1:result.append((d['created_at'],p))
  except (OSError,ValueError,KeyError):continue
 return [p for _,p in sorted(result,key=lambda t:(t[0],t[1].name),reverse=True)]

def replace_file(path,data,mode=0o600):
 if path.is_symlink() or path.parent.is_symlink():raise ValueError('Restore target symlink')
 fd,tmp=tempfile.mkstemp(dir=path.parent)
 try:
  with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
  os.chmod(tmp,mode);os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)

def restore_targets():
 return [(conf,'config/config.json',0o600),(base/'state.json','state.json',0o600),
         (pathlib.Path(binary),'sing-box.bin',0o755),
         (conf.parent/'hy2-backup.crt','config/hy2-backup.crt',0o600),
         (conf.parent/'hy2-backup.key','config/hy2-backup.key',0o600)]

def restore_stage(value):
 p=pathlib.Path(value)
 if p.is_symlink() or p.parent!=base or not p.name.startswith('restore.') or not p.is_dir():raise ValueError('Invalid restore transaction')
 return p

def restore_plan(root,value):
 stage=restore_stage(value);plan=[]
 for dest,name,mode in restore_targets():
  source=root/name
  if not source.exists():continue
  if source.is_symlink() or not source.is_file() or dest.is_symlink() or dest.parent.is_symlink() or dest.exists() and not dest.is_file():raise ValueError('Unsafe restore file')
  n=len(plan);candidate=stage/('new-'+str(n));old=stage/('old-'+str(n))
  replace_from_file(candidate,source)
  previous_mode=None
  if dest.exists():previous_mode=dest.stat().st_mode&0o777;replace_from_file(old,dest)
  plan.append({'target':str(dest),'mode':mode,'previous_mode':previous_mode,'index':n})
 replace_file(stage/'transaction.json',json.dumps(plan).encode())

def restore_files(value,rollback=False):
 stage=restore_stage(value);plan=json.loads((stage/'transaction.json').read_text());allowed={str(p) for p,_,_ in restore_targets()}
 for n,item in enumerate(plan):
  dest=pathlib.Path(item['target']);mode=item['previous_mode'] if rollback else item['mode']
  if str(dest) not in allowed or item['index']!=n or dest.is_symlink() or dest.parent.is_symlink():raise ValueError('Invalid restore journal')
  if mode is None:
   if dest.exists():
    if file_digest(dest)!=file_digest(stage/('new-'+str(n))):raise ValueError('Restore target changed; retained')
    dest.unlink()
  else:
   if type(mode) is not int or not 0<=mode<=0o777:raise ValueError('Invalid restore mode')
   source=stage/(('old-' if rollback else 'new-')+str(n))
   if source.is_symlink() or not source.is_file():raise ValueError('Invalid restore source')
   replace_from_file(dest,source,mode)

if action=='manifest':manifest(pathlib.Path(args[0]))
elif action=='reseal':manifest(contained(args[0]),True)
elif action=='preflight':check(contained(args[0]));print('Backup integrity/configuration preflight passed')
elif action=='restore_plan':restore_plan(contained(args[0]),args[1])
elif action=='restore_apply':restore_files(args[0])
elif action=='restore_rollback':restore_files(args[0],True)
elif action=='list':
 for p in managed():print(p.name+' | '+str(sum(f.stat().st_size for f in files(p).values()))+' bytes | '+str(p))
elif action=='archive':
 root=contained(args[0]);verify(root,True)
 with tarfile.open(args[1],'w:gz') as tar:
  for n,p in files(root).items():tar.add(p,arcname=n,recursive=False)
  tar.add(root/'backup-manifest.json',arcname='backup-manifest.json',recursive=False)
elif action=='import':
 destination=pathlib.Path(tempfile.mkdtemp(prefix='import-',dir=backups));success=False
 try:
  with tarfile.open(args[0],'r:gz') as tar:
   members=tar.getmembers()
   if len(members)>10000 or sum(m.size for m in members)>1024**3:raise ValueError('Archive exceeds limits')
   seen=set()
   for m in members:
    p=pathlib.PurePosixPath(m.name)
    if p.is_absolute() or '..' in p.parts or '\\' in m.name or m.name in seen or not m.isfile():raise ValueError('Unsafe archive entry')
    seen.add(m.name);target=destination/pathlib.Path(*p.parts);target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tar.extractfile(m) as source,open(target,'xb') as out:shutil.copyfileobj(source,out)
    target.chmod(0o700 if m.name=='sing-box.bin' else 0o600)
  verify(destination,True);check(destination);success=True;print(destination)
 finally:
  if not success:shutil.rmtree(destination)
elif action=='prune':
 keep=int(args[0])
 if not 1<=keep<=1000:raise ValueError('Retention requires 1-1000')
 for p in managed()[keep:]:
  print(p)
  if args[1]=='apply':verify(p,True);shutil.rmtree(p)
else:raise ValueError('Unknown backup operation')
