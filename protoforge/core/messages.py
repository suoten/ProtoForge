from __future__ import annotations

PROTOCOL_MESSAGES: dict[str, dict[str, str]] = {
    "s7": {
        "service_started": "S7 service started {host}:{port}",
        "service_stopped": "S7 service stopped",
        "device_created": "S7 device created {name}",
        "device_removed": "S7 device removed {id}",
        "point_written": "Write {area}{db_number} offset {offset}",
    },
    "profinet": {
        "service_started": "PROFINET IO service started {host}:{port}",
        "service_stopped": "PROFINET IO service stopped",
        "controller_connected": "IO Controller connected: {addr}",
        "ar_disconnected": "PROFINET AR[{ar_id}] disconnected, transitioning to W_ABORT",
        "cm_connect": "PROFINET CM Connect: AR[{ar_id}] established, state=W_DATA",
        "cm_release": "PROFINET CM Release: AR[{ar_id}] released",
        "cm_release_not_found": "PROFINET CM Release: AR[{ar_id}] not found",
        "alarm_sent": "PROFINET Alarm sent: {detail}",
        "io_cycle_write": "PROFINET IO cycle write {detail}",
        "io_cycle_response": "PROFINET IO cycle response {detail}",
        "device_created": "PROFINET device created: {name}",
        "device_removed": "PROFINET device removed: {id}",
        "point_written": "PROFINET write point: {detail}",
    },
    "opcua": {
        "service_started": "OPC-UA service started {host}:{port}",
        "service_stopped": "OPC-UA service stopped",
        "device_created": "OPC-UA device created: {name}",
        "device_removed": "OPC-UA device removed: {id}",
    },
    "modbus_tcp": {
        "service_started": "Modbus TCP service started {host}:{port}",
        "service_stopped": "Modbus TCP service stopped",
        "device_created": "Modbus device created: {name}",
        "device_removed": "Modbus device removed: {id}",
    },
    "http": {
        "service_started": "HTTP REST service started {host}:{port}",
        "service_stopped": "HTTP REST service stopped",
        "device_written": "HTTP write device: {detail}",
        "point_written": "HTTP write: {detail}",
        "device_created": "HTTP device created: {name}",
        "device_removed": "HTTP device removed: {id}",
    },
    "gb28181": {
        "service_started": "GB28181 SIP service started {host}:{port}",
        "service_start_failed": "SIP service start failed: {error}",
        "service_stopped": "GB28181 SIP service stopped",
        "device_created": "Device created: {name} (national_code={code})",
        "device_removed": "Device removed",
        "register_sent": "Sent REGISTER -> {target}",
        "register_failed": "REGISTER send failed: {error}",
        "sip_received": "Received SIP message <- {detail}",
        "sip_unhandled": "Unhandled SIP message: {detail}",
        "sip_error": "SIP message processing error: {error}",
        "unknown_device_message": "Unknown device MESSAGE: {detail}",
        "request_received": "Received {cmd_type} request {detail}",
        "catalog_response_sent": "Sent Catalog response (1 device)",
        "keepalive_response_sent": "Sent Keepalive response OK",
        "device_control_response_sent": "Sent DeviceControl response OK",
        "device_config_response_sent": "Sent DeviceConfig response OK",
        "xml_parse_failed": "XML parse failed",
        "register_success": "Device registered successfully! Server confirmed",
        "register_refresh_success": "Registration refresh successful",
        "auth_register_sent": "Sent auth REGISTER (Digest auth, nonce={nonce})",
        "auth_register_failed": "Auth REGISTER send failed: {error}",
        "invite_no_match": "INVITE but no matching device: {detail}",
        "invite_received": "Received INVITE (video request) <- {detail}",
        "invite_ok_sent": "Sent INVITE 200 OK + SDP (media: {detail})",
        "ack_received_streaming": "ACK received, starting RTP video stream -> {detail}",
        "rtp_start_failed": "RTP stream start failed: {error}",
        "ack_no_media": "ACK received but no valid media address",
        "bye_received": "BYE received, stopping RTP video stream",
        "bye_ok_sent": "Sent BYE 200 OK",
    },
    "ethercat": {
        "service_started": "EtherCAT service started {host}:{port}",
        "service_stopped": "EtherCAT service stopped",
    },
}

CONFIG_DESCRIPTIONS: dict[str, str] = {
    "listen_address": "Listen address",
    "listen_port": "Listen port",
    "s7_rack": "Rack number",
    "s7_slot": "Slot number",
    "s7_port_desc": "S7 port (default 102)",
    "tcp_tunnel_address": "Listen address (TCP tunnel mode)",
    "tcp_tunnel_port": "TCP tunnel port",
    "profinet_device_name": "PROFINET device name (DCP identification)",
    "vendor_id": "Vendor ID",
    "dcp_ip_address": "DCP Identify response IP address",
    "subnet_mask": "Subnet mask",
    "default_gateway": "Default gateway",
    "tcp_tunnel_mode_desc": "TCP tunnel mode - supports DCP discovery/CM connection/AR state machine/RT cyclic data/Alarm notification",
    "security_mode": "Security mode",
    "security_policy": "Security policy",
    "server_cert_path": "Server certificate path (PEM format, leave empty for auto-generation)",
    "server_key_path": "Server private key path (PEM format, leave empty for auto-generation)",
    "cert_store_dir": "Certificate storage directory (default ~/.protoforge/opcua_certs)",
    "http_api_prefix": "API path prefix",
    "sip_server_id": "SIP server ID (20-digit code)",
    "srtp_enabled": "Enable SRTP encryption",
    "srtp_crypto_suite": "SRTP crypto suite",
}


def msg(protocol: str, key: str, **kwargs) -> str:
    template = PROTOCOL_MESSAGES.get(protocol, {}).get(key, key)
    if kwargs:
        try:
            return template.format(**kwargs)
        except KeyError:
            return template
    return template


def desc(key: str) -> str:
    return CONFIG_DESCRIPTIONS.get(key, key)
