# -*- coding: utf-8 -*-
"""BPMN 2.0 產生器（規則式，純函式，不依賴 Odoo）：流程模型 → 帶座標的 XML ＋ 同座標的 SVG。

版面沿用「角色泳道圖」做法：時間軸由左至右（欄）、角色泳道由上而下；節點固定在網格，
連線正交（同泳道水平；跨泳道從欄間空隙垂直轉折），所以方框不碰撞、交接線不壓字。
XML 的 DI 與 SVG 用同一組座標，bpmn-js 打開與前台圖片看起來一樣。

模型格式：
    {'name': 流程名, 'lanes': [{'id', 'name'}],
     'nodes': [{'id', 'kind': start|task|gateway|end|subprocess, 'name', 'lane', 'col'}],
     'edges': [{'id'?, 'src', 'dst', 'name'?}]}
"""
import html
import re
import xml.etree.ElementTree as ET

POOL_X, POOL_LABEL, LANE_LABEL = 20, 30, 90
COL_W, LANE_H, TOP = 210, 120, 20
TASK_W, TASK_H, EVENT_D, GATE_D = 124, 64, 36, 50
NS = {
    'bpmn': 'http://www.omg.org/spec/BPMN/20100524/MODEL',
    'bpmndi': 'http://www.omg.org/spec/BPMN/20100524/DI',
    'dc': 'http://www.omg.org/spec/DD/20100524/DC',
    'di': 'http://www.omg.org/spec/DD/20100524/DI',
}
TAGS = {'start': 'startEvent', 'end': 'endEvent', 'task': 'task', 'gateway': 'exclusiveGateway',
        'subprocess': 'callActivity'}


def _esc(s):
    return html.escape(s or '', quote=True)


def _slug(s):
    return re.sub(r'[^A-Za-z0-9_]', '_', s or 'x')


def lane_rows(model):
    """每個泳道有幾列（節點的 row 從 0 起；取消類結束放在下一列）。"""
    rows = {l['id']: 1 for l in model['lanes']}
    for n in model['nodes']:
        rows[n['lane']] = max(rows[n['lane']], n.get('row', 0) + 1)
    return rows


def lane_tops(model):
    rows, tops, y = lane_rows(model), {}, TOP
    for l in model['lanes']:
        tops[l['id']] = y
        y += rows[l['id']] * LANE_H
    return tops, y - TOP


def layout(model):
    """回傳 {node_id: (x, y, w, h)} 與池子大小。"""
    cols = max([n['col'] for n in model['nodes']] or [0]) + 1
    left = POOL_X + POOL_LABEL + LANE_LABEL
    tops, height = lane_tops(model)
    boxes = {}
    for n in model['nodes']:
        cx = left + 40 + n['col'] * COL_W + TASK_W / 2
        cy = tops[n['lane']] + n.get('row', 0) * LANE_H + LANE_H / 2
        if n['kind'] in ('start', 'end'):
            w = h = EVENT_D
        elif n['kind'] == 'gateway':
            w = h = GATE_D
        else:
            w, h = TASK_W, TASK_H
        boxes[n['id']] = (cx - w / 2, cy - h / 2, w, h)
    width = left + 40 + cols * COL_W
    return boxes, width, height


def _route(a, b):
    """正交連線：同一列水平；不同列從欄間空隙轉折；往回的連線從下方繞。"""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    acy, bcy = ay + ah / 2, by + bh / 2
    if bx >= ax + aw:
        sx, tx = ax + aw, bx
        if abs(acy - bcy) < 1:
            return [(sx, acy), (tx, bcy)]
        mx = tx - 20
        return [(sx, acy), (mx, acy), (mx, bcy), (tx, bcy)]
    if abs((ax + aw / 2) - (bx + bw / 2)) < 1 and by > ay:
        # 同一欄、目標在下方（取消類結束）：直下
        return [(ax + aw / 2, ay + ah), (bx + bw / 2, by)]
    # 往回：從下方繞
    low = max(ay + ah, by + bh) + 18
    return [(ax + aw / 2, ay + ah), (ax + aw / 2, low), (bx + bw / 2, low), (bx + bw / 2, by + bh)]


