# 新功能测试指南

## 功能概述

现在btgatt-server支持3个不同的Characteristic：

1. **WiFi配置** (原有功能)
   - Service UUID: `6e400000-0000-4e98-8024-bc5b71e0893e`
   - Characteristic UUID: `6e400001-0000-4e98-8024-bc5b71e0893e`
   - 发送格式：`{"ssid":"MyWiFi","pw":"password123"}`

2. **系统信息查询** (新功能)
   - Service UUID: `6e400000-0000-4e98-8024-bc5b71e0893e`
   - Characteristic UUID: `6e400002-0000-4e98-8024-bc5b71e0893e`
   - 发送格式：
     - 查询服务状态：`{"info_type":"services"}`
       - 返回格式（紧凑JSON，无换行）：
       ```json
       {"ModelID":"3RLB01081MH","Version":"v1.08.01.08","MacAddress":"10:a5:62:8c:57:0a","Services":"z2m,otbr"}
       ```
       - 只返回启用的服务：core(matter), z2m, otbr
       - 如果服务未启用，不会出现在列表中
     - 查询系统信息：`{"info_type":"system"}`（暂未实现）

3. **MQTT服务器配置** (新功能)
   - Service UUID: `6e400000-0000-4e98-8024-bc5b71e0893e`
   - Characteristic UUID: `6e400003-0000-4e98-8024-bc5b71e0893e`
   - 发送格式：
     - 设置MQTT配置：`{"action":"set","base_topic":"zigbee2mqtt","server":"mqtt://localhost:1883","user":"username","password":"password","client_id":"optional_id"}`
       - `base_topic`, `server`, `user`, `password`: 必填
       - `client_id`: 可选，如果为空则不设置
       - 自动更新 `/opt/zigbee2mqtt/data/configuration.yaml`
       - 如果 server 包含 "localhost"，自动设置 `homeassistant.enabled: true`，否则设置为 `false`
       - 自动备份配置文件：`configuration.yaml.backup_2025-01-27-HHMMSS`
       - 自动启用并启动 zigbee2mqtt.service（后台执行）
     - 获取配置：`{"action":"get"}` （暂未实现）
     - 测试连接：``{"action":"test"}`` （暂未实现）
     - 允许设备入网（permit join）：`{"action":"permit_join"}`
       - 行为：若存在 `/usr/local/bin/supervisor`，执行 `/usr/local/bin/supervisor zigbee scan`
       - 成功：返回 `{"status":"success","message":"permit_join triggered"}`
       - 不存在：返回 `{"status":"error","message":"supervisor not found"}`
    - 停止允许入网：`{"action":"permit_join_stop"}`
      - 行为：若存在 `/usr/local/bin/supervisor`，执行 `/usr/local/bin/supervisor zigbee scan_stop`
       - 成功：返回 `{"status":"success","message":"permit_join stopped"}`
       - 不存在：返回 `{"status":"error","message":"supervisor not found"}`
    - 重置 WiFi 连接：`{"action":"resetup_wifi"}`
      - 行为：删除 NetworkManager 中的所有连接（按 UUID 删除，等价于清空 `nmcli connection` 列表）
      - 成功返回（示例）：`{"status":"success","removed":3,"attempts":3}`
      - 失败（无法列出连接）：`{"status":"error","message":"failed to list connections"}`

## 测试步骤

### 1. 启动服务器
```bash
cd /root/bluez5-utils
sudo ./tools/btgatt-server
```

### 2. 使用BLE调试工具连接
- 设备名称：`3RHUB-XXXXXX` (基于MAC地址)
- 服务UUID：`6e400000-0000-4e98-8024-bc5b71e0893e`

### 3. 测试系统信息查询
连接到Characteristic `6e400002-0000-4e98-8024-bc5b71e0893e`，发送：
```json
{"info_type":"services"}
```
期望返回（紧凑JSON格式）：
```json
{"ModelID":"3RLB01081MH","Version":"v1.08.01.08","MacAddress":"10:a5:62:8c:57:0a","Services":"z2m,otbr"}
```

说明：
- `ModelID` 和 `Version` 从 `/etc/t3r-release` 读取（MODLE 和 VERSION 字段）
- `MacAddress` 从 wlan0 获取
- `Services` 列出启用的服务：core, matter, z2m, otbr（按启用状态添加）

### 4. 测试MQTT配置
连接到Characteristic `6e400003-0000-4e98-8024-bc5b71e0893e`，发送：
```json
{"action":"set","base_topic":"zigbee2mqtt","server":"mqtt://localhost:1883","user":"thirdreality","password":"thirdreality","client_id":"my_id"}
```
或者（不包含client_id）：
```json
{"action":"set","server":"mqtt://192.168.1.100:1883","user":"demo","password":"demo123"}
```

期望返回：
```json
{"status":"success","message":"MQTT config saved"}
```

### 5. 测试允许设备入网（Permit Join）
连接到Characteristic `6e400003-0000-4e98-8024-bc5b71e0893e`，发送：
```json
{"action":"permit_join"}
```
返回：
- 成功：`{"status":"success","message":"permit_join triggered"}`
- 失败（无 supervisor）：`{"status":"error","message":"supervisor not found"}`

### 6. 停止允许入网（Permit Join Stop）
连接到Characteristic `6e400003-0000-4e98-8024-bc5b71e0893e`，发送：
```json
{"action":"permit_join_stop"}
```
返回：
- 成功：`{"status":"success","message":"permit_join stopped"}`
- 失败（无 supervisor）：`{"status":"error","message":"supervisor not found"}`

### 7. 重置 WiFi 连接（Resetup WiFi）
连接到Characteristic `6e400003-0000-4e98-8024-bc5b71e0893e`，发送：
```json
{"action":"resetup_wifi"}
```
期望返回：
```json
{"status":"success","removed":<删除成功数量>,"attempts":<尝试删除数量>}
```
说明：该操作会删除 NetworkManager 下的所有连接配置，请谨慎使用。

## 注意事项

1. 所有新功能都使用相同的BLE通信机制（分片、通知等）
2. 原有的WiFi配置功能完全不变
3. MQTT配置会自动备份原文件，支持回滚
4. 系统信息查询返回紧凑JSON格式（无换行，无空格）
5. 只有已启用的服务会出现在 Services 列表中
6. client_id 字段可选，App可以不发送以减少数据传输
7. zigbee2mqtt.service 操作在后台执行，不阻塞BLE响应
