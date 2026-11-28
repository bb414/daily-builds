"""The review as a spreadsheet workbook (.xlsx), written with the standard library only.

A line-for-line copy of buildXlsx() in the browser model, so the app and the
companion write the same bytes: inline strings, numbers written as exact
decimal text, Excel date serials, live formulas for every total, and a zip of
stored (uncompressed) parts dated 1 January 1980.
"""

import re
import zlib

from .common import plain_money
from .detect import CADENCE_BY_ID
from .outputs import DECISION_LABELS, budget_csv, find_series
from .parsing import parse_delimited, strip_bom
from .payees import category_of
from .planning import forecast, is_cost, runway

STYLE = {'header': 1, 'money': 2, 'date': 3, 'boldMoney': 4, 'bold': 5, 'wrap': 6}

STYLES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<numFmts count="2"><numFmt numFmtId="164" formatCode="&quot;£&quot;#,##0.00;[Red]\\-&quot;£&quot;#,##0.00"/>'
    '<numFmt numFmtId="165" formatCode="d mmm yyyy"/></numFmts>'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFDDE9E3"/><bgColor indexed="64"/></patternFill></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="7"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="164" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')

_CONTROL = re.compile('[\u0000-\u0008\u000b\u000c\u000e-\u001f]')


def zip_store(files):
    """A zip archive of stored files ({'name', 'text'}), dated 1 January 1980 so the bytes never change."""
    out, central = bytearray(), []
    for f in files:
        name, data = f['name'].encode('utf-8'), f['text'].encode('utf-8')
        crc, offset = zlib.crc32(data) & 0xffffffff, len(out)
        out += (0x04034b50).to_bytes(4, 'little') + _u16(20, 0x0800, 0, 0, 33) + _u32(crc, len(data), len(data)) \
            + _u16(len(name), 0) + name + data
        central.append((0x02014b50).to_bytes(4, 'little') + _u16(20, 20, 0x0800, 0, 0, 33)
                       + _u32(crc, len(data), len(data)) + _u16(len(name), 0, 0, 0, 0) + _u32(0, offset) + name)
    cd_start = len(out)
    for c in central:
        out += c
    out += (0x06054b50).to_bytes(4, 'little') + _u16(0, 0, len(files), len(files)) \
        + _u32(len(out) - cd_start, cd_start) + _u16(0)
    return bytes(out)


def _u16(*values):
    return b''.join((v & 0xffff).to_bytes(2, 'little') for v in values)


def _u32(*values):
    return b''.join((v & 0xffffffff).to_bytes(4, 'little') for v in values)


def xml_text(s):
    """Text made safe for XML, without the control characters XML forbids."""
    s = _CONTROL.sub('', str(s))
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def col_name(i):
    """0 -> A, 25 -> Z, 26 -> AA."""
    s, i = '', i + 1
    while i > 0:
        r = (i - 1) % 26
        s = chr(65 + r) + s
        i = (i - 1) // 26
    return s


def c_text(v, style=0):
    return {'t': 's', 'v': '' if v is None else str(v), 's': style}


def c_num(v, style=0):
    return {'t': 'n', 'v': str(v), 's': style}


def c_money(pence, style=STYLE['money']):
    return {'t': 'n', 'v': plain_money(pence), 's': style}


def c_date(day):
    return None if day is None else {'t': 'n', 'v': str(day + 25569), 's': STYLE['date']}


def c_formula(f, style=0):
    return {'t': 'f', 'v': f, 's': style}


def header_row(names):
    return [c_text(n, STYLE['header']) for n in names]


def sheet_xml(sheet):
    """One worksheet's XML."""
    freeze = sheet.get('freeze') or 1
    x = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
         '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
         'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
         '<sheetViews><sheetView workbookViewId="0"><pane ySplit="%d" topLeftCell="A%d" activePane="bottomLeft" '
         'state="frozen"/></sheetView></sheetViews>' % (freeze, freeze + 1),
         '<sheetFormatPr defaultRowHeight="15"/>',
         '<cols>' + ''.join('<col min="%d" max="%d" width="%s" customWidth="1"/>' % (i + 1, i + 1, w)
                            for i, w in enumerate(sheet['widths'])) + '</cols>',
         '<sheetData>']
    for r, row in enumerate(sheet['rows']):
        cells = ''
        for i, c in enumerate(row):
            if not c:
                continue
            ref = col_name(i) + str(r + 1)
            st = ' s="%d"' % c['s'] if c['s'] else ''
            if c['t'] == 's':
                cells += '<c r="%s" t="inlineStr"%s><is><t xml:space="preserve">%s</t></is></c>' % (ref, st, xml_text(c['v']))
            elif c['t'] == 'f':
                cells += '<c r="%s"%s><f>%s</f></c>' % (ref, st, xml_text(c['v']))
            else:
                cells += '<c r="%s"%s><v>%s</v></c>' % (ref, st, c['v'])
        x.append('<row r="%d">%s</row>' % (r + 1, cells))
    x.append('</sheetData>')
    if sheet.get('filter'):
        x.append('<autoFilter ref="%s"/>' % sheet['filter'])
    x.append('</worksheet>')
    return ''.join(x)


