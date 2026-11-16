import type { CandidateProfile } from './api';
import { dollars } from './candidatePresentation';

type Finance = CandidateProfile['finance'];

export function financeRows(finance: Finance) {
  return [
    { label: 'Raised', amount: finance.total_raised },
    { label: 'Spent', amount: finance.total_spent },
    { label: 'Cash on hand', amount: finance.cash_on_hand },
    { label: 'Debts', amount: finance.debts },
  ];
}

function tick(value: number): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD',
    notation: 'compact', maximumFractionDigits: 2 }).format(value);
}

export function financeCsv(finance: Finance): string {
  const records = [
    ['Category', 'Amount', 'Currency', 'Cycle', 'Coverage end', 'FEC candidate ID', 'Definition', 'Source release', 'SHA-256'],
    ...financeRows(finance).map(row => [row.label, row.amount ?? '', 'USD', String(finance.cycle),
      finance.coverage_end ?? '', finance.fec_candidate_id ?? '', finance.definition ?? '',
      finance.source?.release_id ?? '', finance.source?.sha256 ?? '']),
  ];
  return records.map(row => row.map(cell => `"${cell.replaceAll('"', '""')}"`).join(',')).join('\r\n');
}

export function DownloadFinance({ finance }: { finance: Finance }) {
  function download() {
    const url = URL.createObjectURL(new Blob([financeCsv(finance)], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `candidate-finance-${finance.cycle}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }
  return <button className="profile-icon-button" onClick={download} aria-label="Download financial summary as CSV" title="Download CSV">
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4" /></svg>
  </button>;
}

export function CandidateFinanceChart({ finance }: { finance: Finance }) {
  const rows = financeRows(finance);
  // Numbers determine geometry only. All displayed/exported values use exact strings.
  const known = rows.flatMap(row => row.amount !== null && Number.isFinite(Number(row.amount)) ? [Number(row.amount)] : []);
  if (!known.length) return <p className="profile-chart-empty">The chart will appear when a sourced financial summary is available.</p>;
  const minimum = Math.min(0, ...known);
  const maximum = Math.max(0, ...known);
  const range = maximum - minimum || 1;
  const zero = -minimum / range * 100;
  return <figure className="profile-chart" aria-label="Campaign finance comparison">
    <figcaption><span className="profile-chart-dot" aria-hidden="true" />Authorized campaign committees · USD</figcaption>
    <div className="profile-chart-rows">{rows.map(row => {
      const value = row.amount !== null && Number.isFinite(Number(row.amount)) ? Number(row.amount) : null;
      return <div className="profile-chart-row" key={row.label}>
        <span className="profile-chart-label">{row.label}</span>
        <div className="profile-chart-track" style={{ backgroundPosition: `${zero}% 0` }}>
          {value === null ? <span className="profile-chart-missing">Not available</span> : <span className="profile-chart-bar" style={{
            left: `${value < 0 ? (value - minimum) / range * 100 : zero}%`, width: `${Math.abs(value) / range * 100}%`,
          }} aria-hidden="true" />}
        </div>
        <span className="profile-chart-value">{dollars(row.amount)}</span>
      </div>;
    })}</div>
    <div className="profile-chart-axis" aria-hidden="true"><span>{tick(minimum)}</span><span>{tick(maximum / 2 + minimum / 2)}</span><span>{tick(maximum)}</span></div>
  </figure>;
}
