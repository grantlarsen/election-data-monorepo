import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, it, expect, vi } from 'vitest';
import { SiteHeader } from '../SiteHeader';
import { PresidentialHistory } from '../PresidentialHistory';
import { App } from '../App';
import { navigation } from '../navigation';

const event=(year:number,id=String(year))=>({ id,election_date:`${year}-11-${year===2024?'05':'04'}`,stage:'general' });
const response=(items:unknown[],has_more=false)=>({ ok:true,json:async()=>({ items,has_more }) });

describe('site header and presidential archive',()=> {
  it('opens one section at a time, closes on Escape/outside and sends the logo home',async()=> {
    const user=userEvent.setup();
    render(<MemoryRouter><SiteHeader /></MemoryRouter>);
    expect(screen.getByRole('link',{name:'Electoral Atlas home'})).toHaveAttribute('href','/');
    for (const group of navigation) expect(screen.getByRole('button',{name:group.label})).toHaveAttribute('aria-expanded','false');
    await user.click(screen.getByRole('button',{name:'President'}));
    expect(screen.getByRole('link',{name:/2028 Democratic Primary/})).toHaveAttribute('href','/presidential/2028/democratic-primary');
    await user.click(screen.getByRole('button',{name:'Senate'}));
    expect(screen.queryByRole('link',{name:/2028 Democratic Primary/})).not.toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(screen.getByRole('button',{name:'Senate'})).toHaveFocus();
    expect(screen.queryByRole('link',{name:/2026 Election Results/})).not.toBeInTheDocument();
    await user.click(screen.getByRole('button',{name:'Search'}));
    expect(screen.getByRole('link',{name:'Contests'})).toHaveAttribute('href','/contests');
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole('link',{name:'Contests'})).not.toBeInTheDocument();
  });

  it.each(navigation.flatMap(g=>g.items.filter(i=>i.planned).map(i=>[g.label,i.label,i.to])))('resolves %s / %s to its placeholder', (group,label,path)=> {
    const fetch=vi.fn(); vi.stubGlobal('fetch',fetch);
    render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);
    expect(screen.getByRole('heading',{name:label,level:1})).toBeVisible();
    expect(screen.getByText('Coming soon')).toBeVisible();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('loads all discovery pages, groups state events, and uses static images without map requests',async()=> {
    const fetch=vi.fn().mockResolvedValueOnce(response([event(2024),event(2024,'second-state')],true))
      .mockResolvedValueOnce(response([event(2008)]));
    vi.stubGlobal('fetch',fetch);
    const {container}=render(<MemoryRouter><PresidentialHistory /></MemoryRouter>);
    await screen.findByRole('link',{name:/2024 Presidential election/});
    expect(screen.getAllByRole('link')).toHaveLength(2);
    expect(screen.getAllByRole('img')).toHaveLength(2);
    expect(screen.getAllByRole('img')[0]).toHaveAttribute('src','/election-previews/president-2024-general.png');
    expect(container.querySelector('svg')).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[1][0]).toContain('offset=2');
    expect(fetch.mock.calls.every(([url])=>url.startsWith('/api/v1/elections?'))).toBe(true);
  });

  it('includes elections without a generated preview and links them to the existing map',async()=> {
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response([event(1996)])));
    render(<MemoryRouter><PresidentialHistory /></MemoryRouter>);
    const card=await screen.findByRole('link',{name:/1996 Presidential election/});
    expect(card).toHaveAttribute('href',expect.stringContaining('/map?year=1996'));
    expect(screen.getByText('Preview pending')).toBeVisible();
  });

  it('offers retry for failed discovery and an explicit empty state',async()=> {
    const fetch=vi.fn().mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce(response([]));
    vi.stubGlobal('fetch',fetch);
    render(<MemoryRouter><PresidentialHistory /></MemoryRouter>);
    await screen.findByRole('heading',{name:'History unavailable'});
    fireEvent.click(screen.getByRole('button',{name:'Try again'}));
    await waitFor(()=>expect(screen.getByRole('heading',{name:'No presidential elections available'})).toBeVisible());
  });
});
