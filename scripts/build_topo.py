#!/usr/bin/env python3
"""Generate a Huawei eNSP .topo file from a JSON topology spec.

This performs genuine reconstruction from image-derived facts. It is NOT a
copier: you describe the devices, links and annotations you saw in the PNG,
and this script emits a correctly structured, GBK-encoded .topo that eNSP
opens. Never feed it a standard answer to copy.

Usage:
    python build_topo.py spec.json network.topo

Spec format (spec.json):
{
  "devices": [
    {"name": "AR1", "model": "AR2220", "x": 173, "y": 173},
    {"name": "LSW1", "model": "S3700", "x": 173, "y": 373},
    {"name": "PC1", "model": "PC", "x": 173, "y": 473,
     "ip": "192.168.30.2", "mask": "255.255.255.0", "gateway": "192.168.30.1"}
  ],
  "links": [
    {"a": "AR1", "a_idx": 1, "b": "PC1", "b_idx": 0}
  ],
  "txttips": [
    {"x": 373, "y": 287, "text": "OSPF子网掩码设置3"},
    {"x": 245, "y": 433, "text": "172.16.12.2/24\n172.16.12.1/24"}
  ]
}

Notes
- model: one of AR2220, S5700, S3700, PC, Server (extend MODEL_SLOTS if needed).
- x/y: device center in eNSP canvas units (~100 per grid cell). Read positions
  from the image; keep relative layout faithful.
- a_idx/b_idx: zero-based interface index. Map the interface LABEL at each cable
  end (e.g. "GE 0/0/1", "Ethernet 0/0/1") to an index using the table in
  SKILL.md. PC/Server side is 0.
- txttips text keeps Chinese verbatim; use "\n" for line breaks.
"""
import json
import random
import sys
from pathlib import Path

# Interface layout per model on the main board (slot17), as ordered cards.
# Each tuple is (interfacename, count). Indices are assigned in order.
MODEL_SLOTS = {
    "AR2220": [("GE", 1), ("GE", 2)],        # GE0/0/0 ; GE0/0/1-2  -> idx 0,1,2
    "S5700":  [("GE", 24)],                   # GE0/0/1-24            -> idx 0..23
    "S3700":  [("Ethernet", 22), ("GE", 2)],  # Eth access + GE uplink-> idx 0..23
    "PC":     [("Ethernet", 1)],
    "Server": [("Ethernet", 1)],
}

# system_mac vendor prefixes seen in eNSP files.
MAC_PREFIX = {
    "AR2220": "00-E0-FC",
    "S5700": "4C-1F-CC",
    "S3700": "4C-1F-CC",
    "PC": "54-89-98",
    "Server": "54-89-98",
}

ICON_RADIUS = 35  # half icon size used to place cable attach points


def make_guid():
    return "%08X-%04X-4%03X-%04X-%012X" % (
        random.getrandbits(32),
        random.getrandbits(16),
        random.getrandbits(12),
        random.getrandbits(16),
        random.getrandbits(48),
    )


def make_mac(model):
    prefix = MAC_PREFIX.get(model, "54-89-98")
    return prefix + "-" + "-".join("%02X" % random.getrandbits(8) for _ in range(3))


def xml_escape(text):
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def pc_settings(dev):
    ip = dev.get("ip", "192.168.1.1")
    mask = dev.get("mask", "255.255.255.0")
    gateway = dev.get("gateway", "192.168.1.254")
    mac = dev["_mac"]
    return (
        f" -simpc_ip {ip}  -simpc_mask {mask}  -simpc_gateway {gateway}  "
        f"-simpc_mac {mac}  -simpc_mc_dstip 0.0.0.0  -simpc_mc_dstmac 00-00-00-00-00-00  "
        "-simpc_dns1 0.0.0.0  -simpc_dns2 0.0.0.0  -simpc_ipv6 ::  -simpc_prefix 128  "
        "-simpc_gatewayv6 ::  -simpc_dhcp_state 0  -simpc_dhcpv6_state 0  "
        "-simpc_dns_auto_state 0  -simpc_igmp_version 1  -simpc_group_ip_start 0.0.0.0  "
        "-simpc_src_ip_start 0.0.0.0  -simpc_group_num 0  -simpc_group_step 0  "
        "-simpc_src_num 0  -simpc_src_step 0  -simpc_type MODE_IS_INCLUDE "
    )


