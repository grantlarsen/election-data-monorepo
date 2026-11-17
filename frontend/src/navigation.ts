export interface NavigationItem { label: string; to: string; planned?: boolean }
export const navigation: { label: string; items: NavigationItem[] }[] = [
  { label:'President', items:[
    { label:'2028 Electoral College Map', to:'/presidential/2028/electoral-map', planned:true },
    { label:'2028 Democratic Primary', to:'/presidential/2028/democratic-primary', planned:true },
    { label:'2028 Republican Primary', to:'/presidential/2028/republican-primary', planned:true },
    { label:'2024 Election', to:'/presidential/2024' },
    { label:'Historic Data', to:'/presidential/history' },
  ] },
  { label:'Senate', items:[
    { label:'2026 Election Results', to:'/senate/2026/results' },
    { label:'2028 Electoral Map', to:'/senate/2028/map', planned:true },
    { label:'Historic Data', to:'/senate/history', planned:true },
  ] },
  { label:'House', items:[
    { label:'2026 Election Results', to:'/house/2026/results' },
    { label:'Historic Data', to:'/house/history', planned:true },
  ] },
  { label:'Governor', items:[
    { label:'2026 Election Results', to:'/governor/2026/results' },
    { label:'2028 Electoral Map', to:'/governor/2028/map', planned:true },
    { label:'Historic Data', to:'/governor/history', planned:true },
  ] },
  { label:'States', items:[
    { label:'2026 Election Results', to:'/states/2026/results', planned:true },
    { label:'Historic Data', to:'/states/history', planned:true },
  ] },
  { label:'Financing', items:[
    { label:'2026 Total Election Spending', to:'/financing/2026/total-spending', planned:true },
    { label:'2026 PAC and Super PAC Spending', to:'/financing/2026/pac-spending', planned:true },
    { label:'Campaign Finance Trends', to:'/financing/trends', planned:true },
    { label:'Historic Data', to:'/financing/history', planned:true },
  ] },
  { label:'Search', items:[
    { label:'Search all data', to:'/search', planned:true },
    { label:'Map', to:'/map' }, { label:'Contests', to:'/contests' }, { label:'Candidates', to:'/candidates' },
  ] },
];
