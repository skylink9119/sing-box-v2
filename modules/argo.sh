# modules/argo.sh — build-time module; assembled by scripts/build.py.
argo_state(){
 python3 - "$BASE/argo-state.json" "$1" <<'PY'
import json,sys
print(json.load(open(sys.argv[1])).get(sys.argv[2],''))
PY
}
argo_guard(){
 local unit marker expected
 for unit in skybyte-argo-node.service skybyte-argo-tunnel.service; do
  marker="Description=SKYBYTE managed $unit"
  if [[ $unit == skybyte-argo-node.service ]]; then expected="ExecStart=$BIN run -c $BASE/argo-server.json"; else expected="ExecStart=/bin/bash $MANAGER_BIN --argo-run"; fi
  if [[ -e $SYSTEMD_DIR/$unit || -L $SYSTEMD_DIR/$unit ]]; then
   if [[ ! -f $SYSTEMD_DIR/$unit || -L $SYSTEMD_DIR/$unit ]] || ! grep -Fxq "$marker" "$SYSTEMD_DIR/$unit" || ! grep -Fxq "$expected" "$SYSTEMD_DIR/$unit"; then err "$(L 'Argo 服务归属异常，拒绝修改' 'Argo unit ownership mismatch; refusing changes')"; return 1; fi
  fi
 done
 for unit in argo-state.json argo-server.json argo-empty.yml argo.token cloudflared; do
  [[ ! -L $BASE/$unit ]] || { err "$(L 'Argo 文件是符号链接，拒绝修改' 'Argo file is a symlink; refusing changes')"; return 1; }
 done
}
download_cloudflared(){
 local target=$1 tmp arch tag asset digest
 arch=$(rescue_engine arch "$(uname -m)" cloudflared) || return 1
 if [[ -n ${SKYBYTE_ASSET_DIR:-} ]];then rescue_engine asset "$SKYBYTE_ASSET_DIR" cloudflared '' "$(uname -m)" "$target";return $?;fi
 tmp=$(mktemp -d) || return 1
 curl -q -fsSL --connect-timeout 10 --proto '=https' --proto-redir '=https' --retry 2 --max-time 30 https://api.github.com/repos/cloudflare/cloudflared/releases/latest -o "$tmp/release.json" || { rm -rf "$tmp"; return 1; }
 tag=$(python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); assert not r["prerelease"] and not r["draft"]; print(r["tag_name"])' "$tmp/release.json") || { rm -rf "$tmp"; return 1; }
 [[ $tag =~ ^[0-9]{4}\.[0-9]+\.[0-9]+$ ]] || { rm -rf "$tmp"; return 1; }
 asset="cloudflared-linux-$arch"
 digest=$(python3 - "$tmp/release.json" "$asset" <<'PY'
import json,sys
asset=next(a for a in json.load(open(sys.argv[1]))['assets'] if a['name']==sys.argv[2])
digest=asset.get('digest') or ''; assert digest.startswith('sha256:')
print(digest.split(':',1)[1])
PY
 ) || { rm -rf "$tmp"; return 1; }
 if [[ ! $digest =~ ^[a-fA-F0-9]{64}$ ]] ||
    ! curl -q -fsSL --connect-timeout 10 --proto '=https' --proto-redir '=https' --retry 2 --max-time 180 "https://github.com/cloudflare/cloudflared/releases/download/$tag/$asset" -o "$tmp/binary" ||
    ! printf '%s  %s\n' "$digest" "$tmp/binary" | sha256sum -c - >/dev/null; then rm -rf "$tmp"; return 1; fi
 command install -m 755 "$tmp/binary" "$target"
 local rc=$?; rm -rf "$tmp"; return "$rc"
}
argo_validate_domain(){
 python3 - "$1" <<'PY'
import re,sys
name=sys.argv[1]
assert len(name)<=253 and '.' in name and not re.fullmatch(r'[0-9.]+',name)
assert all(re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?',p) for p in name.split('.'))
PY
}
argo_write_config(){
 python3 - "$1" "$2" "$3" "$4" "$5" <<'PY'
import json,pathlib,secrets,sys,uuid
root,mode,domain,port,name=sys.argv[1:];root=pathlib.Path(root)
assert mode in ('quick','named') and 1024<=int(port)<=65535
uid=str(uuid.uuid4());path='/'+secrets.token_hex(16)
config={'log':{'level':'warn'},'inbounds':[{'type':'vless','tag':'argo-ws','listen':'127.0.0.1','listen_port':int(port),'users':[{'uuid':uid}], 'transport':{'type':'ws','path':path}}], 'outbounds':[{'type':'direct','tag':'direct'}], 'route':{'final':'direct'}}
state={'mode':mode,'domain':domain,'port':int(port),'path':path,'node_name':name,'connected':False}
(root/'argo-server.json').write_text(json.dumps(config,indent=2))
(root/'argo-state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2))
(root/'argo-empty.yml').write_text('{}\n')
PY
}
argo_setup_units(){
 argo_guard || return 1
 if [[ -L $MANAGER_BIN ]]; then err "$(L '管理脚本不能是符号链接' 'Manager executable cannot be a symlink')"; return 1; fi
 if [[ -e $MANAGER_BIN ]] && ! grep -q '^# SKYBYTE Manager V2.1 community manager;' "$MANAGER_BIN"; then err "$(L '管理脚本路径被其他程序占用' 'Manager executable path is occupied')"; return 1; fi
 if [[ ! $SCRIPT_PATH -ef $MANAGER_BIN ]]; then command install -m 700 "$SCRIPT_PATH" "$MANAGER_BIN" || return 1; fi
 cat >"$SYSTEMD_DIR/skybyte-argo-node.service" <<EOF
[Unit]
Description=SKYBYTE managed skybyte-argo-node.service
After=network-online.target
Wants=network-online.target
[Service]
ExecStart=$BIN run -c $BASE/argo-server.json
Restart=on-failure
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF
 cat >"$SYSTEMD_DIR/skybyte-argo-tunnel.service" <<EOF
[Unit]
Description=SKYBYTE managed skybyte-argo-tunnel.service
After=network-online.target skybyte-argo-node.service
Requires=skybyte-argo-node.service
[Service]
ExecStart=/bin/bash $MANAGER_BIN --argo-run
Restart=on-failure
RestartSec=5
KillMode=control-group
TimeoutStopSec=15
[Install]
WantedBy=multi-user.target
EOF
 systemctl daemon-reload
}
argo_wait(){
 local attempt
 for ((attempt=0; attempt<30; attempt++)); do
  [[ $(argo_state connected) == True ]] && return 0
  systemctl is-active --quiet skybyte-argo-tunnel.service || return 1
  sleep 1
 done
 return 1
}
argo_install(){
 need_root
 if [[ ! -e $CONF && ! -e $META && ! -L $CONF && ! -L $META ]];then
  local bootstrap_rc=0;rescue_bootstrap_core || bootstrap_rc=$?
  [[ $bootstrap_rc != 2 ]] || return 0
  [[ $bootstrap_rc == 0 ]] || return "$bootstrap_rc"
 fi
 check_owned || return 1; argo_guard || return 1
 local mode=$1 port name domain='' token='' stage snap file
 [[ $mode == quick || $mode == named ]] || return 1
 for file in argo-state.json argo-server.json argo.token argo-empty.yml cloudflared; do
  [[ ! -e $BASE/$file ]] || { err "$(L '已有 Argo 文件；请先用 Argo 管理入口卸载' 'Argo files exist; remove via Argo controls first')"; return 1; }
 done
 for file in skybyte-argo-node.service skybyte-argo-tunnel.service; do
  [[ ! -e $SYSTEMD_DIR/$file ]] || return 1
  if systemctl list-unit-files "$file" --no-legend 2>/dev/null | grep -q "$file"; then err "$(L '已有同名 Argo 服务，拒绝覆盖' 'An Argo service with this name exists; refusing overwrite')"; return 1; fi
 done
 warn "$(L '新增 VLESS+WS 隧道节点；Cloudflare 终止公网 TLS，可处理隧道流量。临时隧道仅供测试，重启会换地址。' 'Adds a VLESS+WS node. Cloudflare terminates public TLS and can process tunnel traffic. Quick tunnels are for testing; restarts change the hostname.')"
 confirm "$(L '安装所选 Argo 模式？' 'Install selected Argo mode?')" || return 0
 prompt_read "$(L '本机 WS 端口 [8080]：' 'Local WS port [8080]: ')" port || return 1
 port=${port:-8080}; valid_port "$port" && (( 10#$port>=1024 )) || return 1; port=$((10#$port))
 haproxy_engine check_port "$port" || return 1
 if ss -H -ltn "( sport = :$port )" | grep -q .; then err "$(L '端口已占用' 'Port is occupied')"; return 1; fi
 name=$(choose_node_name) || return 1
 if [[ $mode == named ]]; then
  prompt_read "$(L 'Cloudflare 固定公开域名：' 'Cloudflare published hostname: ')" domain || return 1
  argo_validate_domain "$domain" || { err "$(L '域名格式无效' 'Invalid hostname')"; return 1; }
  say "请在 Cloudflare 控制台将该域名的 HTTP 服务指向 http://127.0.0.1:${port}；需要支持 WebSocket，不能要求交互式 Access 登录。" "In Cloudflare, route this hostname to HTTP http://127.0.0.1:$port with WebSocket support; interactive Access login is incompatible."
  prompt_read "$(L 'Tunnel Token（隐藏输入）：' 'Tunnel Token (hidden input): ')" token secret || return 1; printf '\n'
  if [[ ! $token =~ ^[a-zA-Z0-9+/=_-]+$ ]] || (( ${#token}<20 || ${#token}>4096 )); then err "$(L 'Token 格式无效' 'Invalid token format')"; return 1; fi
 fi
 snap=$(backup) || return 1
 stage=$(mktemp -d "$BASE/.argo-install.XXXXXX") || return 1
 if ! argo_write_config "$stage" "$mode" "$domain" "$port" "$name" || ! "$BIN" check -c "$stage/argo-server.json" || ! download_cloudflared "$stage/cloudflared"; then rm -rf "$stage"; return 1; fi
 rescue_engine options "$stage/argo-state.json" "$(rescue_engine family)" auto || { rm -rf "$stage";return 1; }
 if [[ $mode == named ]]; then printf '%s' "$token" >"$stage/argo.token"; token=''; fi
 chmod 600 "$stage"/argo-*; chmod 755 "$stage/cloudflared"
 for file in argo-state.json argo-server.json argo-empty.yml cloudflared argo.token; do
  if [[ -f $stage/$file ]]; then mv "$stage/$file" "$BASE/$file" || { rm -rf "$stage"; return 1; }; fi
 done
 rmdir "$stage"
 if ! warp_reconcile || ! argo_setup_units || ! systemctl enable --now skybyte-argo-node.service || ! systemctl enable --now skybyte-argo-tunnel.service; then
  err "$(L 'Argo 启动失败；保留配置供诊断，原节点配置未改变' 'Argo startup failed; config retained for diagnosis. Existing node config was not changed')"; return 1
 fi
 if ! argo_wait; then warn "$(L '隧道尚未注册连接；请使用 Argo 状态检查 Token、路由或出站网络。' 'Tunnel not registered yet; use Argo status to check token, route or outbound connectivity.')"; return 1; fi
 ok "$(L 'Argo 已启动；安装前备份：' 'Argo started; pre-install backup: ')$snap"
 exports
}
argo_run(){
 # Worker mode never takes the interactive manager lock. Only state/exports use their own locks.
 python3 - "$BASE" "$MANAGER_BIN" <<'PY'
import fcntl,json,os,pathlib,re,signal,subprocess,sys,tempfile
base=pathlib.Path(sys.argv[1]);runner=sys.argv[2];state_path=base/'argo-state.json'
def update(**fields):
 with open(base/'argo-state.lock','a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  if not state_path.exists():return
  state=json.loads(state_path.read_text());state.update(fields)
  with tempfile.NamedTemporaryFile(mode='w',dir=base,delete=False) as tmp:
   json.dump(state,tmp,ensure_ascii=False,indent=2);name=tmp.name
  os.chmod(name,0o600);os.replace(name,state_path)
def sync():
 try:subprocess.run(['/bin/bash',runner,'--argo-export'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20,check=False)
 except (OSError,subprocess.TimeoutExpired):pass
state=json.loads(state_path.read_text());mode=state['mode']
assert mode in ('quick','named')
edge=state.get('edge_ip_version','auto');transport=state.get('transport','auto')
assert edge in ('auto','4','6') and transport in ('auto','quic','http2')
common=[str(base/'cloudflared'),'tunnel','--config',str(base/'argo-empty.yml'),'--no-autoupdate','--grace-period','5s','--edge-ip-version',edge,'--protocol',transport]
if mode=='quick':
 update(domain='',connected=False,last_error='');command=common+['--url',f"http://127.0.0.1:{state['port']}"]
else:
 assert (base/'argo.token').is_file();update(connected=False,last_error='')
 command=common+['run','--token-file',str(base/'argo.token')]
sync()
# Do not inherit incidental shell tokens/configuration from the interactive environment.
env={k:v for k,v in os.environ.items() if not k.startswith(('TUNNEL_','CF_'))}
proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env=env)
stopping=False;hostname=state.get('domain','') if mode=='named' else '';registered=False
pattern=re.compile(r'https://([a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com)(?![a-z0-9.-])')
def stop(*_):
 global stopping
 stopping=True;proc.terminate()
 try:proc.wait(timeout=7)
 except subprocess.TimeoutExpired:proc.kill()
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
try:
 for line in proc.stdout:
  match=pattern.search(line)
  if mode=='quick' and match:hostname=match.group(1)
  lower=line.lower()
  if 'invalid tunnel token' in lower or 'unauthorized' in lower: update(last_error='token_or_account')
  elif 'timeout' in lower or 'failed to dial' in lower or 'network is unreachable' in lower: update(last_error='outbound_network')
  elif 'certificate' in lower and ('error' in lower or 'failed' in lower): update(last_error='tls')
  if 'Registered tunnel connection' in line:registered=True
  if registered and hostname:
   update(domain=hostname,connected=True,last_error='');sync();registered=False
 # Suppress raw cloudflared output: it can include operational/account information.
finally:
 if proc.poll() is None:stop()
 update(connected=False,**({'domain':''} if mode=='quick' else {}));sync()
rc=proc.wait();sys.exit(0 if stopping else rc if rc>0 else 1)
PY
}
argo_status(){
 [[ -f $BASE/argo-state.json ]] || { say '尚未配置 Argo 隧道。' 'Argo is not configured.'; return 0; }
 local mode domain port connected last_error edge transport snapshot
 snapshot=$(python3 - "$BASE/argo-state.json" <<'PY_ARGO_SNAPSHOT'
import json,sys
s=json.load(open(sys.argv[1]))
for key in ('mode','domain','port','connected','last_error','edge_ip_version','transport'):print(s.get(key,''))
PY_ARGO_SNAPSHOT
 ) || return 1
 { IFS= read -r mode;IFS= read -r domain;IFS= read -r port;IFS= read -r connected;IFS= read -r last_error;IFS= read -r edge;IFS= read -r transport; } <<< "$snapshot"
 say "最近错误类别：$last_error" "Last error category: $last_error"
 say "模式：${mode}；公开域名：${domain:-尚未分配}；本机端口：${port}；已注册：$connected" "Mode: $mode; hostname: ${domain:-not assigned}; local port: $port; registered: $connected"
 say "连接地址族：${edge}；隧道传输：$transport" "Edge IP version: $edge; transport: $transport"
 if systemctl is-active --quiet skybyte-argo-node.service; then ok "$(L 'Argo WS 服务运行中' 'Argo WS origin active')"; else err "$(L 'Argo WS 服务未运行' 'Argo WS origin inactive')"; fi
 if systemctl is-active --quiet skybyte-argo-tunnel.service; then ok "$(L 'Argo 隧道服务运行中' 'Argo tunnel worker active')"; else err "$(L 'Argo 隧道服务未运行' 'Argo tunnel worker inactive')"; fi
 warn "$(L '服务运行不代表客户端可达；固定模式还需核对 Cloudflare 公开路由和客户端 SNI/WS 路径。' 'Active services do not prove client connectivity; verify published routes and client SNI/WS paths.')"
}
argo_clear_ready(){
 [[ -f $BASE/argo-state.json ]] || return 0
 python3 - "$BASE" <<'PY'
import fcntl,json,os,pathlib,tempfile,sys
base=pathlib.Path(sys.argv[1]);p=base/'argo-state.json'
with open(base/'argo-state.lock','a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX);s=json.loads(p.read_text());s['connected']=False
 if s['mode']=='quick':s['domain']=''
 with tempfile.NamedTemporaryFile(mode='w',dir=base,delete=False) as f:json.dump(s,f,indent=2);tmp=f.name
 os.chmod(tmp,0o600);os.replace(tmp,p)
PY
}
argo_stop(){
 argo_guard || return 1
 if [[ -f $SYSTEMD_DIR/skybyte-argo-tunnel.service ]]; then systemctl stop skybyte-argo-tunnel.service || return 1; fi
 if [[ -f $SYSTEMD_DIR/skybyte-argo-node.service ]]; then systemctl stop skybyte-argo-node.service || return 1; fi
 argo_clear_ready
}
argo_start(){
 [[ -f $BASE/argo-state.json ]] || return 1
 argo_setup_units || return 1
 "$BIN" check -c "$BASE/argo-server.json" || return 1
 systemctl start skybyte-argo-node.service || return 1
 systemctl start skybyte-argo-tunnel.service || return 1
 argo_wait || { err "$(L '隧道连接未就绪，请检查状态' 'Tunnel connection not ready; inspect status')"; return 1; }
 exports
}
argo_remove_internal(){
 argo_guard || return 1
 if [[ -f $SYSTEMD_DIR/skybyte-argo-tunnel.service ]]; then systemctl disable --now skybyte-argo-tunnel.service || return 1; fi
 if [[ -f $SYSTEMD_DIR/skybyte-argo-node.service ]]; then systemctl disable --now skybyte-argo-node.service || return 1; fi
 warp_engine forget_argo || return 1
 for file in argo-state.json argo-server.json argo-empty.yml argo.token cloudflared; do rm -f -- "$BASE/$file"; done
 rm -f -- "$SYSTEMD_DIR/skybyte-argo-node.service" "$SYSTEMD_DIR/skybyte-argo-tunnel.service"
 systemctl daemon-reload
}
argo_remove(){
 [[ -f $BASE/argo-state.json ]] || return 0
 argo_guard || return 1
 confirm "$(L '备份后卸载本机 Argo 附加节点？Cloudflare 账户内的隧道和 DNS 不会删除。' 'Back up and remove the local Argo add-on? Cloudflare tunnel/DNS records will not be deleted.')" || return 0
 local snap; snap=$(backup) || return 1
 argo_remove_internal || return 1
 ok "$(L 'Argo 已卸载；备份：' 'Argo removed; backup: ')$snap"
 exports
}
argo_restore_snapshot(){
 local path=$1 file
 argo_guard || return 1
 if [[ ! -f $path/argo-state.json ]]; then
  [[ ! -f $BASE/argo-state.json ]] || argo_remove_internal || return 1
  return 0
 fi
 [[ -f $path/argo-server.json && -f $path/cloudflared.bin ]] || return 1
 "$BIN" check -c "$path/argo-server.json" || return 1
 argo_stop || return 1
 for file in argo-state.json argo-server.json argo-empty.yml argo.token; do
  if [[ -f $path/$file ]]; then cp "$path/$file" "$BASE/$file" || return 1; chmod 600 "$BASE/$file"; else rm -f -- "$BASE/$file"; fi
 done
 command install -m 755 "$path/cloudflared.bin" "$BASE/cloudflared" || return 1
 argo_clear_ready || return 1
 argo_setup_units || return 1
 systemctl enable --now skybyte-argo-node.service || return 1
 systemctl enable --now skybyte-argo-tunnel.service || return 1
}
argo_manager(){
 local choice
 # --menu renders only; a numeric argument executes one selected operation.
 if [[ $# == 0 || $1 == --menu ]]; then
 prompt_options '1. 临时隧道
2. 固定隧道
3. 状态
4. 启动
5. 停止
6. 重启
7. 刷新节点
8. 卸载 Argo
9. 地址族与传输设置
0. 返回' '1. Quick
2. Named
3. Status
4. Start
5. Stop
6. Restart
7. Refresh nodes
8. Remove Argo
9. Address family/transport
0. Back'
 [[ ${1:-} != --menu ]] || return 0
 prompt_read '> ' choice || return 0
 else
  choice=$1
 fi
 case $choice in
  1) argo_install quick;; 2) argo_install named;; 3) report_output argo_status;; 4) argo_start;;
  5) argo_stop && exports;; 6) argo_stop && argo_start;; 7) exports;; 8) argo_remove;;9) argo_network_settings;; 0) return 0;; *) err "$(L '无效选项' 'Invalid choice')"; return 1;;
 esac
}

