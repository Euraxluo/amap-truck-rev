#!/usr/bin/env python3
"""amap-truck-proxy — 高德APP货车导航私有接口代理

逆向还原 (APK 17.02.0.2010):
  端点:   POST https://m5.amap.com/ws/mapapi/navigation/auto/
  签名:   sign = MD5("amap7a" + fromX + fromY + toX + toY + "@" + AosKey)
  AosKey: "xnaEwInMxaMQ2m0cw6Y1bDm7ns0YVxYS9v7JlC8I"  (libserverkey.so,
          APK 官方签名校验和 0x3576 分支返回; 非官方签名返回 "unknown")
  货车:   use_truck_engine=1 + v_type/v_height/v_width/v_length/v_load/
          v_weight/v_axis/v_size/carplate

本地接口:
  GET /route?from=lon,lat&to=lon,lat[&via=lon,lat;lon,lat]
           [&height=]&[width=]&[length=]&[load=]&[weight=]&[axis=]
           [&plate=]&[policy=][&raw=1]
  返回: {code, distance_m, duration_s, toll_yuan, paths:[{name,text,length,cameras}...], raw}

坐标: GCJ-02 (高德坐标系)
"""
import hashlib, json, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import urllib.request, urllib.parse

CH = 'amap7a'
AOS_KEY = 'xnaEwInMxaMQ2m0cw6Y1bDm7ns0YVxYS9v7JlC8I'
UPSTREAM = 'https://m5.amap.com/ws/mapapi/navigation/auto/'

DEFAULT_TRUCK = dict(v_type='1', v_height='3.5', v_width='2.5', v_length='13.0',
                     v_load='31.0', v_weight='20.0', v_axis='3', v_size='2')


def amap_route(fx, fy, tx, ty, truck=None, plate='京A12345', policy='32', via=None):
    sign = hashlib.md5(f'{CH}{fx}{fy}{tx}{ty}@{AOS_KEY}'.encode()).hexdigest()
    params = {'fromX': fx, 'fromY': fy, 'toX': tx, 'toY': ty,
              'output': 'json', 'channel': CH, 'sign': sign,
              'use_truck_engine': '1', 'carplate': plate, 'policy2': policy}
    t = dict(DEFAULT_TRUCK); t.update(truck or {})
    params.update(t)
    if via:
        params['viapoints'] = via  # "x1,y1;x2,y2"
    data = '&'.join(f'{k}={urllib.parse.quote(str(v))}' for k, v in params.items()).encode()
    req = urllib.request.Request(
        f'{UPSTREAM}?sloc_precision=1.0&sloc_speed=10&t=carroute&invoker=plan',
        data=data, method='POST',
        headers={'User-Agent': 'Android'})
    return json.load(urllib.request.urlopen(req, timeout=20))


def summarize(raw):
    def floats(v):
        return [float(x) for x in str(v).split(',')] if v else []
    dists = floats(raw.get('distance'))
    durs = [int(x) for x in str(raw.get('drivetime', '') or '').split(',') if x]
    costs = floats(raw.get('cost'))
    out = {
        'code': raw.get('code'),
        'distance_m': dists[0] if dists else None,
        'all_distances_m': dists,
        'duration_s': durs[0] if durs else None,
        'all_durations_s': durs,
        'toll_yuan': costs[0] if costs else None,
    }
    paths = []
    for pl in raw.get('path_list', []):
        steps = [{'name': s.get('name', ''), 'text': s.get('text', ''),
                  'length_m': int(s.get('length', 0) or 0),
                  'cameras': s.get('cameras', [])}
                 for s in (pl.get('path') or []) if isinstance(s, dict)]
        paths.append(steps)
    out['steps'] = paths[0] if len(paths) == 1 else paths
    return out


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path != '/route':
            self.send_error(404); return
        q = parse_qs(u.query)
        try:
            frm = q['from'][0].split(','); to = q['to'][0].split(',')
        except (KeyError, ValueError):
            self.send_error(400, 'from/to required as lon,lat'); return
        truck = {k: q[k][0] for k in ('v_type', 'v_height', 'v_width', 'v_length',
                                      'v_load', 'v_weight', 'v_axis', 'v_size') if k in q}
        raw = amap_route(frm[0].strip(), frm[1].strip(), to[0].strip(), to[1].strip(),
                         truck=truck, plate=q.get('plate', ['京A12345'])[0],
                         policy=q.get('policy', ['32'])[0],
                         via=q.get('via', [None])[0])
        body = raw if q.get('raw') else summarize(raw)
        body_b = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body_b)))
        self.end_headers()
        self.wfile.write(body_b)

    def log_message(self, *a):
        pass


if __name__ == '__main__':
    srv = ThreadingHTTPServer(('127.0.0.1', 18964), Handler)
    print('amap-truck-proxy on http://127.0.0.1:18964/route')
    srv.serve_forever()
