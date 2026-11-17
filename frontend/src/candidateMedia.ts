import { sourceUrl } from './api';

export interface CandidatePortrait {
  focus?: { x: number; y: number; zoom: number } | null;
  url: string;
  credit: string;
  source: string;
  license?: string;
  license_url?: string;
  sha256?: string;
}

/** Reviewed API media uses only our checksum-named local raster cache. */
export function cachedPortrait(portrait?: CandidatePortrait | null): CandidatePortrait | undefined {
  return portrait && /^\/media\/candidates\/[a-f0-9]{64}\.(jpg|png|webp)$/.test(portrait.url)
    && sourceUrl(portrait.source)?.startsWith('https://') && portrait.credit ? portrait : undefined;
}
