import type { ReactNode } from 'react';
import { Link, useInRouterContext } from 'react-router';

type Props = { candidacyId?: string | null; children: ReactNode };

/** Only explicit candidacy IDs become links; source names never imply identity. */
export function CandidateLink(props: Props) {
  const inRouter = useInRouterContext();
  if (!props.candidacyId) return <>{props.children}</>;
  const href = `/candidates/${encodeURIComponent(props.candidacyId)}`;
  if (inRouter) return <Link to={href}>{props.children}</Link>;
  // Geographic components can also be embedded outside the application router.
  return <a href={href}>{props.children}</a>;
}