def device_xml(dev, com_port):
    slots = MODEL_SLOTS[dev["model"]]
    x, y = float(dev["x"]), float(dev["y"])
    edit_left = int(x) + 27
    edit_top = int(y) + 54
    is_endpoint = dev["model"] in ("PC", "Server")

    settings = xml_escape(pc_settings(dev)) if is_endpoint else ""
    com = "0" if is_endpoint else str(com_port)

    interfaces = "\n".join(
        f'                <interface sztype="Ethernet" interfacename="{name}" count="{count}" />'
        for name, count in slots
    )
    return (
        f'        <dev id="{dev["_id"]}" name="{dev["name"]}" poe="0" '
        f'model="{dev["model"]}" settings="{settings}" system_mac="{dev["_mac"]}" '
        f'com_port="{com}" bootmode="0" cx="{x:.6f}" cy="{y:.6f}" '
        f'edit_left="{edit_left}" edit_top="{edit_top}">\n'
        '            <slot number="slot17" isMainBoard="1">\n'
        f"{interfaces}\n"
        "            </slot>\n"
        "        </dev>"
    )


def attach_point(src, dst):
    sx, sy = float(src["x"]), float(src["y"])
    dx, dy = float(dst["x"]), float(dst["y"])
    vx, vy = dx - sx, dy - sy
    dist = (vx * vx + vy * vy) ** 0.5 or 1.0
    return sx + vx / dist * ICON_RADIUS, sy + vy / dist * ICON_RADIUS


def line_xml(link, by_name):
    a = by_name[link["a"]]
    b = by_name[link["b"]]
    ax, ay = attach_point(a, b)
    bx, by_ = attach_point(b, a)
    return (
        f'        <line srcDeviceID="{a["_id"]}" destDeviceID="{b["_id"]}">\n'
        f'            <interfacePair lineName="Copper" srcIndex="{link["a_idx"]}" '
        f'srcBoundRectIsMoved="0" srcBoundRect_X="{ax:.6f}" srcBoundRect_Y="{ay:.6f}" '
        'srcOffset_X="0.000000" srcOffset_Y="0.000000" '
        f'tarIndex="{link["b_idx"]}" tarBoundRectIsMoved="0" '
        f'tarBoundRect_X="{bx:.6f}" tarBoundRect_Y="{by_:.6f}" '
        'tarOffset_X="0.000000" tarOffset_Y="0.000000" />\n'
        "        </line>"
    )


def txttip_xml(tip):
    text = tip["text"].replace("\r\n", "\n")
    content = xml_escape(text).replace("\n", "&#x0D;&#x0A;")
    left = int(tip["x"])
    top = int(tip["y"])
    right = left + tip.get("width", 110)
    bottom = top + tip.get("height", 17 + 18 * text.count("\n"))
    return (
        f'        <txttip left="{left}" top="{top}" right="{right}" bottom="{bottom}" '
        f'content="{content}" fontname="Consolas" fontstyle="0" '
        f'editsize="{tip.get("editsize", 100)}" txtcolor="-16777216" '
        'txtbkcolor="-7278960" charset="1" />'
    )


def build(spec):
    by_name = {}
    for dev in spec["devices"]:
        if dev["model"] not in MODEL_SLOTS:
            raise ValueError(f"Unknown model {dev['model']!r}; extend MODEL_SLOTS.")
        dev["_id"] = make_guid()
        dev["_mac"] = dev.get("system_mac", make_mac(dev["model"]))
        by_name[dev["name"]] = dev

    lines = ['<?xml version="1.0" encoding="UNICODE" ?>', '<topo version="1.3.00.100">']
    lines.append("    <devices>")
    com_port = 2000
    for dev in spec["devices"]:
        lines.append(device_xml(dev, com_port))
        if dev["model"] not in ("PC", "Server"):
            com_port += 1
    lines.append("    </devices>")

    lines.append("    <lines>")
    for link in spec.get("links", []):
        lines.append(line_xml(link, by_name))
    lines.append("    </lines>")

    lines.append("    <shapes />")

    lines.append("    <txttips>")
    for tip in spec.get("txttips", []):
        lines.append(txttip_xml(tip))
    lines.append("    </txttips>")

    lines.append("</topo>")
    return "\n".join(lines) + "\n"


def main(argv):
    if len(argv) != 3:
        print("Usage: python build_topo.py spec.json network.topo", file=sys.stderr)
        return 2
    spec = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    xml_text = build(spec)
    # Chinese must be stored as GBK bytes even though the header says UNICODE.
    Path(argv[2]).write_text(xml_text, encoding="gbk")
    print(f"{argv[2]} generated: {len(spec['devices'])} devices, "
          f"{len(spec.get('links', []))} links, {len(spec.get('txttips', []))} txttips.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
