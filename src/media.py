"""Anonymous service-page probes; evidence is never a playback guarantee."""
import concurrent.futures
import datetime
import html
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.parse

PROBES={
 'Netflix':['https://www.netflix.com/title/81280792','https://www.netflix.com/title/70143836'],
 'Disney+':['https://www.disneyplus.com/'],
 'ChatGPT':['https://chatgpt.com/'],
 'Gemini':['https://gemini.google.com/'],
 'YouTube Premium':['https://www.youtube.com/premium'],
 'Amazon Prime Video':['https://www.primevideo.com/'],
 'TikTok':['https://www.tiktok.com/','https://www.tiktok.com/passport/web/store_region/']}
LABELS={
 'catalog':('片目页面有视频信息；播放未验证','Catalog video metadata; playback unverified'),
 'supported':('页面声明地区支持；播放未验证','Page reports supported location; playback unverified'),
 'offer':('页面提供订阅入口；订阅资格未验证','Subscription offer shown; eligibility unverified'),
 'restricted':('页面明确提示地区限制','Explicit location restriction on page'),
 'unknown':('页面可访问；解锁状态未知','Page reachable; unlock status unknown'),
 'verification':('访问被拒绝或需验证；解锁未知','Access denied/verification required; unlock unknown'),
 'network':('连接/DNS/TLS失败；解锁未知','Connection/DNS/TLS failed; unlock unknown'),
 'changed':('响应异常或页面变化；解锁未知','Unexpected response/page changed; unlock unknown')}

# These fields are page-provided hints, not proof of account eligibility or playback.
REGION_FIELDS={
 'Netflix':(('requestCountry','id'),('countryCode',),('country_code',)),
 'Disney+':(('countryCode',),('country_code',),('currentTerritory',),('territory',),('regionCode',)),
 'YouTube Premium':(('countryCode',),('country_code',),('gl',)),
 'Amazon Prime Video':(('currentTerritory',),('territory',),('countryCode',),('country_code',)),
 'TikTok':(('store_region',),('countryCode',),('country_code',),('region',))}
REGION_NAMES={
 'AU':('澳大利亚','Australia'),'BR':('巴西','Brazil'),'CA':('加拿大','Canada'),
 'DE':('德国','Germany'),'ES':('西班牙','Spain'),'FR':('法国','France'),
 'GB':('英国','United Kingdom'),'HK':('香港','Hong Kong'),'ID':('印度尼西亚','Indonesia'),
 'IN':('印度','India'),'IT':('意大利','Italy'),'JP':('日本','Japan'),
 'KR':('韩国','South Korea'),'MX':('墨西哥','Mexico'),'MY':('马来西亚','Malaysia'),
 'NL':('荷兰','Netherlands'),'PH':('菲律宾','Philippines'),'RU':('俄罗斯','Russia'),
 'SC':('塞舌尔','Seychelles'),'SG':('新加坡','Singapore'),'TH':('泰国','Thailand'),
 'TR':('土耳其','Türkiye'),'TW':('台湾','Taiwan'),'US':('美国','United States'),
 'VN':('越南','Vietnam')}

def fetch(url,path='4',port=None,post=False):
    # Ignore curlrc/proxy environment. No login cookies, authorization or node data.
    with tempfile.TemporaryDirectory() as tmp:
        body=Path(tmp)/'body'
        cmd=['curl','-q','--silent','--show-error','--location','--max-redirs','4',
             '--proto','=https','--proto-redir','=https','--connect-timeout','4','--max-time','12',
             '--max-filesize','8388608','--limit-rate','1M','--user-agent','Mozilla/5.0 SKYBYTE-Manager/2.4',
             '--header','Accept-Language: en-US,en;q=0.9','--output',str(body),
             '--write-out','%{http_code}\n%{url_effective}']
        if path=='warp':cmd+=['--noproxy','','--proxy','socks5h://127.0.0.1:'+str(port)]
        else:cmd+=['--noproxy','*','-'+path]
        if post:cmd+=['--request','POST','--data','']
        cmd.append(url)
        try:r=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
        except (subprocess.TimeoutExpired,OSError):return {'error':True,'code':0,'body':'','url':url}
        lines=r.stdout.splitlines()
        code=int(lines[0]) if lines and lines[0].isdigit() else 0
        text=body.read_bytes()[:8388608].decode('utf-8','replace') if body.exists() else ''
        return {'error':r.returncode!=0,'code':code,'body':text,'url':lines[1] if len(lines)>1 else url}

