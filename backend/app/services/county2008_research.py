"""Inspect archived official source links and extract limited PDF research pages."""
import argparse
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urljoin


class Links(HTMLParser):
    def __init__(self):
        super().__init__();self.links=[];self.active=None;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a':
            self.active=dict(attrs).get('href');self.parts=[]
    def handle_data(self,data):
        if self.active is not None:
            self.parts.append(data)
    def handle_endtag(self,tag):
        if tag=='a' and self.active is not None:
            self.links.append((self.active,' '.join(' '.join(self.parts).split())))
            self.active=None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive',type=Path)
    p.add_argument('--extract-dir',type=Path)
    p.add_argument('--max-pages',type=int,default=16)
    args=p.parse_args()
    records=json.loads((args.archive/'retrievals.json').read_text(encoding='utf-8'))
    if args.extract_dir:
        args.extract_dir.mkdir(parents=True,exist_ok=False)
        from pypdf import PdfReader,__version__
    for r in records:
        if not r.get('success'):
            print(json.dumps({'id':r['id'],'error':r.get('error')}));continue
        path=args.archive/r['file']
        if sha256(path.read_bytes()).hexdigest()!=r['sha256']:
            raise ValueError('Archived bytes changed')
        if path.suffix=='.pdf':
            if not args.extract_dir:
                continue
            reader=PdfReader(path)
            pages=[dict(page=n+1,text=reader.pages[n].extract_text(extraction_mode='layout') or '',
                        plain_text=reader.pages[n].extract_text() or '')
                   for n in range(min(len(reader.pages),args.max_pages))]
            out=args.extract_dir/(r['id']+'.pages.json')
            out.write_text(json.dumps(pages,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
            print(json.dumps({'id':r['id'],'pages':len(reader.pages),'extracted':len(pages)}))
            continue
        body=path.read_bytes().decode('utf-8',errors='replace')
        links=Links();links.feed(body)
        candidates=[dict(url=urljoin(r['url'],url),label=label) for url,label in links.links
                    if re.search(r'2008|president|download|\.csv|\.xls|\.zip',url+' '+label,re.I)]
        if r.get('kind')=='index':
            print(json.dumps({'id':r['id'],'links':candidates[:60]}))


if __name__=='__main__':
    main()
