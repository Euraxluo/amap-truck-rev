#!/usr/bin/env python3
"""amap-truck-openapi — 高德官方货车路径规划 v4 OpenAPI 兼容层

把逆向出的 APP 私有通道 (m5.amap.com/ws/mapapi/navigation/auto/) 封装成
官方《物流服务API·货车路径规划基础版》的 drop-in 替换:

  官方:  GET https://restapi.amap.com/v4/direction/truck?parameters
  本地:  GET http://127.0.0.1:18964/v4/direction/truck?parameters   ← 同参数同返回结构

参数映射 (官方 → APP 私有):
  origin,destination → fromX/fromY/toX/toY
  waypoints          → viapoints (官方";"分隔 → APP"|"分隔, ≤16 点)
  strategy(1-13)     → policy2 位掩码 (官方枚举 → APP 位组合)
  size(1-4国标)      → v_size + 按档位补默认 v_length/v_load/v_weight
  height,width,load,weight,axis → v_height/v_width/v_load/v_weight/v_axis
  province+number    → carplate (省份汉字+号码拼接, 政策限行判定)
  cartype(0/1/2)     → v_type (0普通/1纯电/2混动)
  nosteps,showpolyline → 透传控制响应裁剪
  key                → 忽略 (兼容官方调用方式)

返回: 官方 v4 schema {errcode:0, errmsg:"OK", data:{count, route:{origin,
destination, paths:[{distance,duration,strategy,tolls,toll_distance,
restriction,steps:[{instruction,orientation,road,distance,duration,
polyline,action,assistant_action,tmcs}]}]}}}
坐标系: GCJ-02 (与官方一致)
"""
import hashlib, json, logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import urllib.request, urllib.parse

CH = 'amap7a'
AOS_KEY = 'xnaEwInMxaMQ2m0cw6Y1bDm7ns0YVxYS9v7JlC8I'
UPSTREAM = 'https://m5.amap.com/ws/mapapi/navigation/auto/'

log = logging.getLogger('truck-openapi')

# ---------- 官方 strategy(1-13) → APP policy2 位掩码 ----------
# 官方语义: 1躲避拥堵 2不走高速 3避免收费 4躲避拥堵+不走高速 5避免收费+不走高速
#           6躲避拥堵+避免收费 7躲避拥堵+避免收费+不走高速 8高速优先 9躲避拥堵+高速优先
#           10无路况速度优先 11高德推荐 12无路况+不走高速 13不考虑路况距离优先
# APP policy2 位: 2躲避拥堵 4避免收费 8距离优先 16高速优先 32不走高速
STRATEGY_MAP = {
    '1': '2', '2': '32', '3': '4', '4': '2|32', '5': '4|32',
    '6': '2|4', '7': '2|4|32', '8': '16', '9': '2|16',
    '10': '0', '11': '0', '12': '32', '13': '8',
}

# size 国标档位 → (默认车长m, 默认总重t, 默认载重t)
SIZE_DEFAULTS = {
    '1': (3.5, 1.8, 0.5),    # 微型: ≤3.5m, 总质量≤1800kg
    '2': (5.0, 4.0, 2.0),    # 轻型: <6m, 总质量<4500kg
    '3': (7.0, 10.0, 5.0),   # 中型: ≥6m, 4500-12000kg
    '4': (13.0, 31.0, 20.0), # 重型: ≥6m, ≥12000kg
}

ORIENTATION = {'1': '北', '2': '东北', '3': '东', '4': '东南', '5': '南',
               '6': '西南', '7': '西', '8': '西北'}


def call_app_route(origin, dest, waypoints=None, size='2', height=None, width=None,
                   load=None, weight=None, axis=None, plate='京A12345', policy2='0'):
    fx, fy = origin
    tx, ty = dest
    sign = hashlib.md5(f'{CH}{fx}{fy}{tx}{ty}@{AOS_KEY}'.encode()).hexdigest()
    dl, dw, dl_ = SIZE_DEFAULTS.get(size, SIZE_DEFAULTS['2'])
    params = {
        'fromX': fx, 'fromY': fy, 'toX': tx, 'toY': ty,
        'output': 'json', 'channel': CH, 'sign': sign,
        'use_truck_engine': '1', 'v_type': '1', 'v_size': size,
        'v_height': f'{float(height) if height else 1.6:.1f}',
        'v_width': f'{float(width) if width else 2.5:.2f}',
        'v_length': f'{dl:.1f}',
        'v_load': f'{float(load) if load else dw:.1f}',
        'v_weight': f'{float(weight) if weight else dl_:.1f}',
        'v_axis': axis or '2',
        'carplate': plate,
        'policy2': policy2,
    }
    if waypoints:
        # 官方 waypoints: "x,y;x,y" → APP viapoints: "x,y|x,y"
        pts = [w.strip() for w in waypoints.replace('|', ';').split(';') if w.strip()]
        if len(pts) > 16:
            raise ValueError('waypoints 最多16个')
        params['viapoints'] = '|'.join(pts)
    data = '&'.join(f'{k}={urllib.parse.quote(str(v))}' for k, v in params.items()).encode()
    req = urllib.request.Request(
        f'{UPSTREAM}?sloc_precision=1.0&sloc_speed=10&t=carroute&invoker=plan',
        data=data, method='POST', headers={'User-Agent': 'Android'})
    return json.load(urllib.request.urlopen(req, timeout=25))