def country_values(text,key):
    # Handle both literal JSON and JSON strings embedded with escaped quotes.
    quote=r'(?:\\)?["\']'
    return list(dict.fromkeys(m[1].upper() for m in re.finditer(quote+re.escape(key)+quote+r'\s*:\s*'+quote+r'([A-Za-z]{2})'+quote,text)))

def country(text,key):
    return next(iter(country_values(text,key)),'-')

def url_region(response):
    url=response.get('url','')
    try:parsed=urllib.parse.urlsplit(url)
    except ValueError:return '-',''
    query=urllib.parse.parse_qs(parsed.query)
    for key in ('country','countryCode','region','gl'):
        for value in query.get(key,[]):
            if re.fullmatch('[A-Za-z]{2}',value):return value.upper(),'final URL '+key
    # Locale paths identify the page's selected territory, not necessarily the egress IP.
    match=re.search(r'(?:^|/)[a-z]{2}-([a-z]{2})(?:/|$)',parsed.path,re.I)
    if match:return match[1].upper(),'final URL locale'
    return '-',''

def region_hint(service,responses):
    hints=[]
    for response in responses:
        if response.get('error') or response.get('code')!=200:continue
        body=html.unescape(response.get('body',''))
        found=False
        for fields in REGION_FIELDS.get(service,()):
            if len(fields)==2:
                parent,child=fields
                quote=r'(?:\\)?["\']'
                pattern=quote+re.escape(parent)+quote+r'\s*:\s*\{[^{}]{0,512}?'+quote+re.escape(child)+quote+r'\s*:\s*'+quote+r'([A-Za-z]{2})'+quote
                values=[match[1].upper() for match in re.finditer(pattern,body,re.S)]
                source=parent+'.'+child
            else:
                source=fields[0];values=country_values(body,source)
            for value in values:
                hints.append((value,source))
                found=True
        if not found:
            value,source=url_region(response)
            if value!='-':hints.append((value,source))
    # Preserve conflicting provider hints instead of silently choosing one.
    values=list(dict.fromkeys(value for value,_ in hints))
    sources=list(dict.fromkeys(source for _,source in hints))
    return '/'.join(values) if values else '-',', '.join(sources)

def region_label(region,language):
    if region=='-':return '未识别' if language=='zh_CN' else 'not identified'
    names=[]
    for code in region.split('/'):
        name=REGION_NAMES.get(code)
        names.append((name[0] if language=='zh_CN' else name[1])+' ('+code+')' if name else code)
    return '/'.join(names)

def location_restricted(service,body):
    low=body.lower()
    messages={
        'Netflix':('not available to watch in your area','this title is not available in your country'),
        'Disney+':(),
        'YouTube Premium':('premium is not available in your country',),
        'Amazon Prime Video':('this video is currently unavailable to watch in your location',),
        'TikTok':('this content is not available in your region','not available in your region')}
    return any(phrase in low for phrase in messages.get(service,()))

def json_boolean(text,key):
    quote=r'(?:\\)?["\']'
    match=re.search(quote+re.escape(key)+quote+r'\s*:\s*(true|false)',text,re.I)
    return match[1].lower() if match else None

def status_color(status):
    if status in ('catalog','offer','supported'):return '\033[1;32m'
    if status in ('restricted','network','changed'):return '\033[1;31m'
    return '\033[1;33m'

