# 高德 APP 货车导航私有协议逆向 — 阶段成果

目标: 把高德 APP 的货车导航算路变成可独立调用的 HTTP 接口。
APK: com.autonavi.minimap 17.02.0.2010 (大陆版, 应用宝镜像)

## 已还原的协议链路 (静态分析完成)

### 1. 算路请求 URL (Java 层, com/amap/bundle/drivecommon/request/RouteCarParamUrlWrapper.java)

```java
@URLBuilder.Path(
  builder = AosURLBuilder.class,
  host = ConfigerHelper.DRIVE_AOS_URL_KEY,   // = "drive_aos_url" → e02.a() 映射 "aos.m5" → https://m5.amap.com/
  sign = {"fromX","fromY","toX","toY"},       // 签名只覆盖起终点坐标
  url  = "ws/mapapi/navigation/auto/?"
)
public class RouteCarParamUrlWrapper implements ParamEntity
```

Java 层统一入口 `ws/mapapi/navigation/auto/?`（不分小车/货车），货车通过参数区分:
- `use_truck_engine = 1` (货车) / 2 (摩托车) / 0 (小车)   ← defpackage/q22.java:392-398,594
- `v_type` = 车辆类型 (DriveUtil.getCarTypeByVtype: 1=truck 11=motor)
- `carplate` = 车牌 (货车: DriveUtil.getTruckCarPlateNumber())
- `v_height/v_width/v_length/v_load/v_weight/v_axis/v_size` = 车辆尺寸 (小车时置 0)
- `fromX/fromY/toX/toY` = 起终点经纬度 (GCJ-02, 字符串)
- `viapoints` = 途经点 `x1,y1;x2,y2` 格式
- `policy2` = 算路偏好 (DriveUtil.getTruckRoutingChoice() 等)
- `contentoptions` = 位标志 (16384=沿途城市, 512=?, 128=离线数据)
- `output=bin` (二进制响应) — defpackage/q22.java:367

Native 层(libamaphorus.so fcn.00c798ec)按 routeMode 二次分发到:
- `/ws/shield/truck/route?sloc_precision=1.0&sloc_speed=10&t=carroute&invoker=` (货车算路)
- `/ws/shield/truck/routeguide` (货车导航引导)
- `/ws/shield/truck/cloudsection` (货车云路段)
- `/ws/shield/motor-route/route` (摩托车)
- `ws/transfer/navigation/auto/` (小车云算路)
- host: aos.nvg → https://nvg.amap.com/ (defpackage/e02.java:73)

### 2. 公共参数 (com/amap/bundle/network/request/param/NetworkParam.getNetworkParamMap)

div, siv, dip, dic, diu, adiu, adiu_extras, diu2(mac), diu3(isn), dai, cifa,
sa, session, appstartid, stepid, channel, uid, spm, tid, dib, client_network_class,
dibv, BID_F, aeTraffic, ct_id, oaid, buildABI(arm64-v8a), i18n_zone/lang/tz_offset/switch,
pageSessionId, pcdInfo...
channel 来自 serverkey.getAosChannel() (native)

### 3. 签名 (关键门槛)

```
sign = Sign.getSign( concat(sign数组各字段值) )
     = serverkey.sign( (getAosChannel() + signStr + "@" + getAosKey()).getBytes() )
     → ServerkeyNative.sign(bytes)  → libserverkey.so (JNI, 自实现MD5变体)
```
- libserverkey.so 内混淆常量: MD5/MessageDigest 线索, 内嵌 key 片段
  (xaMQ2m0c9v7JlC8I / 10057148 / 3fcf2117c10f44c6 等交错编码)
- 车辆导航 sign 只覆盖 fromX+fromY+toX+toY 四个字段值直接串接

### 4. 响应格式
- output=bin → 自定义二进制 (native TBT 解析, 走 RouteRegister/nativeGetAgentService)
- output=json → JSON (Java 层解析)

## 已验证 (curl 实测 2026-11-02)

- https://nvg.amap.com/ws/shield/truck/route 存活: GET→"Request method not supported"(code 11), POST 缺参→"Params error"(code 3) — 服务在, 参数名未对
- https://m5.amap.com/ws/mapapi/navigation/auto/ 同样存活, 同样 "Params error"
- 两端点均不验 sign 就先校验参数 → 参数对后才会碰到 sign 墙

## 下一步 (动态阶段)
1. 模拟器/真机 + frida hook:
   - hook ServerkeyNative.sign / Sign.getSign 直接取签名(绕过算法还原)
   - hook AosURLBuilder.parse / kx4.b dump 完整参数表
   - mitmproxy 抓 m5/nvg 完整请求(含真实 diu/channel/公共参数)
2. 用抓到的参数模板 + frida rpc 签名服务, 封装本地 HTTP 代理
3. 若 sign 可离线还原(疑似自定义MD5), 直接脱离设备实现

## 工件
- work/jadx/out/  反编译 Java 源 (42616 文件)
- work/apktool/out/  解包资源
- work/raw/lib/arm64-v8a/  native 库 (73 个)
- work/disasm_cloud_route_router.txt  fcn.00c798ec 全反汇编
- work/disasm_truck_param_builder.txt fcn.00c7afb0 全反汇编
