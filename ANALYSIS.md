# NV ISA Solver: Data Quality Analysis

## Solver Approach

The solver works by single-bit flipping: for each of the 128 bits in an instruction, flip it and observe how nvdisasm output changes. Based on the response:
- Output changes (different operand/modifier) → operand/modifier bit
- nvdisasm refuses to decode → opcode bit
- No change → constant bit (value preserved from seed)

## Data Quality Issues Found

### Issue 1: Sampling Redundancy (Fixed)
**Problem**: `scan_disasm.py` collects different assembly strings as different seeds. For instructions like FSWZADD with 176 swizzle patterns, each pattern becomes a separate variant even though the field layout is identical.

**Impact**: 1636 raw variants → 1163 after dedup (473 redundant).

**Fix**: `cross_variant_merge.py` Step 2 — layout fingerprint dedup.

### Issue 2: Cross-Variant Constant Mislabeling (Fixed)
**Problem**: Solver runs per-variant. If a bit has value X in variant A and value Y in variant B, but both are marked "constant" within their own variant (because flipping doesn't change nvdisasm output for that variant), the bit is actually a modifier/operand field.

**Impact**: 136 instructions, 324 bits reclassified from constant → modifier.

**Fix**: `cross_variant_merge.py` Step 1 — cross-variant constant analysis.

### Issue 3: Reserved/Unused Bits (Unfixed, Low Priority)
**Observation**: Average 30.2b per instruction marked as constant=0 in non-opcode regions. These are likely genuinely unused (NV reserved bits), but some might be modifier fields where:
- The seed value is 0 (default)
- Flipping to 1 produces an illegal instruction (nvdisasm refuses)
- Solver can't distinguish "reserved" from "modifier with narrow valid range"

**Potential fix**: Multi-value fuzzing (try 0→1, 0→2, 0→3...) instead of single-bit flip. Requires re-running nvdisasm.

### Issue 4: Embedded Config Constants (Unfixed, Medium Priority)  
**Observation**: Average 20.6b per instruction marked as non-zero constant in non-opcode regions. Example: LDC has bit[24:36]=255, which might be a constant bank index operand rather than a true encoding constant.

**Potential fix**: Cross-instruction analysis — if the same bit region has different non-zero values across instructions of the same base_name, it's likely an operand. Already partially addressed by Issue 2 fix.

### Issue 5: Single-Bit Flip Blind Spots (Unfixed, Low Priority)
**Problem**: Some multi-bit fields have sparse valid value sets. Example: a 2-bit field with valid values {0, 3} (binary 00, 11). Flipping any single bit produces an invalid value (01 or 10), so solver marks both bits as "opcode/constant."

**Potential fix**: Multi-bit combinatorial fuzzing. Expensive (2^k trials per k-bit region).

## Summary Statistics (SM100a / Blackwell)

| Metric | Before Cleaning | After Cleaning |
|--------|----------------|----------------|
| Raw variants | 1636 | 1636 |
| Unique layouts | 1007 | 1163 |
| After dedup | 1636 | **1163** |
| Avg constant bits (non-opcode) | 50.8b | ~47b (estimated) |
| Reclassified bits | — | 324 |

## Field Type Distribution (per variant, 128b)

| Type | Avg bits | % |
|------|----------|---|
| constant (opcode + reserved) | 62.8b | 49.1% |
| operand | 33.1b | 25.9% |
| scheduling (stall/yield/r-bar/w-bar/b-mask/reuse) | 21.0b | 16.4% |
| modifier | 4.6b | 3.6% |
| predicate | 4.0b | 3.1% |
| flag + operand_flag + operand_modifier | 2.5b | 1.9% |

## Tools

- `cross_variant_merge.py`: Two-step cleaning (constant reclassification + seed dedup)
  ```bash
  python3 -m nv_isa_solver.nv_isa_solver.cross_variant_merge isa.json -o isa_cleaned.json --report report.json
  ```
