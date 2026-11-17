import { useEffect, useMemo, useState } from 'react';
import { UnitedStatesMap } from './geography/UnitedStatesMap';
import type { JurisdictionCollection, JurisdictionFeature } from './geography/unitedStates';
import { indeterminateColor, partyPalette, tieColor } from './map/electionColors';
import type { SenateRace, SenateResults } from './senate';
import { SenatePopover } from './SenatePopover';
import statesUrl from './geography/data/states.json?url';
import greatLakes from './geography/data/great-lakes.json';
import type { FeatureCollection, Polygon, MultiPolygon } from 'geojson';

const noElectionColor = '#edf1ed';
const missingColor = '#b6c1c8';
const statusLabels = { counting: 'Counting · no call', called: 'Media call · uncertified', final: 'Certified · per source' };
const number = (value: number) => value.toLocaleString('en-US');

interface StateOutlines extends JurisdictionCollection {
  source: { boundary_vintage: string; documentation_url: string; vintage_note: string };
}
interface MapState { race: SenateRace | undefined; missing: boolean }

/** Color the current count, without interpreting a lead as a call or certification. */
export function senateRaceColor(race: SenateRace): string {
  if (['indeterminate', 'no_results', 'zero_total'].includes(race.summary_status || '')) return indeterminateColor;
  if (!race.total_votes) return indeterminateColor;
  const highest = Math.max(...race.candidates.map(candidate => candidate.votes));
  const leaders = race.candidates.filter(candidate => candidate.votes === highest);
  if (leaders.length !== 1) return tieColor;
  const party = leaders[0].party;
  return partyPalette[party === 'D' ? 'Democratic' : party === 'R' ? 'Republican' : party ? 'Other / independent' : 'Party unavailable'];
}

/** State-code join only: these source-scoped counts have no canonical person/geography IDs. */
export default function SenateMap({ data, selectedState, onSelect, onClear, raceState }: {
  data: SenateResults; selectedState: string; onSelect: (state: string) => void; onClear?: () => void; raceState?: string;
}) {
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
    return missing.has(feature.properties.state_code) ? 'Returns unavailable' : 'No Senate election in 2026';
  }
  const legend = [
    ['Democratic lead', partyPalette.Democratic], ['Republican lead', partyPalette.Republican],
    ['Other / independent lead', partyPalette['Other / independent']], ['Tie', tieColor],
    ['No determined leader', indeterminateColor],
    ['Returns unavailable', missingColor], ['No election', noElectionColor],
  ];
  return <section className="senate-map-panel" aria-label="Senate results map">
    {selectedState && !raceState && onClear && <div className="senate-map-actions"><button onClick={onClear}>Show all states</button></div>}
    {error ? <div className="notice" role="status"><p>The map could not load. State results remain available below.</p>
      <button onClick={() => setAttempt(value => value + 1)}>Retry map</button></div>
      : !outlines || !displayedOutlines ? <p role="status">Loading state map…</p> : <>
        <UnitedStatesMap<MapState> features={displayedOutlines} data={matched} title={raceState ? `${selected?.properties.name || raceState} 2026 Senate race map` : '2026 Senate results map'}
          selectedId={selected?.properties.geoid} focusSelection={false}
          water={raceState ? undefined : greatLakes as FeatureCollection<Polygon | MultiPolygon, { name: string }>}
          isInteractive={unit => !!unit?.race || !!unit?.missing}
          fill={unit => unit?.race ? senateRaceColor(unit.race) : unit?.missing ? missingColor : noElectionColor}
          describe={(unit, feature) => `${feature.properties.name}: ${unit?.race ? `${statusLabels[unit.race.status]}, ${number(unit.race.total_votes)} votes counted` : unavailable(feature)}`}
          tooltip={(unit, feature) => <SenatePopover race={unit?.race} name={feature.properties.name} missing={!!unit?.missing} />}
          onSelect={(_, feature) => onSelect(feature.properties.state_code)}
          attribution={<><a href={outlines.source.documentation_url}>Census 2024 state outlines</a> · Display geography, not 2026 election-day boundary certification{!raceState && <> · Water: <a href={greatLakes.source.documentation}>Natural Earth</a></>}</>} />
        <ul className="senate-map-legend" aria-label="Map legend">{(raceState ? legend.slice(0, 5) : legend).map(([label, fill]) =>
          <li key={label}><span style={{ background: fill }} />{label}</li>)}</ul>
        <p className="senate-map-note">Colors show the party ahead in the current vote count. Calls and certification are labeled separately; unreported or zero-vote counts have no determined leader.</p>
        {selectedState && !raceState && <p role="status">Showing {selected?.properties.name || selectedState} in the results below.</p>}
      </>}
  </section>;
}
