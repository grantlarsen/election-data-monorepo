import { useEffect, useId, useMemo, useState } from 'react';
import { UnitedStatesMap } from './geography/UnitedStatesMap';
import type { JurisdictionCollection, JurisdictionFeature } from './geography/unitedStates';
import { indeterminateColor, partyPalette, tieColor } from './map/electionColors';
import type { ReactNode } from 'react';
import statesUrl from './geography/data/states.json?url';
import greatLakes from './geography/data/great-lakes.json';
import type { FeatureCollection, Polygon, MultiPolygon } from 'geojson';

export interface StateResultRace {
  id: string; state_code: string; status: 'counting' | 'called' | 'final';
  total_votes: number | null; candidates: { votes: number | null; party: string }[];
  summary_status?: string | null;
}
interface StateResults<R> { races: R[]; missing_states: string[] }

const noElectionColor = '#edf1ed';
const missingColor = '#b6c1c8';
const statusLabels = { counting: 'Counting · no call', called: 'Media call · uncertified', final: 'Certified · per source' };
const number = (value: number) => value.toLocaleString('en-US');

interface StateOutlines extends JurisdictionCollection {
  source: { boundary_vintage: string; documentation_url: string; vintage_note: string };
}
interface MapState<R> { race: R | undefined; missing: boolean }

/** Color the current count, without interpreting a lead as a call or certification. */
export function stateRaceColor(race: StateResultRace): string {
  if (['indeterminate', 'no_results', 'zero_total'].includes(race.summary_status || '')) return indeterminateColor;
  if (!race.total_votes) return indeterminateColor;
  const highest = Math.max(...race.candidates.map(candidate => (candidate.votes ?? 0)));
  const leaders = race.candidates.filter(candidate => candidate.votes === highest);
  if (leaders.length !== 1) return tieColor;
  const party = leaders[0].party;
  return partyPalette[party === 'D' ? 'Democratic' : party === 'R' ? 'Republican' : party ? 'Other / independent' : 'Party unavailable'];
}

/** State-code join only: these source-scoped counts have no canonical person/geography IDs. */
export default function StateResultsMap<R extends StateResultRace>({ data, selectedState, onSelect, onClear, raceState, office, tooltip, flipped }: {
  data: StateResults<R>; office: string; tooltip: (race: R | undefined, name: string, missing: boolean) => ReactNode; selectedState: string; onSelect: (state: string) => void; onClear?: () => void; raceState?: string;
  flipped?: (race: R) => boolean;
}) {
  const mapId = useId().replace(/:/g, '');
  const patternId = (race: R) => `state-flip-${mapId}-${race.id}`;
  const [outlines, setOutlines] = useState<StateOutlines>();
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setError(false);
    fetch(statesUrl, { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error('State outlines unavailable');
      const body: StateOutlines = await response.json();
      if (body?.type !== 'FeatureCollection' || body.features?.length !== 51 || !body.source ||
          (raceState && !body.features.some(feature => feature.properties.state_code === raceState)) ||
          new Set(body.features.map(feature => feature.properties.state_code)).size !== 51 ||
          body.features.some(feature => String(feature.id) !== feature.properties.geoid ||
            !/^[A-Z]{2}$/.test(feature.properties.state_code) || !/^[0-9]{2}$/.test(feature.properties.geoid))) {
        throw new Error('Invalid state outlines');
      }
      if (current) setOutlines(body);
    }).catch(() => { if (current && !controller.signal.aborted) setError(true); });
    return () => { current = false; controller.abort(); };
  }, [attempt, raceState]);
  const displayedOutlines = useMemo(() => outlines && raceState
    ? { ...outlines, features: outlines.features.filter(feature => feature.properties.state_code === raceState) }
    : outlines, [outlines, raceState]);
  const byState = useMemo(() => new Map(data.races.map(race => [race.state_code, race])), [data.races]);
  const missing = useMemo(() => new Set(data.missing_states), [data.missing_states]);
  const matched = useMemo(() => new Map(outlines?.features.map(feature => {
    const race = byState.get(feature.properties.state_code);
    return [feature.properties.geoid, { race, missing: missing.has(feature.properties.state_code) }] as const;
  })), [outlines, byState, missing]);
  const selected = outlines?.features.find(feature => feature.properties.state_code === selectedState);
  function unavailable(feature: JurisdictionFeature) {
    return missing.has(feature.properties.state_code) ? 'Returns unavailable' : `No ${office} election in 2026`;
  }
  const legend = [
    ['Democratic lead', partyPalette.Democratic], ['Republican lead', partyPalette.Republican],
    ['Other / independent lead', partyPalette['Other / independent']], ['Tie', tieColor],
    ['No determined leader', indeterminateColor],
    ['Returns unavailable', missingColor], ['No election', noElectionColor],
  ];
  return <section className="senate-map-panel" aria-label={`${office} results map`}>
    {selectedState && !raceState && onClear && <div className="senate-map-actions"><button onClick={onClear}>Show all states</button></div>}
    {error ? <div className="notice" role="status"><p>The map could not load. State results remain available below.</p>
      <button onClick={() => setAttempt(value => value + 1)}>Retry map</button></div>
      : !outlines || !displayedOutlines ? <p role="status">Loading state map…</p> : <>
        <UnitedStatesMap<MapState<R>> features={displayedOutlines} data={matched} title={raceState ? `${selected?.properties.name || raceState} 2026 ${office} race map` : `2026 ${office} results map`}
          selectedId={selected?.properties.geoid} focusSelection={false}
          water={raceState ? undefined : greatLakes as FeatureCollection<Polygon | MultiPolygon, { name: string }>}
          isInteractive={unit => !!unit?.race || !!unit?.missing}
          definitions={flipped && data.races.filter(flipped).map(race => <pattern key={race.id} id={patternId(race)} width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="8" height="8" fill={stateRaceColor(race)} /><line x1="0" y1="0" x2="0" y2="8" stroke="#fff" strokeWidth="3" strokeOpacity="0.7" />
          </pattern>)}
          fill={unit => unit?.race ? flipped?.(unit.race) ? `url(#${patternId(unit.race)})` : stateRaceColor(unit.race) : unit?.missing ? missingColor : noElectionColor}
          describe={(unit, feature) => `${feature.properties.name}: ${unit?.race ? `${statusLabels[unit.race.status]}, ${unit.race.total_votes === null ? 'unavailable' : number(unit.race.total_votes)} votes counted${flipped?.(unit.race) ? ', party flipped from the previous election' : ''}` : unavailable(feature)}`}
          tooltip={(unit, feature) => tooltip(unit?.race, feature.properties.name, !!unit?.missing)}
          onSelect={(_, feature) => onSelect(feature.properties.state_code)}
          attribution={<><a href={outlines.source.documentation_url}>Census 2024 state outlines</a> · Display geography, not 2026 election-day boundary certification{!raceState && <> · Water: <a href={greatLakes.source.documentation}>Natural Earth</a></>}</>} />
        <ul className="senate-map-legend" aria-label="Map legend">{(raceState ? legend.slice(0, 5) : legend).map(([label, fill]) =>
          <li key={label}><span style={{ background: fill }} />{label}</li>)}
          {flipped && <li><span style={{ background: 'repeating-linear-gradient(135deg, #84949c 0 4px, #fff 4px 6px)' }} />Party flipped from previous election (called or certified)</li>}</ul>
        {selectedState && !raceState && <p role="status">Showing {selected?.properties.name || selectedState} in the results below.</p>}
      </>}
  </section>;
}
