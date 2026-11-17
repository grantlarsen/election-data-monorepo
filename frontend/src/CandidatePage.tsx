import { useEffect, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router';
import { ApiError, fetchCandidate, sourceUrl } from './api';
import type { CandidateProfile } from './api';
import { FilterLink, Notice, SourceDetails } from './components';
import { CandidateElection } from './CandidateElection';
import { CandidateFinanceChart, DownloadFinance, financeRows } from './CandidateFinanceChart';
import { candidateDisplayName, candidateInitials, candidatePortrait, dollars } from './candidatePresentation';
import { humanize, isUuid } from './filters';
import './candidate-profile.css';
import { CandidateAvatar } from './CandidateAvatar';

export { dollars } from './candidatePresentation';

function FinanceAvailability({ finance }: { finance: CandidateProfile['finance'] }) {
  if (finance.status === 'available') return null;
  return <p className="profile-availability" role="status">{finance.status === 'ambiguous'
    ? 'Multiple candidate identifiers or source snapshots prevent a unique financial total.'
    : finance.status === 'identity_unresolved' ? 'Resolve the candidate identity before linking financial totals.'
    : finance.status === 'partial' ? 'Source totals or transfer information are incomplete.'
    : 'No sourced financial summary is available for this candidacy and cycle.'} Missing figures are not zero.</p>;
}

export function CandidatePage() {
  const { candidacyId = '' } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    if (location.search) navigate({ pathname: location.pathname, hash: location.hash }, { replace: true });
  }, [location.pathname, location.search, location.hash, navigate]);
  const invalid = !isUuid(candidacyId) ? 'The candidacy identifier must be a valid UUID.' : null;
  const [pagination, setPagination] = useState({ candidacyId, offset: 0 });
  const offset = pagination.candidacyId === candidacyId ? pagination.offset : 0;
  const queryString = offset ? `offset=${offset}` : '';
  const [attempt, setAttempt] = useState(0);
  const key = `${candidacyId}?${queryString}&attempt=${attempt}`;
  const [state, setState] = useState<{ key: string; profile?: CandidateProfile; error?: string; missing?: boolean }>({ key: '' });
  useEffect(() => {
    if (invalid) return;
    const controller = new AbortController();
    let current = true;
    fetchCandidate(candidacyId, queryString, controller.signal).then(profile => {
      if (current) setState({ key, profile });
    }).catch(error => {
      if (current && !controller.signal.aborted) setState({ key,
        error: error instanceof Error ? error.message : 'Unable to load candidate profile.',
        missing: error instanceof ApiError && error.status === 404 });
    });
    return () => { current = false; controller.abort(); };
  }, [candidacyId, queryString, invalid, key]);
  const profile = state.key === key ? state.profile : undefined;
  const error = state.key === key ? state.error : undefined;
  const name = candidateDisplayName(profile?.label || 'Candidate profile');
  useEffect(() => {
    if (profile) document.title = `${name} | Electoral Atlas`;
  }, [profile, name]);
  const title = <header className="page-heading"><p className="eyebrow">Candidate profile</p>
    <h1 id="page-title" tabIndex={-1}>{name}</h1></header>;
  if (invalid) return <>{title}<Notice title="Invalid selection" error><p>{invalid}</p></Notice></>;
  if (error) return <>{title}<Notice title={state.missing ? 'Candidate not found' : 'Profile could not be loaded'} error><p>{error}</p>
    {!state.missing && <button onClick={() => setAttempt(value => value + 1)}>Try again</button>}
    <FilterLink to="/candidates">Browse published candidate returns</FilterLink></Notice></>;
  if (!profile) return <>{title}<Notice title="Loading candidate profile"><p>Retrieving identity, election returns and source references.</p></Notice></>;
  const { contest, finance, results } = profile;
  const financeSourceUrl = finance.source ? sourceUrl(finance.source.url) : undefined;
  const portrait = candidatePortrait(profile);
  return <div className="candidate-profile">
    <header className="profile-hero">
      <div className="profile-inner">
        <div className="profile-hero-grid">
          <div className="profile-person">
            <CandidateAvatar className="profile-avatar" portrait={portrait} name={name}
              fallback={<span aria-hidden="true">{candidateInitials(name)}</span>} />
            <div className="profile-person-text"><p className="profile-kicker">{contest.office_name} · Candidate profile</p>
              <h1 id="page-title" tabIndex={-1}>{name}</h1>
              <p className="profile-geography">{contest.jurisdiction.name}</p>
              <p className="profile-person-status"><span className={`profile-status-dot ${profile.person ? 'is-resolved' : ''}`} aria-hidden="true" />
                {humanize(profile.identity_status)}<span aria-hidden="true">·</span>{humanize(contest.stage)} · {contest.election_date}</p>
            </div>
          </div>
          <section className="profile-headline" aria-label="Campaign finance headline totals">
            <p>Authorized campaign committees <span>· {finance.cycle} cycle</span></p>
            <dl>{[
              ['Total Raised', finance.total_raised], ['Total Spent', finance.total_spent], ['Cash on hand', finance.cash_on_hand],
            ].map(([label, amount]) => <div key={label}><dt>{label}</dt><dd>{dollars(amount)}</dd></div>)}</dl>
          </section>
        </div>
      </div>
    </header>

    <div className="profile-body profile-inner">
      <aside className="profile-sidebar"><p className="profile-nav-label">Sections</p>
        <nav aria-label="Candidate profile sections">
          <a className="profile-nav-summary" href="#election-results"><span aria-hidden="true">☆</span> Most recent election</a>
          <p className="profile-nav-group">Campaign finance</p>
          <a href="#campaign-finance"><span aria-hidden="true">$</span> Financial summary</a>
          <a href="#linked-committees"><span aria-hidden="true">▤</span> Linked committees</a>
          <p className="profile-nav-group">Candidate information</p>
          <a href="#profile-identity"><span aria-hidden="true">◇</span> Identity & sources</a>
        </nav>
        <p className="profile-sidebar-note">Follow the source.<br />Understand the numbers.</p>
      </aside>

      <div className="profile-content">
        <CandidateElection profile={profile} onResultsPageChange={offset => setPagination({ candidacyId, offset })} />

        <section id="campaign-finance" className="profile-finance" aria-labelledby="finance-heading">
          <div className="profile-data-controls"><div><span className="profile-control-label">Election cycle</span><strong className="profile-cycle-value">{finance.cycle}</strong></div>
            <div><span className="profile-control-label">Data displayed</span><span className="profile-scope"><span aria-hidden="true">✓</span> Authorized campaign committees</span></div>
          </div>
          <div className="profile-card profile-finance-card">
            <div className="profile-card-heading"><div><h2 id="finance-heading">Campaign finance</h2><p>FEC cycle {finance.cycle} · USD{finance.coverage_end ? ` · Through ${finance.coverage_end}` : ''}</p></div>
              <DownloadFinance finance={finance} /></div>
            <FinanceAvailability finance={finance} />
            <CandidateFinanceChart finance={finance} />
            <table className="profile-finance-table"><caption className="profile-visually-hidden">Financial summary amounts for the {finance.cycle} cycle</caption>
              <thead><tr><th scope="col">Category</th><th scope="col" className="number">Amount</th></tr></thead>
              <tbody>{financeRows(finance).map(row => <tr key={row.label}><th scope="row">{row.label}</th><td className="number">{dollars(row.amount)}</td></tr>)}</tbody>
            </table>
            {finance.source && <details className="profile-disclosure"><summary>Financial source & calculation details</summary>
              <dl className="profile-facts"><div><dt>Reported receipts</dt><dd>{dollars(finance.reported_receipts)}</dd></div><div><dt>Reported disbursements</dt><dd>{dollars(finance.reported_disbursements)}</dd></div>
                <div><dt>Transfers from authorized committees</dt><dd>{dollars(finance.transfers_from_authorized)}</dd></div><div><dt>Transfers to authorized committees</dt><dd>{dollars(finance.transfers_to_authorized)}</dd></div></dl>
              <p>{financeSourceUrl ? <a href={financeSourceUrl} target="_blank" rel="noreferrer">Federal Election Commission — source download</a> : 'Federal Election Commission'} · Version {finance.source.version}</p>
              <div className="profile-finance-note">
                <p>Through {finance.coverage_end || 'an unspecified coverage date'}. Coverage can differ between candidates.</p>
                <p>{finance.definition === 'reported_totals_less_authorized_transfers'
                  ? 'Total Raised and Total Spent are derived from reported receipts and disbursements, subtracting transfers from and to authorized committees because both transfer fields are positive, following FEC guidance.'
                  : 'Reported receipts and disbursements are source totals. They are not net contributions or independent expenditures.'}</p>
                <p>One candidate summary. Independent expenditures and leadership PAC activity are excluded.</p>
              </div>
            </details>}
          </div>
        </section>

        <section id="linked-committees" className="profile-card" aria-labelledby="committees-heading">
          <div className="profile-card-heading"><div><h2 id="committees-heading">Linked committees</h2><p>Source-backed relationships for the {finance.cycle} cycle.</p></div></div>
          {!profile.committees.length && <p className="profile-section-note">No source-backed committee link is available for this candidacy and cycle.</p>}
          {profile.committees.map((committee, index) => <article className="profile-committee" key={`${committee.id}:${index}`}>
            <p className="profile-kicker">{humanize(committee.role)} · Cycle {committee.cycle}</p><h3>{committee.name}</h3>
            <p>FEC IDs: {committee.fec_ids.join(', ') || 'Not recorded'}</p>
            <details className="profile-disclosure"><summary>Committee linkage evidence</summary>{committee.evidence && <p>{committee.evidence}</p>}
              {committee.source ? <SourceDetails source={committee.source} /> : <p>Source ID: {committee.source_id} · Release not recorded</p>}</details>
          </article>)}
        </section>

        <section id="profile-identity" className="profile-card" aria-labelledby="identity-heading">
          <div className="profile-card-heading"><div><h2 id="identity-heading">Identity & candidacy</h2><p>Source records, review evidence and methodology.</p></div><span className="profile-status-badge">{humanize(profile.identity_status)}</span></div>
          <p className="profile-section-note">A candidacy identifies a candidate in one contest. This profile follows the candidacy in the address; explorer filters do not change its election or financial cycle.</p>
          {!profile.person && <p className="profile-availability">This source label has not been linked to a verified person. Possible name matches remain review proposals.</p>}
          <details className="profile-disclosure"><summary>Record identifiers</summary><dl className="profile-facts"><div><dt>Candidacy ID</dt><dd>{profile.id}</dd></div><div><dt>Source label</dt><dd>{profile.source_label || 'Not supplied'}</dd></div>
            <div><dt>Person ID</dt><dd>{profile.person?.id || 'Unresolved'}</dd></div><div><dt>Candidate type</dt><dd>{humanize(profile.candidate_kind)}</dd></div></dl></details>
          {profile.identifiers.length > 0 && <details className="profile-disclosure"><summary>Official identifiers and sources</summary>{profile.identifiers.map(item => <div key={`${item.namespace}:${item.identifier_type}:${item.value}`}>
            <p>{item.namespace} {item.identifier_type}: <strong>{item.value}</strong></p>{item.evidence && <p>{item.evidence}</p>}
            {item.source ? <SourceDetails source={item.source} /> : <p>Source ID: {item.source_id} · Release not recorded</p>}</div>)}</details>}
          {profile.identity_evidence.length > 0 && <details className="profile-disclosure"><summary>Identity review evidence</summary>{profile.identity_evidence.map((item, index) => <div className="profile-evidence" key={index}>
            <p>{humanize(item.status)} · Match score {item.confidence} (rule score, not a probability)</p>
            <p>FEC candidate: {item.fec_candidate_id || 'No proposed match'} · Source record: {item.record_id || 'Not matched'}</p>
            {item.decision_evidence && <p>{item.decision_evidence}</p>}<pre>{JSON.stringify(item.evidence, null, 2)}</pre>
            <SourceDetails source={item.source} /></div>)}</details>}
          {portrait && <p className="profile-media-credit"><a href={sourceUrl(portrait.source)} target="_blank" rel="noreferrer">{portrait.credit}</a>
            {'license' in portrait && portrait.license && <> · <a href={sourceUrl(portrait.license_url || '')} target="_blank" rel="noreferrer">{portrait.license}</a></>}</p>}
        </section>
      </div>
    </div>
  </div>;
}
