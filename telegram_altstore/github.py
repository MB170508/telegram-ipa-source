from __future__ import annotations
import json, logging, os, re, time
from datetime import datetime, timezone
from pathlib import Path
import requests

log=logging.getLogger(__name__)
class GitHubError(RuntimeError): pass
class GitHub:
    def __init__(self, owner, repo, token, verify=True):
        self.owner,self.repo=owner,repo; self.base=f'https://api.github.com/repos/{owner}/{repo}'; self.verify=verify
        self.s=requests.Session(); self.s.headers.update({'Authorization':f'Bearer {token}','Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
    def _call(self, method, url, **kw):
        for attempt in range(5):
            r=self.s.request(method,url,timeout=60,**kw)
            if r.status_code==403 and r.headers.get('X-RateLimit-Remaining')=='0':
                wait=max(1,int(r.headers.get('X-RateLimit-Reset','0'))-int(time.time())+1); log.warning('GitHub rate limited; sleeping %ss',wait); time.sleep(min(wait,900)); continue
            if r.status_code>=500 or r.status_code==429: time.sleep(min(2**attempt,30)); continue
            return r
        raise GitHubError(f'GitHub API retries exhausted: {method} {url}')
    def publish_ipa(self, path:Path, sha256:str, bundle_id:str, version:str, build:str):
        tag='ipa-'+sha256[:20]; url=self.base+'/releases/tags/'+tag
        r=self._call('GET',url)
        if r.status_code==200:
            release=r.json(); asset=next((a for a in release.get('assets',[]) if a['name'].endswith('.ipa')),None)
            if asset: return release['tag_name'],asset['browser_download_url']
        elif r.status_code!=404: raise GitHubError(f'release lookup: {r.status_code} {r.text[:300]}')
        payload={'tag_name':tag,'name':f'{bundle_id} {version} ({build})','body':f'Automated Telegram IPA import\n\nBundle: `{bundle_id}`\nVersion: `{version}` ({build})\nSHA-256: `{sha256}`','draft':False,'prerelease':False}
        r=self._call('POST',self.base+'/releases',json=payload)
        if r.status_code not in (200,201): raise GitHubError(f'release create: {r.status_code} {r.text[:500]}')
        release=r.json(); asset_name='app-'+sha256[:20]+'.ipa'
        with path.open('rb') as f: r=self._call('POST',release['upload_url'].split('{')[0],params={'name':asset_name},headers={'Content-Type':'application/octet-stream'},data=f)
        if r.status_code not in (200,201): raise GitHubError(f'asset upload: {r.status_code} {r.text[:500]}')
        asset=r.json(); download=asset['browser_download_url']
        if self.verify:
            try: check=requests.head(download,allow_redirects=True,timeout=30)
            except requests.RequestException as e: raise GitHubError(f'could not verify public asset URL: {e}')
            if check.status_code!=200: raise GitHubError(f'asset is not anonymously downloadable (HTTP {check.status_code}); make repository/release public')
        return release['tag_name'],download
    def put_file(self, path, content, message, existing_sha=None):
        data={'message':message,'content':__import__('base64').b64encode(content).decode()}
        if existing_sha: data['sha']=existing_sha
        r=self._call('PUT',self.base+'/contents/'+path,json=data)
        if r.status_code not in (200,201): raise GitHubError(f'contents update {path}: {r.status_code} {r.text[:500]}')
        return r.json()
    def get_file(self,path):
        r=self._call('GET',self.base+'/contents/'+path)
        if r.status_code==404:return None
        if r.status_code!=200:raise GitHubError(f'contents read {path}: {r.status_code}')
        return r.json()
    def publish_source(self, source, source_path, backups_path):
        old=self.get_file(source_path); now=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        if old:
            import base64
            previous=base64.b64decode(old['content'])
            self.put_file(f'{backups_path}/source-{now}.json',previous,f'Backup source.json {now}')
        raw=(json.dumps(source,indent=2,ensure_ascii=False)+'\n').encode()
        return self.put_file(source_path,raw,'Update AltStore source',old.get('sha') if old else None)
