import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation, useNavigate } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { ElectionMapPage } from "../map/ElectionMapPage";
import type { ElectionMap, MapUnit } from "../map/types";
import {
  candidacyId,
  contestId,
  jurisdictionId,
  publication,
} from "./fixtures";

vi.mock("../map/GeographyMap", () => ({
  GeographyMap: ({
    data,
    onSelect,
  }: {
    data: ElectionMap;
    onSelect: (unit: MapUnit) => void;
  }) => (
    <div aria-label="Test map renderer">
      {data.units.map((unit) => (
        <button key={unit.id} onClick={() => onSelect(unit)}>
          Map select {unit.name}
        </button>
      ))}
    </div>
  ),
}));

const county: MapUnit = {
  id: "36001",
  geoid: "36001",
  name: "Albany County",
  state_code: "NY",
  jurisdiction_id: jurisdictionId,
  contest_id: contestId,
  publication_batch_id: publication.batch_id,
  has_geometry: true,
  summary: {
    status: "available",
    total_votes: 100,
    leader: "BARACK OBAMA",
    margin_votes: 30,
    margin_pp: 30,
    candidates: [
      {
        label: "BARACK OBAMA",
        party_labels: ['DEMOCRATIC'],
        kind: "candidate",
        votes: 60,
        share: 60,
        candidacy_id: candidacyId,
        geographic_reference_id: jurisdictionId,
        observation_ids: [jurisdictionId],
        correction_ids: [],
      },
      {
        label: "JOHN MCCAIN",
        party_labels: ['REPUBLICAN'],
        kind: "candidate",
        votes: 30,
        share: 30,
        candidacy_id: contestId,
        geographic_reference_id: jurisdictionId,
        observation_ids: [contestId],
        correction_ids: [],
      },
      {
        label: "OTHER",
        kind: "aggregate",
        votes: 10,
        share: 10,
        candidacy_id: null,
        geographic_reference_id: jurisdictionId,
        observation_ids: [contestId],
        correction_ids: [contestId],
      },
    ],
  },
};
function dataset(counties = false): ElectionMap {
  const units = counties
    ? [county]
    : [{ ...county, id: "36", geoid: "36", name: "New York" }];
  return {
    year: 2008,
    office: "U.S. President",
    stage: "general",
    reporting_level: counties ? "county" : "state",
    drill_down_level: counties ? null : "county",
    state_code: counties ? "NY" : null,
    selected_jurisdiction_id: null,
    availability: "available",
    boundary: null,
    features: {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          id: units[0].id,
          properties: {
            geoid: units[0].id,
            state_code: "NY",
            name: units[0].name,
          },
          geometry: { type: "Polygon", coordinates: [] },
        },
      ],
    },
    units,
    publications: [publication],
    coverage: {
      boundary_units: 1,
      units_with_results: 1,
      missing_results: 0,
      results_without_geometry: 0,
    },
    metric_note:
      "Shares include all published buckets. No turnout is calculated.",
    source_note:
      "FEC states and canonical counties are separate non-additive sources.",
  };
}
function respond(data: unknown, status = 200) {
  return { ok: status === 200, status, json: async () => data } as Response;
}
function Probe() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <p data-testid="location">
        {location.pathname}
        {location.search}
      </p>
      <button onClick={() => navigate(-1)}>Back</button>
    </>
  );
}
function open(path = "/map?year=2008") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ElectionMapPage />
      <Probe />
    </MemoryRouter>,
  );
}
function mockMap() {
  const fetch = vi.fn(async (url: string) =>
    respond(dataset(url.includes("state_code=NY"))),
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

describe("election map display", () => {
  it("places the interactive map before the independently loading statewide summary", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) =>
      url.includes("reporting_level=state")
        ? new Promise<Response>(() => {})
        : respond(dataset(true)),
    ));
    open("/map?year=2008&state_code=NY&reporting_level=county");
    const map = await screen.findByLabelText("Test map renderer");
    const summary = screen.getByRole("region", { name: "NY statewide summary" });
    expect(map.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(summary).getByRole("status")).toHaveTextContent("Loading statewide results");
    expect(within(map).getByRole("button", { name: "Map select Albany County" })).toBeEnabled();
  });

  it("preserves a federal district election and shows a compact party legend", async () => {
    const data = dataset(true);
    Object.assign(data, {
      year: 2024,
      office: "U.S. House",
      stage: "primary",
      reporting_level: "congressional_district",
    });
    data.units = [
      {
        ...county,
        id: "3601",
        geoid: "3601",
        name: "District 1",
        summary: {
          ...county.summary,
          leader: "Example federal candidate",
          candidates: county.summary.candidates.map((candidate, index) => ({
            ...candidate,
            label:
              index === 0
                ? "Example federal candidate"
                : index === 1
                  ? "Another federal candidate"
                  : "OTHER",
          })),
        },
      },
    ];
    const fetch = vi.fn(async (_url: string) => respond(data));
    vi.stubGlobal("fetch", fetch);
    const user = userEvent.setup();
    open(
      "/map?year=2024&office=U.S.+House&stage=primary&state_code=NY&reporting_level=congressional_district",
    );
    await screen.findByRole("heading", {
      name: "NY · Congressional district returns",
    });
    expect(screen.getByLabelText("Map legend")).toHaveTextContent(
      "Democratic",
    );
    expect(screen.getByLabelText("Map legend")).not.toHaveTextContent("Obama");
    await user.click(screen.getByRole("button", { name: "District 1" }));
    await screen.findByRole("heading", {
      name: "District 1 · Published returns",
    });
    const query = new URLSearchParams(
      fetch.mock.calls.at(-1)![0].split("?")[1],
    );
    expect(query.get("year")).toBe("2024");
    expect(query.get("office")).toBe("U.S. House");
    expect(query.get("stage")).toBe("primary");
    expect(query.get("reporting_level")).toBe("congressional_district");
    expect(screen.getByTestId("location")).toHaveTextContent("map_unit=3601");
  });
  it("shows API votes, shares, percentage-point margins and source coverage", async () => {
    mockMap();
    open();
    const table = await screen.findByRole("table");
    expect(within(table).getByText("60 · 60.00%")).toBeVisible();
    expect(within(table).getByText("10 · 10.00%")).toBeVisible();
    expect(within(table).getByText("30.00% · 30 votes")).toBeVisible();
    expect(screen.getByLabelText("Map legend")).toHaveTextContent(
      "No published returns",
    );
    const legend = screen.getByRole('list', { name: 'Map legend' });
    expect(within(legend).getByText('BARACK OBAMA').closest('li')!.querySelector('span')).toHaveStyle({ background:'#3276ac' });
    expect(within(legend).getByText('JOHN MCCAIN').closest('li')!.querySelector('span')).toHaveStyle({ background:'#bd5548' });
    await userEvent.click(screen.getByText("Sources & notes"));
    expect(screen.getByText(/non-additive sources/)).toBeVisible();
    expect(screen.getAllByText("Partial publication").length).toBeGreaterThan(
      0,
    );
    expect(screen.queryByText(/turnout:/i)).not.toBeInTheDocument();
  });

  it("drills through the map, selects a county, and restores state/nation through history", async () => {
    const fetch = mockMap();
    const user = userEvent.setup();
    open();
    await user.click(
      await screen.findByRole("button", { name: "Map select New York" }),
    );
    await screen.findByRole("heading", { name: "NY · County returns" });
    expect(fetch.mock.calls.at(-1)![0]).toContain("state_code=NY");
    await user.click(
      await screen.findByRole("button", { name: "Map select Albany County" }),
    );
    await screen.findByRole("heading", {
      name: "Albany County · Published returns",
    });
    expect(screen.getByTestId("location")).toHaveTextContent(
      `jurisdiction_id=${jurisdictionId}`,
    );
    expect(within(screen.getByRole('table', { name: 'Candidate votes and share of reported votes' })).getByRole("link", { name: "BARACK OBAMA" })).toHaveAttribute(
      "href",
      expect.stringContaining(`/candidates/${candidacyId}?`),
    );
    expect(screen.queryByText("Reporting unit lineage")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Election map results table")).not.toBeInTheDocument();
    expect(screen.queryByText(/GEOID/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", {
          name: "Albany County · Published returns",
        }),
      ).not.toBeInTheDocument(),
    );
    await user.click(screen.getByRole("link", { name: "United States" }));
    await screen.findByRole("heading", {
      name: "United States · State returns",
    });
    expect(screen.getByTestId("location")).not.toHaveTextContent("state_code");
  });

  it("supports keyboard table drill-down and a directly reloaded county selection", async () => {
    mockMap();
    const user = userEvent.setup();
    open(`/map?year=2008&state_code=NY&jurisdiction_id=${jurisdictionId}`);
    await screen.findByRole("heading", {
      name: "Albany County · Published returns",
    });
    const button = screen.getByRole("button", { name: "Map select Albany County" });
    button.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByTestId("location")).toHaveTextContent("map_unit=36001");
  });

  it("keeps missing returns, stored zero totals and unmatched geometry visible", async () => {
    const data = dataset(true);
    data.units = [
      {
        ...county,
        has_geometry: false,
        summary: {
          ...county.summary,
          status: "zero_total",
          total_votes: 0,
          leader: null,
          margin_pp: null,
          margin_votes: null,
          candidates: [
            { ...county.summary.candidates[0], votes: 0, share: null },
          ],
        },
      },
      {
        ...county,
        id: "36003",
        geoid: "36003",
        name: "Missing County",
        jurisdiction_id: null,
        summary: {
          status: "no_results",
          total_votes: null,
          leader: null,
          margin_pp: null,
          margin_votes: null,
          candidates: [],
        },
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => respond(data)),
    );
    const user = userEvent.setup();
    open("/map?year=2008&state_code=NY");
    const table = await screen.findByRole("table");
    expect(within(table).getByText("0")).toBeVisible();
    expect(within(table).getByText("No matching geometry")).toBeVisible();
    expect(within(table).getByText("No published returns")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Missing County" }));
    expect(
      await screen.findByText(
        "No published returns for this area.",
      ),
    ).toBeVisible();
    expect(screen.getByTestId("location")).toHaveTextContent("map_unit=36003");
  });

  it("sorts units by votes while keeping null values last", async () => {
    const data = dataset(true);
    data.units.push({
      ...county,
      id: "36003",
      name: "Z County",
      summary: { ...county.summary, total_votes: 1000 },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => respond(data)),
    );
    const user = userEvent.setup();
    open("/map?state_code=NY");
    await screen.findByRole("table");
    await user.selectOptions(screen.getByLabelText("Sort units"), "votes");
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("Z County");
  });

  it("announces unavailable boundaries while retaining published results", async () => {
    const data = dataset();
    data.availability = "boundaries_unavailable";
    data.features.features = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => respond(data)),
    );
    open();
    expect(
      await screen.findByRole("heading", {
        name: "Map boundaries are not available yet",
      }),
    ).toBeVisible();
    expect(screen.getByRole("table")).toHaveTextContent("New York");
  });

  it.each([2000, 2004, 2012, 2016, 2020, 2024])('retains %s when drilling from the national county URL into a state', async year => {
    const fetch = vi.fn(async (url: string) => {
      const query = new URLSearchParams(url.split('?')[1]);
      const data = dataset(query.has('state_code') && query.get('reporting_level') !== 'state');
      data.year = Number(query.get('year'));
      return respond(data);
    });
    vi.stubGlobal('fetch', fetch);
    const user = userEvent.setup();
    open(`/map?year=${year}&office=U.S.+President&stage=general&reporting_level=county`);
    expect(screen.getByText('Choose a state on the map to view its county returns.')).toBeVisible();
    await user.click(await screen.findByRole('button', { name: 'Map select New York' }));
    await screen.findByRole('heading', { name: 'NY · County returns' });
    expect(screen.getByTestId('location')).toHaveTextContent(`year=${year}`);
    const queries = fetch.mock.calls.map(([url]) => new URLSearchParams(url.split('?')[1]));
    expect(queries.every(query => query.get('year') === String(year))).toBe(true);
    expect(queries.some(query => query.get('state_code') === 'NY' && query.get('reporting_level') === 'county')).toBe(true);
  });

  it('shows a prominent explanation when the boundary package uses an historical display approximation', async () => {
    const data = dataset();
    data.year = 2004;
    data.boundary = { approximate: true, version: 'tiger2004-display-v1', boundary_vintage: 'Composite display',
      vintage_note: 'Approximate 2004 display. Original votes are not redistributed.',
      documentation_url: 'https://www.census.gov/', display_sha256: 'a'.repeat(64), repaired_features: 0, sources: [] };
    vi.stubGlobal('fetch', vi.fn(async () => respond(data)));
    open('/map?year=2004');
    const heading = await screen.findByRole('heading', { name: 'Historical display approximation' });
    expect(heading).toBeVisible();
    expect(within(heading.parentElement!).getByText(data.boundary.vintage_note)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Map select New York' })).toBeVisible();
  });

  it("handles API errors and retries without showing raw response details", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(respond({ detail: "password=private" }, 503))
      .mockResolvedValue(respond(dataset()));
    vi.stubGlobal("fetch", fetch);
    const user = userEvent.setup();
    open();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Map data could not be loaded",
    );
    expect(screen.queryByText(/password/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByRole("table");
  });

  it("rejects malformed map responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => respond({ units: [] })),
    );
    open();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The map response could not be read",
    );
  });

  it("aborts a stale nation request when a state filter changes", async () => {
    let finish!: (response: Response) => void;
    const fetch = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve;
          }),
      )
      .mockResolvedValue(respond(dataset(true)));
    vi.stubGlobal("fetch", fetch);
    render(
      <MemoryRouter>
        <LinkToState />
        <ElectionMapPage />
      </MemoryRouter>,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Loading election map",
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Change state" }));
    await screen.findByRole("heading", { name: "NY · County returns" });
    expect((fetch.mock.calls[0][1].signal as AbortSignal).aborted).toBe(true);
    await act(async () => finish(respond(dataset())));
    expect(
      screen.queryByRole("heading", { name: "United States · State returns" }),
    ).not.toBeInTheDocument();
  });
});

function LinkToState() {
  const navigate = useNavigate();
  return (
    <button onClick={() => navigate("/map?state_code=NY")}>Change state</button>
  );
}
