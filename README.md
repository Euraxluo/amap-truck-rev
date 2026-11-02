# amap-truck-rev
目标: 逆向高德地图安卓APP的货车导航私有协议, 还原成可调用的HTTP接口
(承接 osm-routing-service 调研结论: restapi v4/direction/truck 需商务开通, APP 走私有通道)

## 布局
- tools/   逆向工具 (jadx/apktool/ghidra/frida...)
- apk/     高德 APK 存放
- work/    反编译/解包产物 (gitignore)
- captures/ 抓包产物
- scripts/ frida hook / 请求重放脚本
- docs/    调研笔记
