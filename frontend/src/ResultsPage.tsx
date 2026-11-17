import { useParams, useSearchParams } from 'react-router';
import { CandidateLink } from './CandidateLink';
import type { Result } from './api';
import { apiQuery, humanize, isUuid, validateSearch } from './filters';
import { DataState, FilterLink, Pagination, Provenance, Title, Notice, usePage } from './components';

export function ResultsPage({ embedded = false, selection }: { embedded?: boolean; selection?: URLSearchParams }) {
  const { contestId } = useParams();
  const [urlParams] = useSearchParams();
  const params = selection ?? urlParams;
  const error = validateSearch(params) || (contestId && !isUuid(contestId) ? 'The contest identifier must be a valid UUID.' : null);
  const data = usePage<Result>('results', apiQuery(params, 'results', contestId), !error);
  return <>{embedded ? <h2>County returns</h2> : <Title title={contestId ? 'Contest returns' : 'Candidates & returns'}>Published returns at one reporting level. Each row belongs to a specific reporting unit.</Title>}
    {contestId && <div className="selection-context"><FilterLink to="/contests">← All contests</FilterLink><p>Contest ID: <code>{contestId}</code></p></div>}
    <p className="data-note">Showing {humanize(params.get('reporting_level') || 'county')} returns in TOTAL mode. State authority totals are a separate, non-additive source. No cross-geography totals are calculated here.</p>
    {error ? <Notice title="Review your filters" error><p>{error}</p></Notice> : <DataState {...data} empty="No published returns match this selection. A contest may exist without published results.">{page => {
      const publications = [...new Map(page.items.map(item => [item.publication.batch_id, item.publication])).values()];
      return <>
        <p className="result-count">{page.total.toLocaleString('en-US')} matching result records · candidate names can appear in multiple reporting units</p>
        <section className="source-panel" aria-labelledby="sources-heading"><h2 id="sources-heading">Sources on this page</h2><p>Coverage counts apply to entire publications. Separate pages can reflect newer publications if source pointers change.</p><Provenance publications={publications} /></section>
        <div className="table-scroll" tabIndex={0} role="region" aria-label="Published returns table"><table>
          <caption>Published {humanize(params.get('reporting_level') || 'county')} returns — individual reporting units</caption>
          <thead><tr><th scope="col">Candidate / source bucket</th><th scope="col">Contest & geography</th><th scope="col" className="number">Votes</th><th scope="col">Reference & lineage</th></tr></thead>
          <tbody>{page.items.map(item => {
            return <tr key={`${item.publication.batch_id}:${item.contest_id}:${item.jurisdiction.id}:${item.candidacy_id ?? item.observation_ids.join(',')}`}>
              <th scope="row">{item.candidacy_id ? <CandidateLink candidacyId={item.candidacy_id}>{item.label}</CandidateLink> : <>{item.label}<span className="cell-note">Anonymous {humanize(item.basis)} bucket · no person identity</span></>}<span className="cell-note">{humanize(item.basis)}</span></th>
              <td><FilterLink to={`/contests/${item.contest_id}`}>{item.office_name}</FilterLink><span className="cell-note">{item.election_date} · {humanize(item.stage)}</span><span className="cell-note">{item.jurisdiction.name} ({item.jurisdiction.state_code}) · {humanize(item.reporting_level)}</span></td>
              <td className="number">{item.votes.toLocaleString('en-US')}</td>
              <td><span>Reference vintage: {item.reference_vintage_start}–{item.reference_vintage_end}</span><span className="cell-note">Statistical reference; legal boundary dates may differ.</span>
                <details><summary>Record identifiers</summary><dl><dt>Geographic reference</dt><dd>{item.geographic_reference_id}</dd><dt>Jurisdiction</dt><dd>{item.jurisdiction.id}</dd><dt>Publication batch</dt><dd>{item.publication.batch_id}</dd><dt>Observations</dt><dd>{item.observation_ids.join(', ')}</dd>{item.correction_ids.length > 0 && <><dt>Corrections</dt><dd>{item.correction_ids.join(', ')}</dd></>}</dl></details>
              </td>
            </tr>;
          })}</tbody>
        </table></div>
        <Pagination page={page} />
      </>;
    }}</DataState>}
  </>;
}

