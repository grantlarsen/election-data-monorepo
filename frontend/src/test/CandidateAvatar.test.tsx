import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CandidateAvatar } from '../CandidateAvatar';
import { cachedPortrait } from '../candidateMedia';
import { candidatePortrait } from '../candidatePresentation';
import { candidateProfile } from './fixtures';
import { portrait, portraitRace } from './portraitFixtures';

describe('reviewed candidate media', () => {
  it('falls back after image failure and tries a corrected image without losing attribution', () => {
    const view = render(<CandidateAvatar name="Example Candidate" portrait={portrait} fallback="EC" />);
    const image = screen.getByRole('img', { name: 'Portrait of Example Candidate' });
    expect(image).toHaveAttribute('src', portrait.url);
    expect(image).toHaveAttribute('title', 'Example photographer / Wikimedia Commons · CC BY 4.0');
    fireEvent.error(image);
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByText('EC')).toBeVisible();
    view.rerender(<CandidateAvatar name="Example Candidate" portrait={{ ...portrait, url: `/media/candidates/${'b'.repeat(64)}.jpg` }} fallback="EC" />);
    expect(screen.getByRole('img')).toBeVisible();
  });

  it('uses only the reviewed source candidacy ID without resolving person or finance identity', () => {
    const profile = { ...candidateProfile, provisional_election: { race: portraitRace, checked_at: '2026-11-17T12:00:00Z',
      retrieved_at: '2026-11-17T12:00:00Z', stale: false, sha256: 'f'.repeat(64) } };
    expect(profile.person).toBeNull();
    expect(candidatePortrait(profile)).toEqual(portrait);
    expect(candidatePortrait({ ...profile, id: 'different-id' })).toBeUndefined();
    expect(candidatePortrait({ ...profile, provisional_election: { ...profile.provisional_election,
      race: { ...portraitRace, candidates: [{ ...portraitRace.candidates[0], kind: 'aggregate' }] } } })).toBeUndefined();
    expect(profile.person).toBeNull();
  });

  it('rejects nonlocal or unsafe media and keeps a decorative fallback accessible through the candidate name', () => {
    expect(cachedPortrait({ ...portrait, url: 'https://elsewhere.example/photo.jpg' })).toBeUndefined();
    expect(cachedPortrait({ ...portrait, source: 'javascript:alert(1)' })).toBeUndefined();
    const { container } = render(<CandidateAvatar name="Example" fallback="EX" decorative />);
    expect(container.firstChild).toHaveAttribute('aria-hidden', 'true');
    expect(container.querySelector('img')).not.toBeInTheDocument();
  });
});
