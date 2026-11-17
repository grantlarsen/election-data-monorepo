import { houseParties, housePartyClass, houseRaceTitle, houseStatuses, houseWinner } from './house';
import type { HouseRace } from './house';

/** The grid and small-state inset share the same source-winner semantics. */
export function HouseDistrictTile({ race, id, selected, onSelect }: {
  race?: HouseRace; id: string; selected: boolean; onSelect: (race: HouseRace) => void;
}) {
  if (!race) return <span className="house-seat-missing" role="img" aria-label={`${id}: results unavailable`}
    title={`${id}: results unavailable`}>{id.slice(3)}</span>;
  const winner = houseWinner(race);
  const label = `${houseRaceTitle(race)}: ${winner ? `${winner.name}, ${houseParties[winner.party] || winner.party}, ${houseStatuses[race.status]}` : houseStatuses[race.status]}`;
  return <button className={housePartyClass(winner?.party)} aria-pressed={selected} aria-label={label}
    onClick={() => onSelect(race)} title={label}>{race.district_code === '00' ? 'AL' : Number(race.district_code)}</button>;
}
