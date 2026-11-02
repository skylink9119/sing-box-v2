# Runs inside xhttp_command's isolated shell; all inputs were already confirmed.
xhttp_install_automatic(){
 local kind=$XHTTP_KIND host listen=0.0.0.0 port=443 stage
 command -v curl >/dev/null || apt_install --no-install-recommends curl ca-certificates || return 1
 local flags=(--kind "$kind" --name "$XHTTP_NAME" --sni "$XHTTP_SNI")
 if [[ $kind == xhttp-tls && $XHTTP_CDN == 1 ]];then host=$XHTTP_SNI
 else host=$(curl -q -4fsS --noproxy '*' --max-time 12 https://api.ipify.org) || host=$(curl -q -6fsS --noproxy '*' --max-time 12 https://api64.ipify.org) || return 1;fi
 [[ $host != *:* ]] || listen=::
 if [[ $kind == xhttp-tls ]];then
  port=2053;flags+=(--cert "$XHTTP_CERT" --key "$XHTTP_KEY")
  if [[ $XHTTP_CDN == 1 ]];then flags+=(--cdn --mode packet-up);fi
 else flags+=(--target "$XHTTP_SNI:443");fi
 flags+=(--port "$port" --listen "$listen" --address "$host")
 helper preflight "${flags[@]}" || return 1
 install_environment_check "$kind" && install_port_check "$port" "$listen" || return 1
 if [[ $kind == xhttp-reality ]];then install_reality_target "$XHTTP_SNI" "$XHTTP_SNI:443" || return 1
 else helper tls-input --sni "$XHTTP_SNI" --cert "$XHTTP_CERT" --key "$XHTTP_KEY" || return 1;fi
 install_download_check && ensure_binary || return 1
 stage=$(helper prepare "${flags[@]}") || return 1
 apply_stage "$stage" yes || return 1
 show_nodes
}
