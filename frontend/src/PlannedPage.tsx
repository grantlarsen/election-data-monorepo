import { Link } from 'react-router';
import { Title } from './components';

export function PlannedPage({ title, section }: { title:string; section?:string }) {
  return <><Title title={title}>{section ? `${section} · ` : ''}This page is planned for the Electoral Atlas.</Title>
    <section className="landing-placeholder"><p className="eyebrow">Coming soon</p>
      <h2>{section ? 'More ways to explore the data' : 'Every election has a story.'}</h2>
      <p>{section ? 'This dedicated page is on the project backlog. Explore the existing published records while it is being built.' : 'A new home for US election results, political profiles and campaign finance research is on the way.'}</p>
      <div className="placeholder-links"><Link to="/presidential/history">Explore presidential history →</Link><Link to="/map?year=2024">Open the election map →</Link><Link to="/contests">Browse contests →</Link></div>
    </section></>;
}