def to_xml(model, process_id='Process_kb'):
    boxes, width, height = layout(model)
    pid = _slug(process_id)
    nodes = {n['id']: n for n in model['nodes']}
    edges = [dict(e, id=e.get('id') or 'Flow_%s_%s' % (e['src'], e['dst'])) for e in model['edges']]
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<bpmn:definitions xmlns:bpmn="%(bpmn)s" xmlns:bpmndi="%(bpmndi)s" '
           'xmlns:dc="%(dc)s" xmlns:di="%(di)s" id="Defs_%(p)s" '
           'targetNamespace="http://bpmn.io/schema/bpmn">' % dict(NS, p=pid),
           '<bpmn:collaboration id="Collab_%s">' % pid,
           '<bpmn:participant id="Pool_%s" name="%s" processRef="%s"/>' % (
               pid, _esc(model.get('name')), pid),
           '</bpmn:collaboration>',
           '<bpmn:process id="%s" isExecutable="false">' % pid,
           '<bpmn:laneSet id="LaneSet_%s">' % pid]
    for lane in model['lanes']:
        out.append('<bpmn:lane id="Lane_%s" name="%s">' % (_slug(lane['id']), _esc(lane['name'])))
        out += ['<bpmn:flowNodeRef>%s</bpmn:flowNodeRef>' % n['id']
                for n in model['nodes'] if n['lane'] == lane['id']]
        out.append('</bpmn:lane>')
    out.append('</bpmn:laneSet>')
    for n in model['nodes']:
        tag = TAGS[n['kind']]
        ins = ''.join('<bpmn:incoming>%s</bpmn:incoming>' % e['id'] for e in edges if e['dst'] == n['id'])
        outs = ''.join('<bpmn:outgoing>%s</bpmn:outgoing>' % e['id'] for e in edges if e['src'] == n['id'])
        out.append('<bpmn:%s id="%s" name="%s">%s%s</bpmn:%s>' % (
            tag, n['id'], _esc(n.get('name')), ins, outs, tag))
    for e in edges:
        out.append('<bpmn:sequenceFlow id="%s" name="%s" sourceRef="%s" targetRef="%s"/>' % (
            e['id'], _esc(e.get('name')), e['src'], e['dst']))
    out.append('</bpmn:process>')
    out.append('<bpmndi:BPMNDiagram id="Diagram_%s"><bpmndi:BPMNPlane id="Plane_%s" '
               'bpmnElement="Collab_%s">' % (pid, pid, pid))
    out.append('<bpmndi:BPMNShape id="Pool_%s_di" bpmnElement="Pool_%s" isHorizontal="true">'
               '<dc:Bounds x="%d" y="%d" width="%d" height="%d"/></bpmndi:BPMNShape>' % (
                   pid, pid, POOL_X, TOP, width - POOL_X, height))
    tops, _h = lane_tops(model)
    rows = lane_rows(model)
    for lane in model['lanes']:
        out.append('<bpmndi:BPMNShape id="Lane_%s_di" bpmnElement="Lane_%s" isHorizontal="true">'
                   '<dc:Bounds x="%d" y="%d" width="%d" height="%d"/></bpmndi:BPMNShape>' % (
                       _slug(lane['id']), _slug(lane['id']), POOL_X + POOL_LABEL,
                       tops[lane['id']], width - POOL_X - POOL_LABEL, rows[lane['id']] * LANE_H))
    for n in model['nodes']:
        x, y, w, h = boxes[n['id']]
        out.append('<bpmndi:BPMNShape id="%s_di" bpmnElement="%s"><dc:Bounds x="%d" y="%d" '
                   'width="%d" height="%d"/></bpmndi:BPMNShape>' % (n['id'], n['id'], x, y, w, h))
    for e in edges:
        pts = _route(boxes[e['src']], boxes[e['dst']])
        out.append('<bpmndi:BPMNEdge id="%s_di" bpmnElement="%s">%s</bpmndi:BPMNEdge>' % (
            e['id'], e['id'], ''.join('<di:waypoint x="%d" y="%d"/>' % p for p in pts)))
    out.append('</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></bpmn:definitions>')
    return '\n'.join(out)


def _wrap(text, per_line=8, lines=2):
    text = text or ''
    parts = [text[i:i + per_line] for i in range(0, len(text), per_line)][:lines]
    if len(text) > per_line * lines and parts:
        parts[-1] = parts[-1][:-1] + '…'
    return parts


