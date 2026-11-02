# 动态抓取操作手册 (模拟器 + frida)

## 环境就绪后执行顺序

```bash
export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
export JAVA_HOME=/opt/homebrew/opt/openjdk

# 1. 创建并启动 AVD (android-34 google_apis arm64)
$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager create avd \
  -n amap34 -k 'system-images;android-34;google_apis;arm64-v8a' -d pixel_6
$ANDROID_HOME/emulator/emulator -avd amap34 -no-window -no-audio -no-boot-anim \
  -writable-system -gpu swiftshader_indirect &

# 2. 等 boot
$ANDROID_HOME/platform-tools/adb wait-for-device
$ANDROID_HOME/platform-tools/adb shell 'while [ "$(getprop sys.boot_completed)" != 1 ]; do sleep 2; done; echo BOOTED'

# 3. 装 frida-server (root shell: google_apis 镜像默认 adb root 可用)
adb root
adb push tools/frida-server-17.16.4-android-arm64 /data/local/tmp/fs
adb shell 'chmod 755 /data/local/tmp/fs && /data/local/tmp/fs &'

# 4. 装高德
adb install apk/amap_17.02.0.2010.apk

# 5. 起 mitmproxy (可选, https 抓包需装 CA + 可能绕 pinning)
mitmproxy --listen-port 8080 --set block_global=false
adb shell settings put global http_proxy 192.168.x.x:8080   # 宿主机IP

# 6. hook 全家桶
frida -U -f com.autonavi.minimap -l scripts/hook_all.js --no-pause

# 7. APP 内操作: 设置→导航设置→货车→填车牌/车型(重型 厴2.5宽3高9.6长25载)→
#    搜目的地→路线→货车算路。hook 输出:
#    [sign]       → URL sign 原语 (AosChannel+fromX+fromY+toX+toY+@+AosKey)
#    [aosKey]/[aosChannel] → 常量, 一次拿到永久可用
#    [xxTeaV2]    → body 加密前明文 (完整参数表!)
#    [virtualV2Sign] → x-sign 头
#    [urlBuilder] → 最终 URL+params
```

## 拿到原语后的封装路线

1. **重放代理** (最快): Python/Go 服务收外部请求 → 组参数 → 拿 xxTea 加密模板+sign → 转发 nvg/m5 → 解 bin 响应。sign 若只依赖坐标, 每次算路需重新签名 → 要么内嵌算法, 要么保留一台 Android 设备做 "签名服务" (frida rpc)。
2. **算法离线还原** (彻底): r2/Ghidra 逆 libserverkey.so 的 sign (疑似自定义MD5) 与 amapEncodeBinaryV2 (xxTea, 已知算法, 关键是 key)。key 可从 hook [aosKey] 直接观察是否恒定。
3. 注意: SecurityGuard x-sign (阿里 libsgmain) 若服务端强制校验, 只能走 frida rpc 桥 (设备常驻)。

## 风险
- 高德风控: diu/adiu 设备指纹, 短期重放 OK, 长期可能触发验证
- libsgmain 反调试: frida 检测 (ptrace/线程名), 必要时换 gadget 注入或 magisk hide
