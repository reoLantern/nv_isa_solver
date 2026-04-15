#!/usr/bin/env python3
"""Cross-variant merge: fix constant fields that vary across variants of the same instruction.

Problem: The per-variant solver treats each variant independently. When FSWZADD
has 176 variants (each with a different swizzle pattern), the solver marks the
swizzle bits as "constant" because they don't change when you flip other bits
within that single variant. But across variants, those bits DO change — meaning
they're actually a modifier/operand field, not a constant.

Solution: Group variants by base instruction name. For each group, find bit
positions that are marked as "constant" in every variant but have different
values across variants. Reclassify those bits as "modifier" fields.

Usage:
    python3 -m nv_isa_solver.cross_variant_merge isa.json -o isa_merged.json

    Or as a library:
    from nv_isa_solver.cross_variant_merge import merge_cross_variant
    merged = merge_cross_variant(isa_data)
"""

import json
import sys
from collections import defaultdict
from argparse import ArgumentParser
from pathlib import Path


def _extract_constant_bits(entry):
    """Extract which bits are marked constant and their values."""
    const_mask = 0   # which bits are constant
    const_vals = 0   # the constant values
    for r in entry['ranges']['ranges']:
        if r['type'] == 'constant' and r.get('constant') is not None:
            for b in range(r['start'], r['start'] + r['length']):
                const_mask |= (1 << b)
                if (r['constant'] >> (b - r['start'])) & 1:
                    const_vals |= (1 << b)
    return const_mask, const_vals


def _find_varying_constant_bits(variants, opcode_bits=12):
    """Find bits marked as constant in all variants but with different values.

    Excludes opcode region [0:opcode_bits) since those are legitimately constant
    per variant (they ARE the opcode).
    """
    if len(variants) < 2:
        return []

    # Get constant mask/values for each variant
    entries = [(key, entry, *_extract_constant_bits(entry)) for key, entry in variants]

    # Common constant bits = intersection of all constant masks
    common_const = entries[0][2]
    for _, _, mask, _ in entries[1:]:
        common_const &= mask

    # Find bits that are common-constant but have varying values
    varying = []
    for b in range(opcode_bits, 128):  # skip opcode region
        if not (common_const & (1 << b)):
            continue
        vals = set((vals >> b) & 1 for _, _, _, vals in entries)
        if len(vals) > 1:
            varying.append(b)

    return varying


def _find_contiguous_segments(bits):
    """Group bit positions into contiguous segments."""
    if not bits:
        return []
    segments = []
    start = bits[0]
    prev = bits[0]
    for b in bits[1:]:
        if b != prev + 1:
            segments.append((start, prev - start + 1))
            start = b
        prev = b
    segments.append((start, prev - start + 1))
    return segments


def _reclassify_ranges(ranges_list, varying_segments):
    """Replace constant ranges that overlap with varying segments with modifier ranges."""
    new_ranges = []
    varying_set = set()
    for seg_start, seg_len in varying_segments:
        for b in range(seg_start, seg_start + seg_len):
            varying_set.add(b)

    for r in ranges_list:
        if r['type'] != 'constant':
            new_ranges.append(r)
            continue

        # Check if this constant range overlaps with varying bits
        r_bits = set(range(r['start'], r['start'] + r['length']))
        overlap = r_bits & varying_set
        if not overlap:
            new_ranges.append(r)
            continue

        # Split: keep non-varying constant parts, convert varying parts to modifier
        non_varying = r_bits - varying_set
        all_bits = sorted(r_bits)

        # Reconstruct constant value for non-varying bits
        cursor = r['start']
        for b in all_bits:
            if b in varying_set:
                # This bit becomes part of a modifier
                if cursor < b and any(bb in non_varying for bb in range(cursor, b)):
                    # Emit the preceding non-varying constant
                    const_val = 0
                    for bb in range(cursor, b):
                        if bb in non_varying:
                            bit_offset = bb - r['start']
                            const_val |= ((r['constant'] >> bit_offset) & 1) << (bb - cursor)
                    new_ranges.append({
                        'type': 'constant', 'start': cursor,
                        'length': b - cursor, 'constant': const_val,
                        'operand_index': None, 'group_id': None, 'name': None,
                    })
                cursor = b
            else:
                pass

        # Now emit segments
        # Simpler approach: rebuild from scratch
        new_ranges_for_r = []
        i = r['start']
        while i < r['start'] + r['length']:
            if i in varying_set:
                # Start of a modifier segment
                seg_start = i
                while i < r['start'] + r['length'] and i in varying_set:
                    i += 1
                new_ranges_for_r.append({
                    'type': 'modifier', 'start': seg_start,
                    'length': i - seg_start,
                    'operand_index': None, 'group_id': None, 'name': None,
                    'constant': None,
                })
            else:
                # Start of a constant segment
                seg_start = i
                const_val = 0
                bit_idx = 0
                while i < r['start'] + r['length'] and i not in varying_set:
                    bit_offset = i - r['start']
                    const_val |= ((r['constant'] >> bit_offset) & 1) << bit_idx
                    i += 1
                    bit_idx += 1
                new_ranges_for_r.append({
                    'type': 'constant', 'start': seg_start,
                    'length': i - seg_start, 'constant': const_val,
                    'operand_index': None, 'group_id': None, 'name': None,
                })

        # Replace the flat new_ranges entry with the split version
        new_ranges.pop()  # remove the raw append from earlier
        new_ranges.extend(new_ranges_for_r)

    return sorted(new_ranges, key=lambda r: r['start'])


