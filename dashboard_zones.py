"""Version 2 dashboard contract: A upper 6x6, B lower 6x4. Offline only."""
import copy
import re

SPANS={'bar':(4,1),'semicircle':(2,2),'number':(2,2),'battery':(3,2)}
UPPER_NATIVE=(0x200005c8,0x200005e4,0x200005d0,0x200005d4,0x200005cc,
              0x200005ec,0x200005f0,0x200005f4,0x200005f8,0x200005fc,0x200005e8,
              *range(0x20000694,0x200006c4,4))


def validate(layout):
    import dashboard_custom as c
    c._keys(layout,('schema','background','widgets'),'two-zone layout')
    c._integer(layout['schema'],2,2,'schema');background=c._color(layout['background'])
    c._require(type(layout['widgets']) is list and 1<=len(layout['widgets'])<=7,'A two-zone layout needs one to seven widgets.')
    widgets=[];ids=set();channels=set();occupied=set()
    for item in layout['widgets']:
        c._keys(item,('id','channel','kind','zone','col','row','color'),'two-zone widget')
        name=item['id'];c._require(type(name) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,24}',name) is not None and name not in ids,'Invalid or duplicate widget ID.')
        kind=item['kind'];c._require(type(kind) is str and kind in SPANS,'Unknown two-zone widget kind.')
        channel=c._integer(item['channel'],0,6,'channel')
        c._require((channel==0)==(kind=='battery') and channel not in channels,'One battery and one widget per channel are allowed.')
        zone=item['zone'];c._require(type(zone) is str and zone in ('A','B'),'Zone must be A or B.')
        width,height=SPANS[kind];rows=6 if zone=='A' else 4
        col=c._integer(item['col'],0,5,'col');row=c._integer(item['row'],0,rows-1,'row')
        c._require(col+width<=6 and row+height<=rows,'Widget exceeds its zone.')
        cells={(zone,x,y) for y in range(row,row+height) for x in range(col,col+width)}
        c._require(not occupied.intersection(cells),'Widgets overlap in the same zone.')
        occupied.update(cells);ids.add(name);channels.add(channel)
        widgets.append(dict(id=name,channel=channel,kind=kind,zone=zone,col=col,row=row,color=c._color(item['color'])))
    widgets.sort(key=lambda w:(w['zone'],w['row'],w['col'],w['id']))
    return dict(schema=2,background=background,widgets=widgets)


def rectangle(widget):
    width,height=SPANS[widget['kind']];x=widget['col']*215//6
    return x,(0 if widget['zone']=='A' else 170)+widget['row']*25,(widget['col']+width)*215//6-x,height*25


def parts(widget):
    import dashboard_custom as c
    if widget['kind'] in ('bar','semicircle'):
        result=c.widget_parts({k:v for k,v in widget.items() if k!='zone'})
        result['container']=rectangle(widget);return result
    box=rectangle(widget);width=box[2]
    return {'kind':widget['kind'],'container':box,
            'gauge':(4,6,width-8,12) if widget['kind']=='battery' else (0,0,1,1),
            'title':(0,26,width-40,16) if widget['kind']=='battery' else (0,4,width,16),
            'value':(0,26,width,16) if widget['kind']=='number' else (width-38,26,38,16),
            'text_align':{'title':'center','value':'center'},'font_line_height':16,'range':(0,100) if widget['kind']=='battery' else (-120,120),
            'arc_angles':None,'arc_width':None}


DEFAULT={'schema':2,'background':'#162d46','widgets':[
    {'id':'battery','channel':0,'kind':'battery','zone':'A','col':0,'row':0,'color':'#32eb5a'},
    {'id':'g1','channel':1,'kind':'number','zone':'A','col':0,'row':3,'color':'#55b8f0'},
    {'id':'g2','channel':2,'kind':'number','zone':'A','col':3,'row':3,'color':'#55b8f0'},
    {'id':'g3','channel':3,'kind':'semicircle','zone':'B','col':0,'row':0,'color':'#b040ff'},
    {'id':'g4','channel':4,'kind':'semicircle','zone':'B','col':3,'row':0,'color':'#32eb5a'},
]}

def validate_lower(spec):
    import dashboard_custom as c
    c._require(type(spec['schema']) is int and spec['schema'] in (6,10),'Unknown lower grid schema.')
    checked=validate({**spec,'schema':2})
    c._require(all(w['zone']=='B' for w in checked['widgets']),'Only the lower grid (B) can be edited.')
    return {**checked,'schema':spec['schema']}

DEFAULT_LOWER={'schema':6,'background':DEFAULT['background'],'widgets':[
    {**w,'zone':'B','row':2 if w['kind']=='number' else 0} for w in DEFAULT['widgets'] if w['channel']
]}
