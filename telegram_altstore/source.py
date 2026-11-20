from __future__ import annotations
import json, re
from pathlib import Path

class SourceError(ValueError): pass

def permission_object(meta):
    return {'entitlements':[{'name':x} for x in meta.entitlements], 'privacy':[{'name':str(k),'usageDescription':str(v)} for k,v in meta.privacy]}

def build_source(config, rows):
    apps={}
    for r in rows:
        if not r.get('asset_url'): continue
        m=json.loads(r['metadata_json']) if r.get('metadata_json') else {}
        bid=r['bundle_id']; app=apps.setdefault(bid, {'name':m.get('name',bid),'bundleIdentifier':bid,'developerName':'Unknown','localizedDescription':'Imported from Telegram.','versions':[], 'appPermissions':{'entitlements':[{'name':x} for x in m.get('entitlements',[])], 'privacy':[{'name':k,'usageDescription':v} for k,v in m.get('privacy',[])]}})
        version={'version':r['version'],'buildVersion':r['build'],'date':r['updated_at'][:10],'downloadURL':r['asset_url'],'size':m.get('size',0)}
        if m.get('min_os'): version['minOSVersion']=m['min_os']
        app['versions'].append(version)
    for app in apps.values(): app['versions'].sort(key=lambda x:(x['version']+x['buildVersion']), reverse=True)
    return {'name':config['source']['name'],'identifier':config['source']['identifier'],'subtitle':config['source'].get('subtitle',''),'description':config['source'].get('description',''),'tintColor':config['source'].get('tintColor','#2F6FED'),'apps':list(apps.values()),'news':[]}

def validate_source(source):
    for key in ('name','identifier','apps','news'):
        if key not in source: raise SourceError(f'missing source key: {key}')
    seen=set()
    for app in source['apps']:
        for key in ('name','bundleIdentifier','versions','appPermissions'):
            if key not in app: raise SourceError(f"{app.get('bundleIdentifier','app')}: missing {key}")
        if app['bundleIdentifier'] in seen: raise SourceError('duplicate bundleIdentifier')
        seen.add(app['bundleIdentifier'])
        for v in app['versions']:
            for key in ('version','buildVersion','date','downloadURL','size'):
                if key not in v or (key=='size' and not isinstance(v[key],int)): raise SourceError(f"{app['bundleIdentifier']}: invalid version field {key}")
            if not re.match(r'^https://',v['downloadURL']): raise SourceError('downloadURL must be HTTPS')
    return True

def write_source(path, source):
    validate_source(source); p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); tmp=p.with_suffix('.tmp'); tmp.write_text(json.dumps(source,indent=2,ensure_ascii=False)+'\n'); tmp.replace(p)
