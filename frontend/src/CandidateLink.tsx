import type { ReactNode } from 'react';
import { Link, useInRouterContext, useSearchParams } from 'react-router';
import { filterSearch } from './filters';

type Props = { candidacyId?: string | null; contestId?: string | null; search?: URLSearchParams; children: ReactNode };

function candidateHref(candidacyId: string, search?: URLSearchParams, contestId?: string | null) {
  const query = new URLSearchParams(search);
  if (contestId) query.set('contest_id', contestId);
  return `/candidates/${encodeURIComponent(candidacyId)}${query.size ? `?${query}` : ''}`;
}

function RoutedCandidateLink({ candidacyId, contestId, search, children }: Props & { candidacyId: string }) {
  const [params] = useSearchParams();
  return <Link to={candidateHref(candidacyId, search ?? new URLSearchParams(filterSearch(params).slice(1)), contestId)}>{children}</Link>;
}

/** Only explicit candidacy IDs become links; source names never imply identity. */
export function CandidateLink(props: Props) {
  const inRouter = useInRouterContext();
  if (!props.candidacyId) return <>{props.children}</>;
  if (inRouter) return <RoutedCandidateLink {...props} candidacyId={props.candidacyId} />;
  // Geographic components can also be embedded outside the application router.
  return <a href={candidateHref(props.candidacyId, props.search, props.contestId)}>{props.children}</a>;
}
