// frida hook 高德地图 17.02.0.2010 — 一网打尽算路签名三件套
// 1) ServerkeyNative.sign / amapEncodeBinaryV2  (libserverkey.so, URL sign + xxTea body 加密)
// 2) pu5.f → SecurityGuard virtualV2Sign         (x-sign/x-mini-wua 请求头)
// 3) AosURLBuilder.parse / kx4.b                  (完整参数表 + 最终 URL)
// 用法: frida -U -f com.autonavi.minimap -l hook_all.js --no-pause
//       然后在 APP 里发起一次货车导航算路

Java.perform(function () {
  var log = function (tag, obj) { console.log('[' + tag + '] ' + JSON.stringify(obj)); };

  // ---- 1. libserverkey JNI: sign / key / channel / xxTea ----
  try {
    var SK = Java.use('com.autonavi.jni.server.aos.ServerkeyNative');
    SK.sign.implementation = function (b) {
      var r = this.sign(b);
      try { log('sign', { input: Java.use('java.lang.String').$new(b), out: r }); } catch (e) { }
      return r;
    };
    SK.getAosKey.implementation = function () {
      var r = this.getAosKey(); log('aosKey', { key: r }); return r;
    };
    SK.getAosChannel.implementation = function () {
      var r = this.getAosChannel(); log('aosChannel', { ch: r }); return r;
    };
    SK.amapEncodeBinaryV2.overload('[B').implementation = function (b) {
      var r = this.amapEncodeBinaryV2(b);
      log('xxTeaV2', { plainLen: b.length, encLen: r ? r.length : -1,
        plainHead: Java.use('java.lang.String').$new(b, 0, Math.min(b.length, 400), 'UTF-8') });
      return r;
    };
  } catch (e) { console.log('[!] ServerkeyNative hook fail: ' + e); }

  // ---- 2. SecurityGuard 虚拟签名 (x-sign 头) ----
  try {
    var P = Java.use('defpackage.pu5');
    P.f.implementation = function (a, b, c, d, e) {
      var r = this.f(a, b, c, d, e);
      log('virtualV2Sign', { body: String(a).substring(0, 400), ts: b, out: r });
      return r;
    };
  } catch (e2) { console.log('[!] pu5.f hook fail (类名可能混淆): ' + e2); }

  // ---- 3. 完整 URL + 参数 ----
  try {
    var B = Java.use('com.amap.bundle.network.request.param.builder.AosURLBuilder');
    B.parse.implementation = function (p, m, ent, z) {
      var r = this.parse(p, m, ent, z);
      log('urlBuilder', { url: this.getUrl(), params: this.getParams() });
      return r;
    };
  } catch (e3) { console.log('[!] AosURLBuilder hook fail: ' + e3); }

  // ---- 4. 兜底: 抓最终 HTTP 发送 ----
  try {
    var AR = Java.use('com.amap.bundle.aosservice.request.AosPostRequest');
    AR.addReqParam.overload('java.lang.String', 'java.lang.String').implementation = function (k, v) {
      console.log('[param] ' + k + '=' + v);
      return this.addReqParam(k, v);
    };
  } catch (e4) { }
});
