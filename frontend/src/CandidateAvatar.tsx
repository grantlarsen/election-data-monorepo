import { useState } from 'react';
import type { ReactNode } from 'react';
import type { CandidatePortrait } from './candidateMedia';
import './candidate-avatar.css';

/** Shared image failure handling preserves the existing initials/dot fallback. */
export function CandidateAvatar({ portrait, name, fallback, className = '', decorative = false }: {
  portrait?: CandidatePortrait; name: string; fallback: ReactNode; className?: string; decorative?: boolean;
}) {
  const [failedUrl, setFailedUrl] = useState<string>();
  const focus = portrait?.focus;
  const validFocus = focus && [focus.x, focus.y, focus.zoom].every(Number.isFinite)
    && focus.x >= 0 && focus.x <= 100 && focus.y >= 0 && focus.y <= 100 && focus.zoom >= 1 && focus.zoom <= 5;
  return <span className={`candidate-avatar ${className}`} aria-hidden={decorative || undefined}>
    {portrait && failedUrl !== portrait.url
      ? <img src={portrait.url} alt={decorative ? '' : `Portrait of ${name}`} title={`${portrait.credit}${portrait.license ? ` · ${portrait.license}` : ''}`} loading="lazy" decoding="async"
        style={validFocus ? { objectPosition: `${focus.x}% ${focus.y}%`, transformOrigin: `${focus.x}% ${focus.y}%`, transform: `scale(${focus.zoom})` } : undefined}
        onError={() => setFailedUrl(portrait.url)} />
      : fallback}
  </span>;
}