def to_svg(model):
    """同座標的靜態圖（給前台文章用，不需要 bpmn-js）。"""
    boxes, width, height = layout(model)
    W, H = width + 20, height + TOP * 2
    s = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
         'font-family="sans-serif" font-size="12">' % (W, H),
         '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
         'markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#666"/>'
         '</marker></defs>',
         '<rect x="%d" y="%d" width="%d" height="%d" fill="#fff" stroke="#888"/>' % (
             POOL_X, TOP, width - POOL_X, height)]
    s.append('<text x="%d" y="%d" transform="rotate(-90 %d %d)" text-anchor="middle" '
             'font-weight="bold">%s</text>' % (
                 POOL_X + 19, TOP + height / 2, POOL_X + 19, TOP + height / 2,
                 _esc(model.get('name'))))
    tops, _h = lane_tops(model)
    rows = lane_rows(model)
    for i, lane in enumerate(model['lanes']):
        y, lh = tops[lane['id']], rows[lane['id']] * LANE_H
        s.append('<rect x="%d" y="%d" width="%d" height="%d" fill="%s" stroke="#bbb"/>' % (
            POOL_X + POOL_LABEL, y, width - POOL_X - POOL_LABEL, lh,
            '#f7f9fc' if i % 2 else '#ffffff'))
        s.append('<text x="%d" y="%d" fill="#333" font-weight="bold">%s</text>' % (
            POOL_X + POOL_LABEL + 8, y + LANE_H / 2 + 4, _esc(lane['name'])))
    nodes = {n['id']: n for n in model['nodes']}
    for e in model['edges']:
        pts = _route(boxes[e['src']], boxes[e['dst']])
        s.append('<polyline points="%s" fill="none" stroke="#666" stroke-width="1.2" '
                 'marker-end="url(#a)"/>' % ' '.join('%d,%d' % p for p in pts))
        if e.get('name'):
            (x1, y1), (x2, y2) = pts[0], pts[1]
            label = e['name'] if len(e['name']) <= 7 else e['name'][:6] + '…'
            s.append('<text x="%d" y="%d" fill="#555" font-size="11" text-anchor="middle">%s'
                     '</text>' % ((x1 + x2) / 2, min(y1, y2) - 6, _esc(label)))
    for n in model['nodes']:
        x, y, w, h = boxes[n['id']]
        k = n['kind']
        if k in ('start', 'end'):
            s.append('<circle cx="%d" cy="%d" r="%d" fill="%s" stroke="%s" stroke-width="%s"/>' % (
                x + w / 2, y + h / 2, w / 2, '#e8f5e9' if k == 'start' else '#ffebee',
                '#2e7d32' if k == 'start' else '#c62828', 1.5 if k == 'start' else 3))
            if n.get('name'):
                s.append('<text x="%d" y="%d" text-anchor="middle" font-size="11" fill="#333">%s'
                         '</text>' % (x + w / 2, y + h + 14, _esc(n['name'][:10])))
            continue
        if k == 'gateway':
            cx, cy = x + w / 2, y + h / 2
            s.append('<polygon points="%d,%d %d,%d %d,%d %d,%d" fill="#fff8e1" stroke="#f9a825" '
                     'stroke-width="1.5"/>' % (cx, y, x + w, cy, cx, y + h, x, cy))
            continue
        s.append('<rect x="%d" y="%d" width="%d" height="%d" rx="10" fill="%s" stroke="#1565c0" '
                 'stroke-width="%s"/>' % (x, y, w, h, '#e3f2fd' if k == 'task' else '#ede7f6',
                                          1.2 if k == 'task' else 2))
        lines = _wrap(n.get('name'))
        for j, line in enumerate(lines):
            s.append('<text x="%d" y="%d" text-anchor="middle" fill="#0d1b2a">%s</text>' % (
                x + w / 2, y + h / 2 + 4 + (j - (len(lines) - 1) / 2) * 16, _esc(line)))
    s.append('</svg>')
    return '\n'.join(s)


def validate(xml):
    """結構檢查：回傳問題清單（空＝通過）。"""
    problems = []
    try:
        root = ET.fromstring(xml.encode('utf-8'))
    except ET.ParseError as e:
        return ['XML 解析失敗：%s' % e]
    b = '{%s}' % NS['bpmn']
    process = root.find('%sprocess' % b)
    if process is None:
        return ['沒有 process']
    ids = [el.get('id') for el in root.iter() if el.get('id')]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        problems.append('id 重複：%s' % '、'.join(dup[:5]))
    kinds = set(TAGS.values())
    nodes = {el.get('id') for el in process if el.tag[len(b):] in kinds}
    flows = [el for el in process if el.tag == '%ssequenceFlow' % b]
    for f in flows:
        if f.get('sourceRef') not in nodes or f.get('targetRef') not in nodes:
            problems.append('連線 %s 的兩端不存在' % f.get('id'))
    refs = [r.text for r in process.iter('%sflowNodeRef' % b)]
    if sorted(refs) != sorted(nodes):
        problems.append('節點與泳道對不上（每個節點要恰好屬於一個泳道）')
    di = '{%s}' % NS['bpmndi']
    dc = '{%s}' % NS['dc']
    shapes = {}
    for sh in root.iter('%sBPMNShape' % di):
        bd = sh.find('%sBounds' % dc)
        if bd is not None:
            shapes[sh.get('bpmnElement')] = tuple(float(bd.get(k)) for k in ('x', 'y', 'width', 'height'))
    missing = nodes - set(shapes)
    if missing:
        problems.append('節點沒有座標：%s' % '、'.join(sorted(missing)[:5]))
    edged = {e.get('bpmnElement') for e in root.iter('%sBPMNEdge' % di)}
    if {f.get('id') for f in flows} - edged:
        problems.append('有連線沒有座標')
    boxes = [(k, shapes[k]) for k in nodes if k in shapes]
    for i, (k1, a) in enumerate(boxes):
        for k2, c in boxes[i + 1:]:
            if a[0] < c[0] + c[2] and c[0] < a[0] + a[2] and a[1] < c[1] + c[3] and c[1] < a[1] + a[3]:
                problems.append('方框重疊：%s／%s' % (k1, k2))
    return problems
