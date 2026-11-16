import type { CandidateProfile } from './api';
import ocasioCortezPortrait from './assets/people/alexandria-ocasio-cortez.jpg';

/** Display formatting only; canonical and source names remain unchanged. */
export function candidateDisplayName(value: string): string {
  const parts = value.split(',');
  const name = parts.length === 2 ? `${parts[1].trim()} ${parts[0].trim()}` : value;
  return name === name.toUpperCase()
    ? name.toLocaleLowerCase('en-US').replace(/\b\p{L}/gu, letter => letter.toLocaleUpperCase('en-US'))
    : name;
}

export function candidateInitials(name: string): string {
  const words = name.trim().split(/\s+/);
  return [words[0]?.[0], words.length > 1 ? words.at(-1)?.[0] : ''].join('').toUpperCase();
}

/** Curated media from the supplied reference; IDs, never names, select a portrait. */
const portraits: Record<string, { url: string; credit: string; source: string }> = {
  H8NY15148: {
    url: ocasioCortezPortrait,
    credit: 'Portrait from the user-supplied OpenSecrets reference.',
    source: 'https://www.opensecrets.org/profiles/alexandria-ocasio-cortez/us_congress/summary?cycle=2024&mpid=1043803',
  },
};

export function candidatePortrait(profile: CandidateProfile) {
  if (!profile.person || profile.identity_status !== 'resolved') return undefined;
  const id = profile.finance.fec_candidate_id;
  return id ? portraits[id] : undefined;
}

/** Currency never passes through floating point, preserving the API's exact cents. */
export function dollars(value: string | null): string {
  if (value === null) return 'Not available';
  const parts = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(value);
  if (!parts) return 'Not available';
  return `${parts[1]}$${parts[2].replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${(parts[3] || '').padEnd(2, '0')}`;
}
