import pytest
from ingestion.electoral_college import parse
from ingestion.medsl import STATE_NAMES


def table(problem=None):
    rows=[]
    for i,name in enumerate(STATE_NAMES.values()):
        capacity=38 if i==0 else 10
        democrat=10 if i<33 else 2 if i==33 else 0
        republican=capacity-democrat
        if problem=='missing' and i==50:continue
        if problem=='invalid' and i==0:democrat='1.5'
        if problem=='overlap' and i==0:democrat=capacity+1
        row=f'<tr><td>{name}</td><td>{capacity}</td><td>{democrat}</td><td>{republican}</td></tr>'
        rows.append(row)
        if problem=='duplicate' and i==0:rows.append(row)
    return ('<table>'+''.join(rows)+'</table>').encode()


def test_official_partition_and_presidential_column_selection():
    data=parse(table(),2012)
    assert [c['votes'] for c in data['candidates']]==[332,206]
    assert data['other']==0 and len(data['states'])==51


@pytest.mark.parametrize('problem',['missing','duplicate','invalid','overlap'])
def test_bad_sources_fail_instead_of_inventing_electoral_votes(problem):
    with pytest.raises(ValueError):parse(table(problem),2012)
