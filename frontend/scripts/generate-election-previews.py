"""Generate static presidential map cards against a running local atlas.

Requires the optional Playwright Python tooling and an installed browser.
Run from the repository root. No election/database records are changed.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--base-url',default='http://127.0.0.1:5173')
parser.add_argument('--channel',default='msedge')
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
folder=root/'public/election-previews'
folder.mkdir(parents=True,exist_ok=True)
manifest={}
with sync_playwright() as p:
    browser=p.chromium.launch(channel=args.channel,headless=True)
    page=browser.new_page(viewport=dict(width=1200,height=1000),device_scale_factor=1)
    events={}
    offset=0
    while True:
        response=page.request.get(f'{args.base_url}/api/v1/elections?office=U.S.+President&limit=200&offset={offset}')
        if not response.ok: raise RuntimeError('Election discovery failed')
        data=response.json()
        for event in data['items']:
            if event['stage']=='general': events[event['election_date']]=event
        if not data['has_more']: break
        if not data['items']: raise RuntimeError('Invalid discovery pagination')
        offset+=len(data['items'])
    for date in sorted(events):
        year=int(date[:4])
        with page.expect_response(lambda r:'/api/v1/election-map?' in r.url) as received:
            page.goto(f'{args.base_url}/map?year={year}')
        response=received.value
        if not response.ok: raise RuntimeError(f'Map failed for {year}')
        data=response.json()
        if not data['features']['features']: continue
        expect(page.locator('.us-map-svg path[data-geoid]')).to_have_count(len(data['features']['features']),timeout=90000)
        svg=page.locator('.us-map-svg')
        svg.evaluate("e=>Object.assign(e.style,{width:'480px',height:'300px',maxHeight:'none',minHeight:'0'})")
        filename=f'president-{year}-general.png'
        svg.screenshot(path=str(folder/filename),animations='disabled')
        manifest[f'{date}:general']=dict(src=f'/election-previews/{filename}',
            label=f'{year} presidential election — published state result preview',
            generated_at=datetime.now(timezone.utc).isoformat(),
            publications=data['publications'],boundary=data['boundary'])
        print(f'Generated {filename}',flush=True)
    browser.close()
(root/'src/presidential-previews.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
