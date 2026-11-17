import type { ReactNode } from 'react';
import allocations from './electoral-college.json';
import { partyPalette } from './electionColors';
import type { ElectionMap, MapUnit } from './types';
import './electoral-college.css';

interface Allocation {
  candidates: { name: string; party: string; votes: number }[];
  states: Record<string, { name: string; electors: number; votes: number[]; other: number }>;
  other_label: string; other: number;
  source: { url: string; sha256: string; retrieved_at: string };
}
import { smallStates } from '../geography/smallStates';
export { smallStates } from '../geography/smallStates';
export const electoralAllocation = (year: number): Allocation | undefined =>
  (allocations as Record<string, Allocation>)[String(year)];
const color = (party: string) => party === 'DEMOCRATIC' ? partyPalette.Democratic : partyPalette.Republican;
export const isPresidential = (office: string, stage: string) =>
  ['u.s. president', 'president of the united states'].includes(office.trim().toLowerCase()) && stage === 'general';

export function ElectoralCollegeCounter({ year }: { year: number }) {
  const election = electoralAllocation(year);
  if (!election) return null;
  const candidates = [...election.candidates].sort((a, b) => a.party === b.party ? 0 : a.party === 'DEMOCRATIC' ? -1 : 1);
  return <section className="electoral-counter" aria-label={`${year} Electoral College results`}>
    <h2>Electoral College · {year}</h2>
    <div className="electoral-totals">{candidates.map(candidate => <span key={candidate.party} style={{ color: color(candidate.party) }}>
      {candidate.name} ({candidate.party === 'DEMOCRATIC' ? 'D' : 'R'}) <strong>{candidate.votes}</strong>
    </span>)}{election.other > 0 && <span>{election.other_label} <strong>{election.other}</strong></span>}</div>
    <div className="electoral-bar" role="img" aria-label={`${candidates.map(c => `${c.name}: ${c.votes}`).join('; ')}${election.other ? `; ${election.other_label}: ${election.other}` : ''}. 270 electoral votes needed to win.`}>
      {candidates.map(c => <span key={c.party} style={{ width: `${c.votes / 538 * 100}%`, background: color(c.party) }} />)}
      {election.other > 0 && <span style={{ width: `${election.other / 538 * 100}%`, background: '#687687' }} />}
      <i style={{ left: `${270 / 538 * 100}%` }} aria-hidden="true" />
    </div>
    <p className="electoral-majority">270 to win · 538 electors · National certified count</p>
    <details><summary>Electoral allocations & source</summary>
      <p>Certified presidential electoral votes, independent of popular-vote map leaders and filters. Split Maine/Nebraska allocations and faithless electors are retained; {year === 2000 ? 'the DC abstention is separate.' : 'votes for other candidates are separate.'}</p>
      <a href={election.source.url} target="_blank" rel="noreferrer">National Archives · {year} official results</a>
      <div className="electoral-state-list">{Object.entries(election.states).map(([code, state]) => <p key={code}><strong>{code} · {state.electors}</strong> — {election.candidates.map((c, i) => `${c.name}: ${state.votes[i]}`).join('; ')}{state.other ? `; ${election.other_label}: ${state.other}` : ''}</p>)}</div>
    </details>
  </section>;
}

export function PresidentialMapLabels({ data, onSelect, children }: { data: ElectionMap; onSelect: (unit: MapUnit) => void; children: ReactNode }) {
  const election = electoralAllocation(data.year);
  if (!election || !isPresidential(data.office, data.stage) || data.reporting_level !== 'state' || data.state_code) return children;
  return <div className="presidential-map-labels"><div>{children}</div><aside aria-label="Small states and DC electoral votes">
    {[...smallStates].map(code => {
      const state = election.states[code];
      const unit = data.units.find(unit => unit.state_code === code);
      const winner = state.votes[0] === state.votes[1] ? undefined : election.candidates[state.votes[0] > state.votes[1] ? 0 : 1];
      return <button key={code} onClick={() => unit && onSelect(unit)} disabled={!unit}
        style={{ background: winner ? color(winner.party) : '#687687' }}
        aria-label={`${state.name}: ${state.electors} electoral votes; view county results`}>
        <span>{code}</span><strong>{state.electors}</strong>
      </button>;
    })}
    <p>Electors by state. Map colors show popular-vote leaders.</p>
  </aside></div>;
}
