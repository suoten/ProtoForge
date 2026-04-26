-- ProtoForge联调集成配置表
CREATE TABLE IF NOT EXISTS integration_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 初始化默认配置
INSERT OR IGNORE INTO integration_config (key, value, description) VALUES
    ('edgelite_url', '', 'EdgeLite网关地址'),
    ('edgelite_username', 'admin', 'EdgeLite用户名'),
    ('edgelite_password', '', 'EdgeLite密码'),
    ('channel_type', 'http', '通道类型: http/websocket'),
    ('heartbeat_interval', '30', '心跳间隔(秒)'),
    ('max_retries', '3', '最大重试次数'),
    ('backhaul_enabled', 'false', '是否启用数据回传'),
    ('backhaul_rate_limit', '10', '回传限流(次/秒)'),
    ('backhaul_buffer_size', '1000', '回传缓存大小');

-- ProtoForge告警联动规则表
CREATE TABLE IF NOT EXISTS alarm_reaction_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id TEXT NOT NULL UNIQUE,
    source_device_id TEXT DEFAULT '',
    alarm_severity TEXT DEFAULT '',
    action TEXT NOT NULL DEFAULT 'stop_device',
    target_device_id TEXT DEFAULT '',
    action_params TEXT DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
