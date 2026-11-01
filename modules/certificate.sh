# modules/certificate.sh — build-time module; assembled by scripts/build.py.
validate_certificate(){
 local cert=$1 key=$2 name=$3 certpub keypub
 LC_ALL=C openssl x509 -in "$cert" -noout -checkend 0 >/dev/null || { err "$(L '证书无效或已过期' 'Certificate invalid or expired')"; return 1; }
 if python3 - "$name" <<'PY_NAME_IP'
import ipaddress,sys
try:ipaddress.ip_address(sys.argv[1])
except ValueError:sys.exit(1)
PY_NAME_IP
 then
  LC_ALL=C openssl x509 -in "$cert" -noout -checkip "$name" | grep -q "does match" || { err "$(L '证书 IP 不匹配' 'Certificate IP does not match')"; return 1; }
 else
  LC_ALL=C openssl x509 -in "$cert" -noout -checkhost "$name" | grep -q "does match" || { err "$(L '证书域名不匹配' 'Certificate hostname does not match')"; return 1; }
 fi
 certpub=$(openssl x509 -in "$cert" -pubkey -noout) || return 1
 keypub=$(openssl pkey -in "$key" -pubout -passin pass: 2>/dev/null) || return 1
 [[ $certpub == "$keypub" ]] || { err "$(L '证书和私钥不匹配' 'Certificate and private key do not match')"; return 1; }
}
# Download only a verified release binary; never execute a package installer on updates.
