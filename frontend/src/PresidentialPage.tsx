import { useEffect, useState } from 'react';
import { Link, Navigate, useParams, useSearchParams } from 'react-router';
import { ApiError, fetchPresidentialCoverage } from './api';
import type { PresidentialCoverage, StateResult } from './api';
import { DataState, Notice, Pagination, Provenance, Title, usePage } from './components';
import { apiQuery, humanize, validateSearch } from './filters';
import { presidentialParams, presidentialYears } from './presidential';
import { ResultsPage } from './ResultsPage';
import './presidential.css';
import { ElectoralCollegeCounter } from './map/ElectoralCollege';

function YearLinks({ year, params = new URLSearchParams() }: { year?: number; params?: URLSearchParams }) {
  return <nav className="presidential-years" aria-label="Presidential election years">{presidentialYears.map(value => {
    const next = new URLSearchParams();
    if (params.get('state_code')) next.set('state_code', params.get('state_code')!);
    if (params.get('reporting_level')) next.set('reporting_level', params.get('reporting_level')!);
    return <Link key={value} aria-current={value === year ? 'page' : undefined}
      to={`/presidential/${value}?${presidentialParams(value, next)}`}>{value}</Link>;
  })}</nav>;
}

export function PresidentialDiscovery() {
  return <><Title title="Presidential elections">Explore the 2000–2024 general elections. Each year has its own published sources, county coverage and historical geography.</Title>
    <YearLinks />
    <p className="data-note">State authority totals and county returns are separate, non-additive sources. County coverage is partial; absent records do not mean zero votes.</p>
    <p>Choose a year to browse state totals, drill into county returns, and open its election map. Maps display shapes only when compatible boundaries are available.</p>
  </>;
}

/** Route context wins over inherited House/year filters before any data request. */
export function PresidentialPage() {
  const { year: value } = useParams();
  const [params] = useSearchParams();
  const year = presidentialYears.find(year => String(year) === value);
  if (!year) return <><Title title="Presidential election not available">Choose a supported general election from 2000 through 2024.</Title><YearLinks /></>;
  const next = presidentialParams(year, params);
  if (next.toString() !== params.toString()) return <Navigate replace to={`/presidential/${year}?${next}`} />;
  const validation = new URLSearchParams(params);
  validation.delete('reporting_level');
  const error = validateSearch(validation) ||
    (params.getAll('reporting_level').length !== 1 || !['state', 'county'].includes(params.get('reporting_level')!)
      ? 'Choose state totals or county returns for a presidential election.' : null);
  return <><Title title={`${year} presidential election`}>Published popular-vote returns for the presidential general election. Each reporting level retains its own source and coverage.</Title>
    <YearLinks year={year} params={params} />
    {error ? <Notice title="Review your filters" error><p>{error}</p></Notice> : <PresidentialElection key={year} year={year} params={params} />}
  </>;
}

function target(year: number, params: URLSearchParams, level: string, state?: string) {
  const next = new URLSearchParams(params);
  next.set('reporting_level', level);
  next.delete('offset');
  next.delete('jurisdiction_id');
  if (state) next.set('state_code', state);
  return `/presidential/${year}?${presidentialParams(year, next)}`;
}

function PresidentialElection({ year, params }: { year: number; params: URLSearchParams }) {
  const level = params.get('reporting_level')!;
  const map = new URLSearchParams({ year: String(year), office: 'U.S. President', stage: 'general' });
  if (params.get('state_code')) {
    map.set('state_code', params.get('state_code')!.toUpperCase());
    map.set('reporting_level', 'county');
  }
  return <>
    <ElectoralCollegeCounter year={year} />
    <nav className="presidential-views" aria-label="Presidential reporting views">
      <Link to={target(year, params, 'state')} aria-current={level === 'state' ? 'page' : undefined}>State totals</Link>
      <Link to={target(year, params, 'county')} aria-current={level === 'county' ? 'page' : undefined}>County returns</Link>
      <Link to={`/map?${map}`}>Open election map</Link>
    </nav>
    <p className="data-note">State authority totals and county returns must not be added together. Missing returns are not zero votes. Maps use this election's compatible boundaries; unavailable shapes never borrow another year's geography.</p>
    <CoveragePanel year={year} params={params} />
    {level === 'county' ? <ResultsPage embedded selection={params} /> : <StateReturns year={year} params={params} />}
  </>;
}

