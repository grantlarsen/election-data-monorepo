import type { SenateControl as Control } from './senate';

const change = (value: number) => value > 0 ? `+${value}` : String(value);
export function SenateControl({ control }: { control?: Control | null }) {
  if (!control) return <p role="status">Senate control data is unavailable.</p>;
  const c = control;
  const segments = [
    { seats: c.retained_democratic_aligned, name: 'Democratic-aligned seats not up for election', className: 'control-democratic control-retained' },
    { seats: c.called.D, name: 'Called Democratic election seats', className: 'control-democratic' },
    { seats: c.unresolved, name: 'Uncalled seats', className: 'control-uncalled' },
    { seats: c.other_unaligned, name: 'Independent or other election seats without a caucus assignment', className: 'control-other' },
    { seats: c.called.R, name: 'Called Republican election seats', className: 'control-republican' },
    { seats: c.retained.R, name: 'Republican seats not up for election', className: 'control-republican control-retained' },
  ];
  return <section className="senate-control" aria-label="Projected Senate control">
    <div className="control-totals"><div className="control-democratic-total"><strong>{c.democratic_aligned}</strong>
      {c.control === 'D' && <span className="control-check" aria-label="Projected Democratic-aligned majority">✓</span>}
      <span className="control-party">Democratic-aligned seats</span></div>
      <div className="control-republican-total"><strong>{c.totals.R}</strong>
        {c.control === 'R' && <span className="control-check" aria-label="Projected Republican majority">✓</span>}
        <span className="control-party">Republican seats</span></div></div>
    <div className="control-bar-wrap"><div className="control-half" aria-label="51 seats needed for majority">50<span>▼</span></div>
      <div className="control-bar" role="img" aria-label={`${c.democratic_aligned} Democratic-aligned seats, ${c.totals.R} Republican seats, ${c.other_unaligned} other seats, ${c.unresolved} uncalled. 51 seats needed for a majority.`}>
        {segments.filter(s => s.seats > 0).map(s => <span key={s.name} className={s.className} style={{ width: `${s.seats}%` }} title={`${s.seats} ${s.name}`} />)}
      </div>
      <div className="control-election-bracket" style={{ left: `${c.retained_democratic_aligned}%`, width: `${c.seats_up}%` }} aria-hidden="true" />
    </div>
    <div className="control-cohorts"><span>{c.retained_democratic_aligned} not up for election</span><span>{c.seats_up} up for election</span><span>{c.retained.R} not up for election</span></div>
    <div className="control-changes"><span>Flipped {c.gains.D} seats ({change(c.net_change.D)} net gain)</span><span>Flipped {c.gains.R} seats ({change(c.net_change.R)} net change)</span></div>
    <p className="control-context">Projected control · {c.totals.D} Democrats + {c.independent_democratic_caucus} independents caucusing with Democrats · {c.unresolved} uncalled
      {c.other_unaligned > 0 && ` · ${c.other_unaligned} independent/other seats without an assigned caucus`}. 51 seats needed for a majority.</p>
  </section>;
}
