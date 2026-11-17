import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { Title, Notice } from './components';
import { presidentialYears } from './presidential';
import previews from './presidential-previews.json';

interface Election { id:string; election_date:string; stage:string }
export function PresidentialHistory() {
  const [attempt, retry] = useState(0);
  const [state, setState] = useState<{ items?:Election[]; error?:string }>({});
  useEffect(() => {
    const controller = new AbortController();
    setState({});
    async function load() {
      const unique = new Map<string,Election>();
      let offset=0;
      while (true) {
        const response=await fetch(`/api/v1/elections?office=U.S.+President&limit=200&offset=${offset}`, { signal:controller.signal, headers:{ Accept:'application/json' } });
        if (!response.ok) throw new Error('Unavailable');
        const page=await response.json();
        if (!Array.isArray(page.items) || typeof page.has_more !== 'boolean') throw new Error('Invalid response');
        for (const item of page.items as Election[]) {
          if (!/^\d{4}-\d{2}-\d{2}$/.test(item.election_date) || typeof item.stage !== 'string') throw new Error('Invalid election');
          unique.set(`${item.election_date}:${item.stage}`,item);
        }
        if (!page.has_more) break;
        if (!page.items.length) throw new Error('Invalid pagination');
        offset+=page.items.length;
      }
      if (!controller.signal.aborted) setState({ items:[...unique.values()].sort((a,b)=>b.election_date.localeCompare(a.election_date) || a.stage.localeCompare(b.stage)) });
    }
    load().catch(() => { if (!controller.signal.aborted) setState({ error:'Election history could not be loaded. Please try again.' }); });
    return () => controller.abort();
  },[attempt]);
  return <><Title title="Presidential election history">Explore every presidential election represented in the database. Choose an election to open its results.</Title>
    {state.error ? <Notice title="History unavailable" error><p>{state.error}</p><button onClick={()=>retry(n=>n+1)}>Try again</button></Notice> : !state.items ? <p role="status">Loading election history…</p> : !state.items.length ? <Notice title="No presidential elections available"><p>No elections are currently represented in the database.</p></Notice> :
      <div className="election-history-grid">{state.items.map(item=> {
        const year=Number(item.election_date.slice(0,4));
        const preview=(previews as Record<string,{ src:string; label:string }>)[`${item.election_date}:${item.stage}`];
        const to=item.stage === 'general' && presidentialYears.some(y=>y===year) ? `/presidential/${year}` : `/map?${new URLSearchParams({ year:String(year),office:'U.S. President',stage:item.stage })}`;
        return <Link className="election-history-card" to={to} key={`${item.election_date}:${item.stage}`}>
          {preview ? <img src={preview.src} alt={preview.label} width="480" height="300" loading="lazy" decoding="async" /> : <div className="preview-unavailable">Preview pending</div>}
          <div className="history-card-content"><span className="eyebrow">{item.stage.replaceAll('_',' ')} · {item.election_date}</span><h2>{year} Presidential election <span aria-hidden="true">↗</span></h2><p>View results and source coverage</p></div>
        </Link>;
      })}</div>}
    <p className="field-help">Previews are generated snapshots of published state results. Open an election for current totals, geographic details and coverage limitations.</p>
  </>;
}