def merge_cross_variant(isa_data):
    """Main merge function. Returns (merged_data, merge_report)."""
    # Group by base instruction name
    by_name = defaultdict(list)
    for key, entry in isa_data.items():
        base = entry['parsed']['base_name']
        by_name[base].append((key, entry))

    merge_report = {
        'total_variants': len(isa_data),
        'instructions_with_varying_constants': 0,
        'total_reclassified_bits': 0,
        'details': [],
    }

    merged = {}
    for inst_name, variants in by_name.items():
        varying = _find_varying_constant_bits(variants)

        if not varying:
            # No merge needed
            for key, entry in variants:
                merged[key] = entry
            continue

        segments = _find_contiguous_segments(sorted(varying))
        merge_report['instructions_with_varying_constants'] += 1
        merge_report['total_reclassified_bits'] += len(varying)
        merge_report['details'].append({
            'instruction': inst_name,
            'variant_count': len(variants),
            'varying_bits': len(varying),
            'segments': [{'start': s, 'length': l} for s, l in segments],
        })

        # Reclassify each variant's ranges
        for key, entry in variants:
            new_entry = dict(entry)
            new_ranges = entry['ranges']['ranges']
            # Simple approach: rebuild ranges for varying bits
            rebuilt = _reclassify_ranges(new_ranges, segments)
            new_entry['ranges'] = dict(entry['ranges'])
            new_entry['ranges']['ranges'] = rebuilt
            merged[key] = new_entry

    # After reclassification, merge variants that now have identical layouts
    # (same field types/positions, only opcode and modifier values differ)
    def layout_fingerprint(entry):
        fields = []
        for r in entry['ranges']['ranges']:
            fields.append((r['type'], r['start'], r['length']))
        return tuple(sorted(fields))

    fp_groups = defaultdict(list)
    for key, entry in merged.items():
        base = entry['parsed']['base_name']
        fp = layout_fingerprint(entry)
        fp_groups[(base, fp)].append(key)

    merge_report['unique_layouts_after_merge'] = len(fp_groups)
    merge_report['layout_groups_with_multiple_variants'] = sum(
        1 for keys in fp_groups.values() if len(keys) > 1
    )

    # Count how many variants can be collapsed
    collapsible = sum(len(keys) - 1 for keys in fp_groups.values() if len(keys) > 1)
    merge_report['collapsible_variants'] = collapsible
    merge_report['effective_unique_encodings'] = len(merged) - collapsible

    # Step 2: Seed deduplication
    # For each (base_name, layout) group, keep only one representative variant.
    # The representative is the one with the simplest disasm (shortest string).
    deduped = {}
    dedup_map = {}  # representative_key -> list of merged keys
    for (base, fp), keys in fp_groups.items():
        # Pick the representative: shortest disasm text, or first alphabetically
        best_key = min(keys, key=lambda k: (len(merged[k].get('disasm', '')), k))
        deduped[best_key] = merged[best_key]
        if len(keys) > 1:
            dedup_map[best_key] = keys

    merge_report['deduped_variants'] = len(deduped)
    merge_report['dedup_groups'] = len(dedup_map)
    merge_report['dedup_details'] = []
    for rep_key, all_keys in sorted(dedup_map.items(),
                                     key=lambda x: -len(x[1]))[:15]:
        base = merged[rep_key]['parsed']['base_name']
        merge_report['dedup_details'].append({
            'representative': rep_key,
            'instruction': base,
            'merged_count': len(all_keys),
            'merged_keys': all_keys[:5] + (['...'] if len(all_keys) > 5 else []),
        })

    return merged, deduped, merge_report


def main():
    ap = ArgumentParser(description=__doc__)
    ap.add_argument('input', help='input isa.json')
    ap.add_argument('-o', '--output', help='output merged isa.json')
    ap.add_argument('--report', help='output merge report JSON')
    args = ap.parse_args()

    with open(args.input) as f:
        isa_data = json.load(f)

    merged, deduped, report = merge_cross_variant(isa_data)

    print(f"=== Step 1: Cross-variant constant reclassification ===")
    print(f"  Input variants: {report['total_variants']}")
    print(f"  Instructions with varying constants: {report['instructions_with_varying_constants']}")
    print(f"  Total reclassified bits: {report['total_reclassified_bits']}")

    if report['details']:
        print(f"  Top reclassified:")
        for d in sorted(report['details'], key=lambda x: -x['varying_bits'])[:5]:
            segs = ', '.join(f"[{s['start']}:{s['start']+s['length']}]" for s in d['segments'])
            print(f"    {d['instruction']:<20s} {d['variant_count']:3d} variants, "
                  f"{d['varying_bits']:2d} bits: {segs}")

    print(f"\n=== Step 2: Seed deduplication ===")
    print(f"  Unique layouts: {report['unique_layouts_after_merge']}")
    print(f"  Collapsible variants: {report['collapsible_variants']}")
    print(f"  After dedup: {report['deduped_variants']} variants "
          f"(from {report['total_variants']})")

    if report['dedup_details']:
        print(f"  Top merged groups:")
        for d in report['dedup_details'][:8]:
            print(f"    {d['instruction']:<20s} {d['merged_count']:3d} variants → 1")

    # Count unique instructions
    unique_insts = set(deduped[k]['parsed']['base_name'] for k in deduped)
    print(f"\n=== Summary ===")
    print(f"  {report['total_variants']} raw variants → {report['deduped_variants']} "
          f"unique encodings ({len(unique_insts)} instructions)")

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(deduped, f, indent=2, ensure_ascii=False)
        print(f"\n  Wrote {args.output}")

    if args.report:
        with open(args.report, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"  Wrote {args.report}")


if __name__ == '__main__':
    main()
