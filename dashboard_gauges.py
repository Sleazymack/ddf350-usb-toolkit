"""Current lower-grid design contract, preserving the historical builders."""
import copy

SCHEMA = 13
DEFAULT_PANEL = '#101924'


def upgrade(layout):
    import dashboard_custom as c
    spec = c.validate_layout(layout)
    if spec['schema'] == SCHEMA:
        return spec
    if spec['schema'] not in (1, 6, 10, 12):
        raise ValueError('Only a lower-grid composition can use the current gauge style.')
    widgets = [{**item, 'zone': 'B', 'background': DEFAULT_PANEL} for item in spec['widgets']]
    current = dict(schema=SCHEMA, background=spec['background'], widgets=widgets,
                   full_background=spec['schema'] == 12, wallpaper=spec.get('wallpaper'),blink_ch2=False)
    if 'header' in spec:
        current['header'] = spec['header']
    return validate(current)


def validate(layout):
    import dashboard_custom as c
    optional = ('header',) if 'header' in layout else ()
    c._keys(layout, ('schema', 'background', 'widgets', 'full_background', 'wallpaper','blink_ch2') + optional,
            'current gauge layout')
    c._integer(layout['schema'], SCHEMA, SCHEMA, 'schema')
    c._require(type(layout['full_background']) is bool, 'Full background must be a boolean.')
    c._require(type(layout['blink_ch2']) is bool, 'CH2 alarm must be a boolean.')
    c._require(layout['full_background'] or layout['wallpaper'] is None, 'A photo requires a full background.')
    c._require(layout['full_background'] or not optional, 'The minimal header requires a full background.')
    c._require(type(layout['widgets']) is list, 'Widgets must be a list.')
    widgets = []
    backgrounds = {}
    for item in layout['widgets']:
        c._keys(item, ('id', 'channel', 'kind', 'zone', 'col', 'row', 'color', 'background'), 'current gauge')
        c._require(type(item['id']) is str,'Widget ID must be a string.')
        backgrounds[item['id']] = c._color(item['background'])
        widgets.append({key: value for key, value in item.items() if key != 'background'})
    base = dict(schema=12, background=layout['background'], widgets=widgets, wallpaper=layout['wallpaper'])
    if optional:
        base['header'] = layout['header']
    checked = c.validate_layout(base)
    return {**checked, 'schema': SCHEMA, 'full_background': layout['full_background'],
            'blink_ch2':layout['blink_ch2'],
            'widgets': [{**item, 'background': backgrounds[item['id']]} for item in checked['widgets']]}


def parts(widget):
    import dashboard_zones as zones
    base = zones.parts({key: value for key, value in widget.items() if key != 'background'})
    result = copy.deepcopy(base)
    result['range'] = (0, 100) if widget['kind'] == 'battery' else (-100, 100)
    if widget['kind'] == 'semicircle':
        result['arc_width'] = 8
    elif widget['kind'] == 'bar':
        x, _, width, _ = result['gauge']
        result['gauge'] = (x, 6, width, 12)
    return result
