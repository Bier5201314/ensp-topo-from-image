---
name: ensp-topo-from-image
description: Reconstruct Huawei eNSP .topo files from network topology PNG images by genuinely rebuilding devices, links and annotations. Use when the user asks to build, 复刻, fix, or validate .topo files from topology screenshots involving AR2220, S5700, S3700, PC, Server, interface labels, IP/protocol annotations, or a standard answer .topo.
---

# eNSP Topology From Image

## Non-negotiable Rules

1. **Reconstruct, never copy.** Build the topology from what the image shows. Do NOT make `test.py` (or any output) copy a standard answer `.topo` byte-for-byte. A standard answer is only a reference for structure/coordinates and a validation target, never the output source.
2. **Preserve Chinese exactly.** Never translate Chinese annotations to English "to avoid mojibake". The mojibake has a real cause and a real fix (see Encoding).
3. **Bind interfaces in `<lines>`, not in text.** Interface identity lives in `srcIndex`/`tarIndex`, never only in a `<txttip>`.

## Encoding: the real fix for mojibake (读这段)

eNSP `.topo` files declare `<?xml version="1.0" encoding="UNICODE" ?>` but store Chinese as **GBK bytes**, not UTF-8. Verified: the bytes `\xd7\xd3\xcd\xf8...` equal `"子网掩码设置".encode("gbk")`.

Consequences:
- Writing the file with `encoding="utf-8"` makes eNSP show Chinese as mojibake. This is why translating to English was a wrong workaround.
- **Always write the file with `encoding="gbk"`** and keep the `encoding="UNICODE"` string in the XML header untouched.
- To parse/validate in Python, read with `encoding="gbk"`, then for an XML parser replace the header token `UNICODE` with `gbk` (or `utf-8`) in-memory only.

```python
Path("network.topo").write_text(xml_text, encoding="gbk")   # correct
# NOT encoding="utf-8"
```

## Distinguishing S5700 vs S3700 (and other models)

Do not rely on the icon. Decide with this ordered checklist; stop at the first that resolves:

1. **Explicit model text** printed by the device name in the image → use it verbatim.
2. **Access port type on links.** eNSP S3700 exposes FastEthernet access ports labelled `Ethernet 0/0/x`; S5700 exposes only Gigabit ports labelled `GE 0/0/x`.
   - Any switch whose PC/host-facing link is labelled `Ethernet 0/0/x` → **S3700** (Layer 2 access).
   - A switch whose links are all `GE 0/0/x` → **S5700** (Layer 3).
3. **Layer-3 role.** A switch with a `vlanif` IP, acting as a gateway, or doing inter-VLAN routing / OSPF / RIP → **S5700**. A switch that only bridges hosts inside VLANs with no L3 IP → **S3700**.
4. **Topology tier.** Core/aggregation switch feeding other switches/routers → usually **S5700**; edge switch fanning out to PCs → usually **S3700**.
5. **Still ambiguous?** Ask the user rather than guessing.

Record the deciding evidence in your reasoning (e.g. "LSW1 has `Ethernet 0/0/1` to PC1 → S3700").

## Interface model layouts (slot17 main board)

Use the correct port structure per model, and map visible labels to zero-based indices:

| Model | Ports | Label → index |
|-------|-------|---------------|
| AR2220 | GE0/0/0, GE0/0/1, GE0/0/2 | `GE 0/0/0`→0, `GE 0/0/1`→1, `GE 0/0/2`→2 |
| S5700 | GE0/0/1..24 | `GE 0/0/1`→0, `GE 0/0/2`→1, ... |
| S3700 | Eth0/0/1..22 + GE0/0/1..2 | `Ethernet 0/0/1`→0, ...; `GE 0/0/1`→22 |
| PC / Server | one Ethernet | `Ethernet 0/0/1`→0 |

Read the interface label written next to each cable end in the image and translate it to the index — do not assume sequential order.

## Workflow

1. Read the PNG. List every device (name, model via checklist above, approximate canvas position), every link with the interface label at BOTH ends, and every annotation box (IP, protocol, VLAN, title) with its text and location.
2. If a standard answer `.topo` is provided, read it to calibrate coordinate scale and confirm model/interface choices — but still generate your own output.
3. Write a spec and run the generator: `python scripts/build_topo.py spec.json network.topo`. See [scripts/build_topo.py](scripts/build_topo.py) for the spec format. The generator handles GBK encoding, GUIDs/MACs, slot structure, and `interfacePair` geometry so you only supply image-derived facts.
4. Validate (next section). Fix and re-run until all checks pass.

## Validation checklist

Run these before reporting done:

- [ ] File written with `encoding="gbk"`; header still says `encoding="UNICODE"`.
- [ ] Re-read with `encoding="gbk"`; every Chinese annotation decodes to the exact original text (no mojibake, no translation).
- [ ] XML parses (in-memory swap `UNICODE`→`utf-8` for the parser only).
- [ ] Device count and each device's model match the image.
- [ ] Link count matches; each `<line>` connects the intended two device IDs.
- [ ] Each `<interfacePair>` `srcIndex`/`tarIndex` matches the interface labels in the image.
- [ ] No interface identity lives only inside a `<txttip>`.
- [ ] Each annotation's coordinates sit next to the device/link it describes (not clustered generically).
- [ ] PC/Server IP, mask, gateway match visible labels.
- [ ] S5700/S3700 decisions are backed by the checklist evidence, not the icon.

## Using a standard answer correctly

- Read it to learn coordinate scale (canvas units ≈ 100 per grid cell in observed files), model choices, and interface indexing conventions.
- Diff your generated output against it to find mistakes, then fix your spec.
- It is fine to end up structurally very close, but the output must be produced by your generator from your spec — not a byte copy.