def to_v4(raw, origin, dest, nosteps=False, showpolyline=True):
    """APP 私有响应 → 官方 v4 schema"""
    if str(raw.get('code')) != '1':
        return {'errcode': int(raw.get('code') or 0) or -1,
                'errmsg': raw.get('message') or 'UPSTREAM_ERROR',
                'errdetail': raw.get('message', '')}
    dists = [float(x) for x in str(raw.get('distance', '')).split(',') if x]
    durs = [float(x) for x in str(raw.get('drivetime', '') or '').split(',') if x]
    costs = [float(x) for x in str(raw.get('cost', '') or '').split(',') if x]
    paths = []
    path_lists = raw.get('path_list', [])
    for i, pl in enumerate(path_lists):
        steps = []
        for s in (pl.get('path') or []):
            if not isinstance(s, dict):
                continue
            steps.append({
                'instruction': s.get('text', ''),
                'orientation': s.get('orientation', ''),
                'road': s.get('name', ''),
                'distance': int(s.get('length', 0) or 0),
                # APP 不分段返回耗时, 按距离均摊总耗时
                'duration': int(durs[i] * int(s.get('length', 0) or 0) / dists[i]) if i < len(durs) and i < len(dists) and dists[i] else 0,
                'polyline': s.get('polyline', '') if showpolyline else '',
                'action': s.get('action', ''),
                'assistant_action': s.get('assistant_action', ''),
                'tmcs': [{'distance': t.get('length', 0), 'status': t.get('status', 0),
                          'polyline': t.get('polyline', '') if showpolyline else ''}
                         for t in (s.get('tmcs') or []) if isinstance(t, dict)],
            })
        if nosteps:
            steps = []
        paths.append({
            'distance': int(dists[i]) if i < len(dists) else 0,
            'duration': int(durs[i]) if i < len(durs) else 0,
            'strategy': raw.get('strategy', '0'),
            'tolls': costs[i] if i < len(costs) and costs[i] else 0,
            'toll_distance': 0,
            'restriction': 0,
            'steps': steps,
        })
    return {
        'errcode': 0, 'errmsg': 'OK',
        'data': {'count': len(paths),
                 'route': {'origin': ','.join(origin), 'destination': ','.join(dest),
                           'paths': paths}},
    }


def parse_ll(v):
    p = v.split(',')
    if len(p) != 2:
        raise ValueError(f'坐标格式应为 lon,lat: {v}')
    return p[0].strip(), p[1].strip()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path.rstrip('/') != '/v4/direction/truck':
            self.send_error(404, 'use /v4/direction/truck'); return
        q = parse_qs(u.query)
        try:
            origin = parse_ll(q['origin'][0])
            dest = parse_ll(q['destination'][0])
        except (KeyError, ValueError) as e:
            self._json({'errcode': 10001, 'errmsg': 'INVALID_PARAMS', 'errdetail': str(e)})
            return
        size = q.get('size', ['2'])[0]
        if size not in SIZE_DEFAULTS:
            self._json({'errcode': 10001, 'errmsg': 'size must be 1-4'})
            return
        strategy = q.get('strategy', ['1'])[0]
        policy2 = STRATEGY_MAP.get(strategy, '0')
        province = q.get('province', ['京'])[0]
        number = q.get('number', ['A12345'])[0]
        plate = f'{province}{number}' if q.get('number') else '京A12345'
        try:
            raw = call_app_route(
                origin, dest,
                waypoints=q.get('waypoints', [None])[0],
                size=size,
                height=q.get('height', [None])[0],
                width=q.get('width', [None])[0],
                load=q.get('load', [None])[0],
                weight=q.get('weight', [None])[0],
                axis=q.get('axis', [None])[0],
                plate=plate, policy2=policy2)
        except Exception as e:
            self._json({'errcode': 10002, 'errmsg': 'UPSTREAM_ERROR', 'errdetail': str(e)})
            return
        out = to_v4(raw, origin, dest,
                    nosteps=q.get('nosteps', ['0'])[0] == '1',
                    showpolyline=q.get('showpolyline', ['1'])[0] == '1')
        self._json(out)

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    srv = ThreadingHTTPServer(('127.0.0.1', 18964), Handler)
    log.info('amap-truck-openapi on http://127.0.0.1:18964/v4/direction/truck (官方v4兼容)')
    srv.serve_forever()
