import type { HouseBoundaries } from '../HouseMap';
import type { HouseResults } from '../house';
import states from '../geography/data/states.json';
import { snapshot } from './houseFixtures';

export function boundarySnapshot(data: HouseResults = snapshot()): HouseBoundaries {
  const geoids = new Map(states.features.map(f => [f.properties.state_code, f.properties.geoid]));
  return { type: 'FeatureCollection', source: { year: 2026, reporting_levels: ['congressional_district'],
    boundary_vintage: '120th Congress / 2026 election', display_sha256: 'b'.repeat(64),
    documentation_url: 'https://www.census.gov/geographies/mapping-files/2026/geo/tiger-line-file.html' },
    features: [...data.races.map(r => r.id), ...data.missing_districts, 'DC-98'].map(id => {
      const state = id.slice(0, 2);
      const geoid = geoids.get(state)! + (id.endsWith('-AL') ? '00' : id.slice(3));
      return { type: 'Feature' as const, id: geoid,
        geometry: { type: 'Polygon' as const, coordinates: [[[-101, 32], [-101, 33], [-100, 33], [-100, 32], [-101, 32]]] },
        properties: { geoid, state_code: state, name: id, race_id: state === 'DC' ? null : id } };
    }) };
}
