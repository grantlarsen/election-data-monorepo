import type { SenateRace, SenateResults } from './senate';
import StateResultsMap, { stateRaceColor } from './StateResultsMap';
import { SenatePopover } from './SenatePopover';

export const senateRaceColor = (race: SenateRace) => stateRaceColor(race);

export default function SenateMap(props: {
  data: SenateResults; selectedState: string; onSelect: (state: string) => void; onClear?: () => void; raceState?: string;
}) {
  return <StateResultsMap {...props} office="Senate"
    tooltip={(race, name, missing) => <SenatePopover race={race} name={name} missing={missing} />} />;
}