def ai_location_restricted(service,body):
    if service not in ('ChatGPT','Gemini'):return False
    try:
        data=json.loads(body)
        error=data.get('error',data) if isinstance(data,dict) else None
    except (ValueError,TypeError):error=None
    if isinstance(error,dict):
        code=str(error.get('code',error.get('type',''))).lower()
        if code in ('unsupported_country','unsupported_country_region_territory'):return True
        visible=str(error.get('message','')).lower()
    else:
        # Do not mistake dormant JavaScript translations/error enums for a denial.
        visible=re.sub(r'<(script|style)\b[^>]*>.*?</\1\s*>',' ',body,flags=re.I|re.S)
        visible=html.unescape(re.sub(r'<[^>]+>',' ',visible)).lower()
    phrases=('not available in your country','not available in your region','not supported in your country',
             "gemini isn't available in your country",'gemini isn’t available in your country',
             'user location is not supported for the api use')
    return any(phrase in visible for phrase in phrases)

def classify(service,responses):
    main=responses[0];body=main['body'];low=body.lower()
    region,region_source=region_hint(service,responses)
    result={'service':service,'status':'unknown','region':region,'region_source':region_source,'http_code':main['code']}
    if main['error']:result['status']='network';return result
    if ai_location_restricted(service,body):
        result['status']='restricted';return result
    if main['code'] in (401,403,429,451) or any(x in low for x in ['verify you are human','cf-chl-','robot check','unusual traffic']):
        result['status']='verification';return result
    if main['code']!=200:result['status']='changed';return result
    if location_restricted(service,body):result['status']='restricted';return result
    if service=='Netflix':
        if any(not r['error'] and r['code']==200 and re.search(r'<meta\b[^>]*(?:property|name)=["\']og:video',r['body'],re.I) for r in responses):result['status']='catalog'
    elif service=='Disney+':
        if json_boolean(body,'inSupportedLocation')=='false' or '/unavailable' in urllib.parse.urlsplit(main['url']).path:
            result['status']='restricted'
        elif json_boolean(body,'inSupportedLocation')=='true':result['status']='supported'
    elif service=='YouTube Premium':
        if 'purchaseButtonOverride' in body or 'start trial' in low:result['status']='offer'
    return result

def probe(service,path,port):
    rows=[fetch(url,path,port,service=='TikTok' and n==1) for n,url in enumerate(PROBES[service])]
    return classify(service,rows)

def run(paths,report,port=None,language='zh_CN'):
    en=language=='en_US';results=[]
    for path in paths:
        if path=='warp' and not (port and 1024<=port<=65535):raise ValueError('Invalid WARP proxy port')
        label={'4':'VPS IPv4','6':'VPS IPv6','warp':'WARP proxy (remote DNS)'}[path]
        print('\n'+label+'\n'+'-'*64,flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            rows=list(pool.map(lambda s:probe(s,path,port),PROBES))
        for row in rows:
            row['path']=path;results.append(row)
            color=status_color(row['status'])
            if not __import__('sys').stdout.isatty() or os.environ.get('NO_COLOR'):color=''
            region=region_label(row['region'],language)
            source=(' ('+row['region_source']+')') if row.get('region_source') else ''
            print(color+row['service']+' | '+LABELS[row['status']][int(en)]+' | '+('Page region clue: ' if en else '页面识别地区线索：')+region+source+' | HTTP '+str(row['http_code'])+('\033[0m' if color else ''))
    report=Path(report);report.mkdir(exist_ok=True,mode=0o700)
    if report.is_symlink():raise ValueError('Report directory is a symlink')
    fd,tmp=tempfile.mkstemp(prefix='media-',suffix='.json',dir=report)
    with os.fdopen(fd,'w') as f:
        json.dump({'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'playback_verified':False,'results':results},f,ensure_ascii=False,indent=2)
    print(('Report: ' if en else '报告：')+tmp)
    return results

if __name__=='__main__':
    import sys
    paths,report,port,lang=sys.argv[1:]
    run(paths.split(','),report,int(port) if port else None,lang)
