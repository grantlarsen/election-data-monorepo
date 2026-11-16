import type { Publication, Source } from './api';
import { sourceUrl } from './api';

function sourceName(name: string): string {
  if (name.startsWith('medsl_')) return 'MIT Election Data and Science Lab';
  if (name.startsWith('fec_')) return 'Federal Election Commission';
  if (name.includes('county_correction')) return 'Reviewed election corrections';
  return name.replaceAll('_', ' ');
}

/** Reader-facing citations; full record lineage remains in the API. */
export function ElectionSourceDetails({ publications }: { publications: Publication[] }) {
  const sources = [...new Map(publications.flatMap(publication => [publication.source, publication.correction_source]
    .filter((source): source is Source => !!source)).map(source => [source.release_id, source])).values()];
  const partial = publications.some(publication => publication.status === 'PARTIAL');
  const unverifiedCounties = publications.some(publication => publication.reporting_levels.includes('county') && !publication.county_coverage_verified);
  return <details className="profile-disclosure profile-election-sources"><summary>Source and publication details</summary>
    {sources.length ? <div className="profile-source-heading"><div>{sources.map(source => {
      const url = sourceUrl(source.url);
      return <p key={source.release_id}>{url ? <a href={url} target="_blank" rel="noreferrer">{sourceName(source.name)}</a> : sourceName(source.name)} · Version {source.version}</p>;
    })}</div><span className={`badge${partial ? ' badge-partial' : ''}`}>{partial ? 'Partial publication' : 'Complete publication'}</span></div>
      : <p>No published source is available.</p>}
    {partial && <p className="coverage-warning">Coverage is incomplete. Missing returns are not zero votes.</p>}
    {unverifiedCounties && <p className="coverage-warning">County coverage has not been independently verified.</p>}
    <p className="profile-source-method">Shares are based on reported votes.</p>
  </details>;
}