def _absolute(ref):
    """A1:R23 as $A$1:$R$23."""
    return re.sub(r'([A-Z]+)(\d+)', r'$\1$\2', ref)


def build_xlsx(result, decisions=None, opts=None):
    """The review as a workbook. opts may hold transactions, accounts and runway ({account, balance, everyday, overdraft, extraIn}).

    Returns {'bytes', 'sheets', 'parts'}.
    """
    decisions = decisions or {}
    opts = opts or {}
    sheets = []
    reg = {'name': 'Regular payments', 'widths': [28, 26, 15, 16, 12, 12, 12, 9, 13, 13, 13, 10, 11, 60, 11, 30, 22, 11],
           'rows': [header_row(['Name', 'Category', 'Paid by', 'How often', 'Typical', 'Monthly', 'Yearly', 'Payments',
                                'First seen', 'Last seen', 'Next due', 'Status', 'Confidence', 'Checks', 'Decision',
                                'Note', 'Accounts', 'Counts as a cost'])]}
    for s in result['series']:
        d = decisions.get(s['id']) or {}
        cost = is_cost(s) and d.get('decision') != 'ignore'
        reg['rows'].append([
            c_text(s['name']), c_text(category_of(s['category'])['label']), c_text(s['method']),
            c_text(CADENCE_BY_ID[s['cadence']]['label']), c_money(s['typical']), c_money(s['monthly']),
            c_money(s['annual']), c_num(s['count']), c_date(s['first']), c_date(s['last']), c_date(s['nextDue']),
            c_text(s['status']), c_num(s['confidence']), c_text(' '.join(f['text'] for f in s['flags']), STYLE['wrap']),
            c_text(DECISION_LABELS[d['decision']] if d.get('decision') else ''), c_text(d.get('note') or ''),
            c_text(s['account']), c_text('Yes' if cost else 'No')])
    last = len(result['series']) + 1
    reg['rows'].append([])
    reg['rows'].append([c_text('Committed (rows that count as a cost)', STYLE['bold']), None, None, None, None,
                        c_formula('SUMIF(R2:R%d,"Yes",F2:F%d)' % (last, last), STYLE['boldMoney']),
                        c_formula('SUMIF(R2:R%d,"Yes",G2:G%d)' % (last, last), STYLE['boldMoney'])])
    reg['rows'].append([c_text('Marked to cancel', STYLE['bold']), None, None, None, None,
                        c_formula('SUMIFS(F2:F%d,R2:R%d,"Yes",O2:O%d,"Cancel")' % (last, last, last), STYLE['boldMoney']),
                        c_formula('SUMIFS(G2:G%d,R2:R%d,"Yes",O2:O%d,"Cancel")' % (last, last, last), STYLE['boldMoney'])])
    reg['filter'] = 'A1:R%d' % last
    sheets.append(reg)

    budget = parse_delimited(strip_bom(budget_csv(result, decisions, 12)), ',')['rows']
    bs = {'name': 'Next 12 months', 'widths': [34] + [12 for _ in budget[0][1:]], 'rows': [header_row(budget[0])]}
    n_cats = len(budget) - 2
    for i, row in enumerate(budget[1:-1]):
        r = i + 2
        bs['rows'].append([c_text(row[0])] + [c_num(v, STYLE['money']) for v in row[1:13]]
                          + [c_formula('SUM(B%d:M%d)' % (r, r), STYLE['boldMoney'])])
    bs['rows'].append([c_text('Total', STYLE['bold'])]
                      + [c_formula('SUM(%s2:%s%d)' % (col_name(c), col_name(c), n_cats + 1), STYLE['boldMoney'])
                         for c in range(1, 14)])
    sheets.append(bs)

    cal = {'name': 'Calendar', 'widths': [13, 30, 12, 8, 30, 12, 14],
           'rows': [header_row(['Date', 'Payment', 'Amount', 'In or out', 'Category', 'Decision', 'Running total out'])]}
    for i, it in enumerate(forecast(result, 92, decisions)):
        r = i + 2
        running = 'IF(AND(D%d="Out",F%d<>"Cancel",F%d<>"Not a cost"),C%d,0)' % (r, r, r, r)
        cal['rows'].append([c_date(it['day']), c_text(it['name']), c_money(it['amount']),
                            c_text('In' if it['direction'] == 'in' else 'Out'), c_text(category_of(it['category'])['label']),
                            c_text(DECISION_LABELS[it['decision']] if it['decision'] else ''),
                            c_formula(running if r == 2 else 'G%d+%s' % (r - 1, running), STYLE['money'])])
    cal['filter'] = 'A1:G%d' % len(cal['rows'])
    sheets.append(cal)

    if opts.get('transactions') is not None:
        tag = {}
        for s in result['series'] + result['income']:
            for p in s['payments']:
                tag['%s|%d|%d|%s' % (p['account'], p['day'], -p['amount'] if s['direction'] == 'out' else p['amount'],
                                     p['desc'])] = s['name']
        tx = {'name': 'Transactions', 'widths': [13, 20, 44, 12, 28, 24],
              'rows': [header_row(['Date', 'Account', 'Description', 'Amount', 'Regular payment', 'From file'])]}
        for t in opts['transactions']:
            tx['rows'].append([c_date(t['day']), c_text(t['account']), c_text(t['desc']), c_money(t['amount']),
                               c_text(tag.get('%s|%d|%d|%s' % (t['account'], t['day'], t['amount'], t['desc']), '')),
                               c_text(t.get('source') or '')])
        tx['filter'] = 'A1:F%d' % len(tx['rows'])
        sheets.append(tx)

    rwo = opts.get('runway')
    if not rwo and opts.get('accounts'):
        with_bal = [a for a in opts['accounts'] if a.get('closing')]
        pay = find_series(result, result['payday']['seriesId']) if result.get('payday') else None
        pick = next((a for a in with_bal if pay and a['account'] in pay['accounts']), None) or (with_bal[0] if with_bal else None)
        if pick:
            ev = result['everyday'].get(pick['account'])
            rwo = {'account': pick['account'], 'balance': pick['closing']['balance'], 'everyday': ev['perDay'] if ev else 0}
    if rwo and rwo.get('balance') is not None:
        rw = runway(result, decisions, {'account': rwo['account'], 'balance': rwo['balance'],
                                        'everyday': rwo.get('everyday') or 0, 'overdraft': rwo.get('overdraft') or 0,
                                        'days': 60, 'leaveOutCancelled': True, 'extraIn': rwo.get('extraIn') or []})
        bal = {'name': 'Balance day by day', 'freeze': 3, 'widths': [13, 14, 14, 14, 60], 'rows': []}
        bal['rows'].append([c_text(rwo['account'] + ': balance walked forward a day at a time', STYLE['bold'])])
        bal['rows'].append([c_text('Everyday spending a day', STYLE['bold']), c_money(rw['everyday']), None, None,
                            c_text('Change this and every balance below updates.')])
        bal['rows'].append(header_row(['Date', 'Regular change', 'Everyday', 'Balance', 'Payments and money in']))
        bal['rows'].append([c_date(result['asOf'] - 1), None, None, c_money(rwo['balance']), c_text('Balance now')])
        for i, d in enumerate(rw['days']):
            r = i + 5
            bal['rows'].append([c_date(d['day']), c_money(d['change'] + rw['everyday']), c_formula('-$B$2', STYLE['money']),
                                c_formula('D%d+B%d+C%d' % (r - 1, r, r), STYLE['money']),
                                c_text('; '.join(('+' if it['direction'] == 'in' else '-') + plain_money(it['amount']) + ' '
                                                 + it['name'] for it in d['items']))])
        sheets.append(bal)

    files = [{'name': '[Content_Types].xml', 'text': (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + ''.join('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.'
                  'spreadsheetml.worksheet+xml"/>' % (i + 1) for i in range(len(sheets)))
        + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')},
        {'name': '_rels/.rels', 'text': (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/></Relationships>')}]
    defined = ''.join('<definedName name="_xlnm._FilterDatabase" localSheetId="%d" hidden="1">\'%s\'!%s</definedName>'
                      % (i, xml_text(s['name']), _absolute(s['filter'])) for i, s in enumerate(sheets) if s.get('filter'))
    files.append({'name': 'xl/workbook.xml', 'text': (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><bookViews><workbookView/></bookViews><sheets>'
        + ''.join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (xml_text(s['name']), i + 1, i + 1) for i, s in enumerate(sheets))
        + '</sheets>' + ('<definedNames>' + defined + '</definedNames>' if defined else '')
        + '<calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>')})
    files.append({'name': 'xl/_rels/workbook.xml.rels', 'text': (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + ''.join('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                  'Target="worksheets/sheet%d.xml"/>' % (i + 1, i + 1) for i in range(len(sheets)))
        + '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
          'Target="styles.xml"/></Relationships>' % (len(sheets) + 1))})
    files.append({'name': 'xl/styles.xml', 'text': STYLES_XML})
    for i, s in enumerate(sheets):
        files.append({'name': 'xl/worksheets/sheet%d.xml' % (i + 1), 'text': sheet_xml(s)})
    return {'bytes': zip_store(files), 'sheets': [s['name'] for s in sheets], 'parts': files}
