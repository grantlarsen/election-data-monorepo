import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import HouseMap, { fetchHouseBoundaries, houseRaceColor } from '../HouseMap';
import { smallStates } from '../geography/smallStates';
import { partyPalette } from '../map/electionColors';
import { snapshot } from './houseFixtures';
import { boundarySnapshot } from './houseMapFixtures';

describe('2026 House district map', () => {
  it('joins all 435 voting districts plus DC and colors explicit calls instead of leads', async () => {
    const data = snapshot();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => boundarySnapshot(data) }));
    const onSelect = vi.fn();
    render(<HouseMap data={data} selectedState="" selectedDistrict="" onSelect={onSelect} />);
    const map = await screen.findByRole('group', { name: '2026 House results map' });
    expect(map.querySelectorAll('path[data-geoid]')).toHaveLength(436);
    const ca = within(map).getByRole('button', { name: /^California District 1:/ });
    expect(ca).toHaveAttribute('fill', houseRaceColor(data.races[0]));
    expect(ca).not.toHaveAttribute('fill', partyPalette.Democratic);
    expect(within(map).getByRole('button', { name: /^Wyoming at-large:/ })).toHaveAttribute('fill', partyPalette.Republican);
    expect(within(map).getByRole('button', { name: /^Florida District 10:/ })).toHaveAttribute('fill', partyPalette.Democratic);
    fireEvent.keyDown(ca, { key: 'Enter' });
    expect(onSelect).toHaveBeenCalledWith(data.races[0]);
    fireEvent.focus(ca);
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Candidate D');
    expect(screen.getByRole('tooltip')).not.toHaveTextContent('Projected winner');
    expect(within(map).getByRole('img', { name: 'DC: delegate outside voting-seat scope' })).not.toHaveAttribute('tabindex');
  });

  it('shows every requested compact state, real district tiles and an out-of-scope DC tile', async () => {
    const data = snapshot();
    const vt = { ...data.races[1], id: 'VT-AL', state_code: 'VT', state_name: 'Vermont' };
    data.races.push(vt); data.missing_districts = data.missing_districts.filter(id => id !== vt.id);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => boundarySnapshot(data) }));
    const onSelect = vi.fn();
    render(<HouseMap data={data} selectedState="" selectedDistrict="VT-AL" onSelect={onSelect} />);
    const aside = screen.getByRole('complementary', { name: 'Small states and DC House districts' });
    expect(within(aside).getAllByRole('heading').map(h => h.textContent)).toEqual([...smallStates]);
    const tile = within(aside).getByRole('button', { name: /^Vermont at-large:/ });
    expect(tile).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(tile);
    expect(onSelect).toHaveBeenCalledWith(vt);
    expect(within(aside).getByRole('img', { name: 'DC: nonvoting delegate outside this feed' })).toHaveTextContent('DC');
    expect(aside.querySelectorAll('.house-seat-tiles > *')).toHaveLength(41);
  });

  it('fits the selected state, retains national insets, and provides map zoom controls', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => boundarySnapshot() }));
    render(<HouseMap data={snapshot()} selectedState="CA" selectedDistrict="CA-01" onSelect={vi.fn()} />);
    const map = await screen.findByRole('group', { name: '2026 House results map' });
    expect(map.querySelectorAll('path[data-geoid]')).toHaveLength(52);
    expect(map.querySelector('path[data-geoid="0601"]')).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    expect(screen.getByRole('button', { name: 'Reset zoom' })).toBeEnabled();
    expect(screen.getByRole('complementary')).toBeVisible();
  });

  it('keeps results usable after a boundary failure and offers retry', async () => {
    const fetch = vi.fn().mockResolvedValueOnce({ ok: false }).mockResolvedValue({ ok: true, json: async () => boundarySnapshot() });
    vi.stubGlobal('fetch', fetch);
    render(<HouseMap data={snapshot()} selectedState="" selectedDistrict="" onSelect={vi.fn()} />);
    expect(await screen.findByText(/The map could not load/)).toBeVisible();
    expect(screen.getByRole('complementary')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Retry map' }));
    expect(await screen.findByRole('group', { name: '2026 House results map' })).toBeVisible();
  });

  it.each(['year', 'duplicate', 'cross_state', 'dc', 'grain'])('rejects incompatible boundary payloads: %s', async failure => {
    const body = boundarySnapshot();
    if (failure === 'year') body.source.year = 2024;
    if (failure === 'duplicate') body.features[1] = body.features[0];
    if (failure === 'cross_state') body.features[0].properties.state_code = 'TX';
    if (failure === 'dc') body.features = body.features.filter(f => f.properties.state_code !== 'DC');
    if (failure === 'grain') body.source.reporting_levels = ['county'];
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => body }));
    await expect(fetchHouseBoundaries(new AbortController().signal)).rejects.toThrow();
  });
});