function StateReturns({ year, params }: { year: number; params: URLSearchParams }) {
  const data = usePage<StateResult>('state-results', apiQuery(params, 'contests'));
  return <section aria-labelledby="state-returns-heading"><h2 id="state-returns-heading">State authority totals</h2>
    <p>Source candidate buckets are not canonical person identities. OTHER groups the remaining reported votes, including write-ins. Select a state to browse its separate county returns.</p>
    <DataState {...data} empty="No published state totals match this election and geography.">{page => <>
      <p className="result-count">{page.total.toLocaleString('en-US')} matching state result records</p>
      <section className="source-panel" aria-labelledby="state-sources-heading"><h3 id="state-sources-heading">State sources on this page</h3>
        <Provenance publications={[...new Map(page.items.map(item => [item.publication.batch_id, item.publication])).values()]} />
      </section>
      <div className="table-scroll" tabIndex={0} role="region" aria-label="State totals table"><table>
        <caption>{year} presidential state totals — individual reporting units</caption>
        <thead><tr><th scope="col">State / county drill-down</th><th scope="col">Source candidate bucket</th><th scope="col" className="number">Votes</th><th scope="col">Source reference</th></tr></thead>
        <tbody>{page.items.map(item => <tr key={`${item.publication.batch_id}:${item.jurisdiction.id}:${item.candidate_bucket}`}>
          <th scope="row"><Link to={target(year, params, 'county', item.jurisdiction.state_code!)}>{item.jurisdiction.name}</Link></th>
          <td>{item.candidate_bucket}<span className="cell-note">{humanize(item.bucket_kind)} · no canonical person link</span></td>
          <td className="number">{item.votes.toLocaleString('en-US')}</td><td>{item.source_locator}<span className="cell-note">{item.election_date}</span></td>
        </tr>)}</tbody>
      </table></div><Pagination page={page} />
    </>}</DataState>
  </section>;
}

function CoveragePanel({ year, params }: { year: number; params: URLSearchParams }) {
  const [attempt, setAttempt] = useState(0);
  const key = `${year}:${attempt}`;
  const [state, setState] = useState<{ key: string; items?: PresidentialCoverage[]; error?: string }>({ key: '' });
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    fetchPresidentialCoverage(controller.signal).then(items => {
      if (current) setState({ key, items });
    }).catch(error => {
      if (current && !controller.signal.aborted) setState({ key, error: error instanceof ApiError
        ? error.message : 'Unable to load presidential coverage. Check your connection and try again.' });
    });
    return () => { current = false; controller.abort(); };
  }, [key]);
  if (state.key !== key) return <Notice title="Loading election coverage"><p>Retrieving source and county coverage limitations.</p></Notice>;
  if (state.error) return <Notice title="Coverage could not be loaded" error><p>{state.error}</p><button onClick={() => setAttempt(value => value + 1)}>Retry coverage</button></Notice>;
  const coverage = state.items?.find(item => item.year === year);
  if (!coverage) return <Notice title="Coverage not available"><p>No coverage inventory is available for this year. Available returns below do not establish complete coverage.</p></Notice>;
  const selectedState = params.get('state_code')?.toUpperCase();
  const states = coverage.states.filter(state => !selectedState || state.state_code === selectedState);
  const exclusions = coverage.county.exclusions.filter(item => !selectedState || item.state_code === selectedState);
  return <section className="presidential-coverage" aria-labelledby="coverage-heading">
    <h2 id="coverage-heading">Election coverage · {coverage.election_date}</h2>
    <p>State totals: {coverage.state.availability === 'published' ? 'published' : 'no publication'}. County returns: {coverage.county.availability === 'published'
      ? `${coverage.county.status === 'PARTIAL' ? 'partial' : 'complete'} publication` : 'no publication'}.</p>
    {!coverage.county_coverage_verified && <p className="coverage-warning">County coverage has not been independently verified. Missing returns are not zero votes.</p>}
    {coverage.county.availability === 'published' && !coverage.county.matches_active_source && <p className="coverage-warning">The county publication differs from the active source release. Published returns retain their original source.</p>}
    {coverage.limitations.map(note => <p className="coverage-warning" key={note}>{note}</p>)}
    <details><summary>County gaps and state comparison</summary>
      <p>Publication-wide counts: {coverage.county.accepted_rows.toLocaleString('en-US')} accepted rows; {coverage.county.excluded_rows?.toLocaleString('en-US') ?? 'unavailable'} excluded rows. These counts cover all states and are not vote totals.</p>
      <p>States without published county returns: {coverage.county.missing_states.join(', ') || 'None'}. Published county rows do not establish complete coverage within a state.</p>
      <p>Official minus county differences combine coverage gaps and source disagreements. They are not county estimates or allocations. Unavailable county votes remain unavailable even when a signed difference is reported.</p>
      <div className="table-scroll" tabIndex={0} role="region" aria-label="State and county coverage comparison"><table>
        <caption>{year} state and county coverage{selectedState ? ` · ${selectedState}` : ''}</caption>
        <thead><tr><th scope="col">State</th><th scope="col" className="number">Official state votes</th><th scope="col" className="number">Published county votes</th><th scope="col" className="number">Official minus county votes</th></tr></thead>
        <tbody>{states.map(state => <tr key={state.state_code}><th scope="row"><Link to={target(year, params, 'county', state.state_code)}>{state.state_code}</Link></th>
          <td className="number">{state.official_votes?.toLocaleString('en-US') ?? 'Unavailable'}</td>
          <td className="number">{state.county?.votes.toLocaleString('en-US') ?? 'Unavailable'}</td>
          <td className="number">{state.state_minus_published_county_votes?.toLocaleString('en-US') ?? 'Unavailable'}</td></tr>)}</tbody>
      </table></div>
      {exclusions.length > 0 && <><h3>Excluded county observations{selectedState ? ` · ${selectedState}` : ''}</h3><ul>{exclusions.map(item => <li key={`${item.state_code}:${item.code}`}>{item.state_code} · {humanize(item.code)}: {item.rows.toLocaleString('en-US')} rows</li>)}</ul></>}
      {coverage.county.source_release_id && <p>County source release: <code>{coverage.county.source_release_id}</code></p>}
    </details>
  </section>;
}
