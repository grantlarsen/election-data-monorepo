import { useEffect, useMemo, useState } from 'react';
import type { FeatureCollection, MultiPolygon, Polygon } from 'geojson';
import { UnitedStatesMap } from './geography/UnitedStatesMap';
import type { JurisdictionCollection, JurisdictionFeature } from './geography/unitedStates';
import { smallStates } from './geography/smallStates';
import greatLakes from './geography/data/great-lakes.json';
import { houseRaceTitle, houseStatuses, houseWinner } from './house';
import type { HouseRace, HouseResults } from './house';
import { HouseDistrictTile } from './HouseDistrictTile';
import { HousePopover } from './HousePopover';
import { partyPalette } from './map/electionColors';
import { sourceUrl } from './api';

export interface HouseBoundaries extends JurisdictionCollection {
  source: { year: number; boundary_vintage: string; documentation_url: string; display_sha256: string; reporting_levels: string[] };
}
type DistrictFeature = JurisdictionFeature & { properties: JurisdictionFeature['properties'] & { race_id: string | null } };
const raceId = (feature: JurisdictionFeature) => (feature as DistrictFeature).properties.race_id;
const missingColor = '#b6c1c8';
const uncalledColor = '#d6ddd9';

export function houseRaceColor(race?: HouseRace): string {
  if (!race) return missingColor;
  const winner = houseWinner(race);
  return !winner ? uncalledColor : partyPalette[winner.party === 'D' ? 'Democratic' : winner.party === 'R' ? 'Republican' : 'Other / independent'];
}

export async function fetchHouseBoundaries(signal: AbortSignal): Promise<HouseBoundaries> {
  const response = await fetch('/api/v1/house/2026/boundaries', { signal, headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error('House boundaries unavailable');
  const body: HouseBoundaries = await response.json();
  if (body?.type !== 'FeatureCollection' || body.source?.year !== 2026 || !body.source.reporting_levels?.includes('congressional_district') ||
      typeof body.source.boundary_vintage !== 'string' || !/^[a-f0-9]{64}$/.test(body.source.display_sha256) ||
      !sourceUrl(body.source.documentation_url) || !Array.isArray(body.features) || body.features.length !== 436 ||
      new Set(body.features.map(f => f.id)).size !== 436 ||
      body.features.some(f => !f.properties || f.id !== f.properties.geoid || !/^\d{4}$/.test(f.properties.geoid) ||
        !/^[A-Z]{2}$/.test(f.properties.state_code) || !['Polygon', 'MultiPolygon'].includes(f.geometry?.type) ||
        (f.properties.state_code === 'DC' ? f.id !== '1198' || raceId(f) !== null :
          raceId(f) !== `${f.properties.state_code}-${f.properties.geoid.slice(2) === '00' ? 'AL' : f.properties.geoid.slice(2)}`)) ||
      body.features.filter(f => f.properties.state_code === 'DC').length !== 1 ||
      new Set(body.features.map(raceId)).size !== 436) throw new Error('Invalid 2026 House boundaries');
  return body;
}

/** Election-scoped district join over verified 120th Congress display geometry. */
export default function HouseMap({ data, selectedState, selectedDistrict, onSelect }: {
  data: HouseResults; selectedState: string; selectedDistrict: string; onSelect: (race: HouseRace) => void;
}) {
  const [boundaries, setBoundaries] = useState<HouseBoundaries>();
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setError(false);
    fetchHouseBoundaries(controller.signal).then(body => { if (current) setBoundaries(body); })
      .catch(() => { if (current && !controller.signal.aborted) setError(true); });
    return () => { current = false; controller.abort(); };
  }, [attempt]);
  const byRace = useMemo(() => new Map(data.races.map(race => [race.id, race])), [data.races]);
  const matched = useMemo(() => new Map(boundaries?.features.map(feature => [feature.properties.geoid, byRace.get(raceId(feature) || '')])), [boundaries, byRace]);
  const displayed = useMemo(() => boundaries && selectedState && boundaries.features.some(f => f.properties.state_code === selectedState)
    ? { ...boundaries, features: boundaries.features.filter(f => f.properties.state_code === selectedState) } : boundaries, [boundaries, selectedState]);
  const selectedId = boundaries?.features.find(f => raceId(f) === selectedDistrict)?.properties.geoid;
  const missing = useMemo(() => new Set(data.missing_districts), [data.missing_districts]);
  return <div className="house-map-layout"><div className="house-geographic-map">
    {error ? <div className="notice" role="status"><p>The map could not load. Use the tile grid or district tables to explore results.</p>
      <button onClick={() => setAttempt(value => value + 1)}>Retry map</button></div> : !displayed ? <p role="status">Loading House district map…</p> :
      <UnitedStatesMap<HouseRace | undefined> features={displayed} data={matched} title="2026 House results map"
        selectedId={selectedId} focusSelection={false} isInteractive={race => !!race}
        water={selectedState ? undefined : greatLakes as FeatureCollection<Polygon | MultiPolygon, { name: string }>}
        fill={houseRaceColor}
        describe={(race, feature) => race ? `${houseRaceTitle(race)}: ${houseStatuses[race.status]}${houseWinner(race) ? `, ${houseWinner(race)!.name}` : ''}` :
          feature.properties.state_code === 'DC' ? 'DC: delegate outside voting-seat scope' : `${raceId(feature)}: district returns unavailable`}
        tooltip={(race, feature) => <HousePopover race={race} name={feature.properties.name} dc={feature.properties.state_code === 'DC'} />}
        onSelect={race => { if (race) onSelect(race); }}
        attribution={<><a href={sourceUrl(displayed.source.documentation_url)}>{displayed.source.boundary_vintage} · Census TIGER/Line</a> · Simplified display boundaries</>} />}
    <p className="senate-map-note">Colors show called winners, matching the tile grid. Gray districts remain uncalled; no vote leader is treated as a winner. Select a district to view its counts below.</p>
  </div><aside className="house-small-states" aria-label="Small states and DC House districts">
    {[...smallStates].map(code => <div key={code} className="house-small-state"><h3>{code}</h3><div className="house-seat-tiles">
      {code === 'DC' ? <span className="house-seat-missing" role="img" aria-label="DC: nonvoting delegate outside this feed" title="DC delegate results are outside this voting-seat feed">DC</span> :
        [...new Set([...data.races.filter(r => r.state_code === code).map(r => r.id), ...[...missing].filter(id => id.startsWith(`${code}-`))])].sort().map(id =>
          <HouseDistrictTile key={id} id={id} race={byRace.get(id)} selected={selectedDistrict === id} onSelect={onSelect} />)}
    </div></div>)}
    <p>One tile per district. DC’s delegate is outside the voting-seat count.</p>
  </aside></div>;
}
