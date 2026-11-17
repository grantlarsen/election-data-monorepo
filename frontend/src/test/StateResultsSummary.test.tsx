import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { StateResultsSummary } from "../map/StateResultsSummary";
import type { ElectionMap, MapUnit } from "../map/types";
import { publication } from "./fixtures";

const state = {
  id: "05",
  geoid: "05",
  name: "Arkansas",
  state_code: "AR",
  publication_batch_id: publication.batch_id,
  summary: {
    status: "available",
    total_votes: 1000,
    leader: "Source leader",
    margin_votes: 200,
    margin_pp: 20,
    candidates: [
      {
        label: "Source leader",
        kind: "source_candidate",
        party_labels: ['DEMOCRATIC'],
        votes: 600,
        share: 60,
      },
      { label: "Runner-up", kind: "source_candidate", party_labels: ['REPUBLICAN'], votes: 400, share: 40 },
    ],
  },
} as MapUnit;
const selection = {
  year: 2008,
  office: "U.S. President",
  stage: "general",
  state_code: "AR",
  reporting_level: "county",
  selected_jurisdiction_id: "selected-county",
  units: [{ ...state, summary: { ...state.summary, total_votes: 9999 } }],
} as ElectionMap;
const overview = {
  year: 2008,
  reporting_level: "state",
  state_code: "AR",
  availability: "available",
  features: { type: "FeatureCollection", features: [] },
  units: [state],
  publications: [publication],
  coverage: {
    boundary_units: 1,
    units_with_results: 1,
    missing_results: 0,
    results_without_geometry: 0,
  },
} as unknown as ElectionMap;
const response = (body: unknown, status = 200) =>
  ({ ok: status === 200, status, json: async () => body }) as Response;

describe("published statewide overview", () => {
  it('links candidates only when the statewide authority supplies a candidacy ID', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response({ ...overview, units: [{ ...state,
      summary: { ...state.summary, candidates: [{ ...state.summary.candidates[0], candidacy_id: 'known' }, state.summary.candidates[1]] },
    }] })));
    render(<StateResultsSummary selection={selection} />);
    expect(await screen.findByRole('link', { name: 'Source leader' })).toHaveAttribute('href', '/candidates/known');
    expect(screen.queryByRole('link', { name: 'Runner-up' })).not.toBeInTheDocument();
  });
  it("requests state authority independently of county selection and displays API metrics", async () => {
    const fetch = vi.fn(async (_url: string) => response(overview));
    vi.stubGlobal("fetch", fetch);
    render(<StateResultsSummary selection={selection} />);
    await screen.findByRole("heading", { name: "Arkansas statewide summary" });
    expect(screen.getByText("1,000")).toBeVisible();
    expect(screen.queryByText("9,999")).not.toBeInTheDocument();
    expect(screen.getByText("20.00%")).toBeVisible();
    expect(screen.getByText("votes · 60.00%")).toBeVisible();
    expect(screen.getByText("Leading").closest('li')).toHaveTextContent("Source leader");
    expect(screen.getByText('Source leader').closest('li')!.querySelector('i')).toHaveStyle({ background: '#3276ac' });
    expect(screen.getByText('Runner-up').closest('li')!.querySelector('i')).toHaveStyle({ background: '#bd5548' });
    expect(screen.queryByText("Leading candidate statewide")).not.toBeInTheDocument();
    const query = new URLSearchParams(fetch.mock.calls[0][0].split("?")[1]);
    expect(query.get("reporting_level")).toBe("state");
    expect(query.get("state_code")).toBe("AR");
    expect(query.has("jurisdiction_id")).toBe(false);
    expect(
      screen.getByText(/State and county publications may differ/),
    ).toBeVisible();
  });
  it("explains unavailable authority without adding up county votes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response({ ...overview, units: [], publications: [] })),
    );
    render(<StateResultsSummary selection={selection} />);
    expect(await screen.findByRole("status")).toHaveTextContent(
      /Published statewide results are unavailable/,
    );
    expect(screen.queryByText("9,999")).not.toBeInTheDocument();
  });
  it("preserves stored zero state totals and unavailable margin", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        response({
          ...overview,
          units: [
            {
              ...state,
              summary: {
                ...state.summary,
                status: "zero_total",
                total_votes: 0,
                leader: null,
                margin_pp: null,
                margin_votes: null,
                candidates: [],
              },
            },
          ],
        }),
      ),
    );
    render(<StateResultsSummary selection={selection} />);
    expect(await screen.findByText("0")).toBeVisible();
    expect(screen.getByText("Unavailable")).toBeVisible();
  });
  it("retries a failed summary without replacing the county map", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(response({}, 503))
        .mockResolvedValue(response(overview)),
    );
    render(<StateResultsSummary selection={selection} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "State summary could not be loaded",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Retry state summary" }),
    );
    expect(
      await screen.findByRole("heading", {
        name: "Arkansas statewide summary",
      }),
    ).toBeVisible();
  });
});
