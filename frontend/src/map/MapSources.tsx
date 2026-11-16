import type { Publication } from "../api";
import { sourceUrl } from "../api";

/** Reader-facing source attribution; audit identifiers remain in the data API. */
export function MapSources({ publications }: { publications: Publication[] }) {
  return <ul className="map-source-list">{publications.map(publication => (
    <li key={publication.batch_id}>
      <a href={sourceUrl(publication.source.url)}>{publication.source.name.replace(/^medsl_/, "MEDSL ").replaceAll("_", " ")}</a>
      {" · "}Version {publication.source.version}
      {publication.correction_source && <> · Corrections: <a href={sourceUrl(publication.correction_source.url)}>{publication.correction_source.name.replaceAll("_", " ")}</a></>}
    </li>
  ))}</ul>;
}
