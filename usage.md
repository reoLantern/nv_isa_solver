# NVIDIA ISA Solver Usage Guide

This guide describes how to use the `nv_isa_solver` toolset to reverse engineer and generate ISA documentation for NVIDIA GPUs (e.g., SM100a).

## 0. Prerequisites

Ensure that the **NVIDIA CUDA Toolkit** is installed and the following tools are in your system PATH:
- `nvcc`: NVIDIA CUDA Compiler
- `nvdisasm`: NVIDIA Disassembler
- `cuobjdump`: CUDA Object Dump Utility

You can verify the installation with:
```bash
nvcc --version
nvdisasm --version
```

## 1. Installation

First, ensure that all dependencies listed in `requirements.txt` (such as `tqdm`) are installed.

```bash
# Ensure you are in the virtual environment
pip install -r requirements.txt
```

## 2. Initial Cache Population (Brute Force)

In the `nv_isa_solver` source directory, use the `populate_cache` script to perform an initial brute-force search of the instruction space.

**Note**: This script may overwrite or reset `disasm_cache.txt`. It is recommended to use it only during the initialization phase or to back up the existing cache before use.

```bash
python3 -m nv_isa_solver.populate_cache --arch SM100a --cache_file disasm_cache.txt
```

> **Tip**: During the brute-force process, you may see disassembled instructions containing `???` (e.g., `ATOM.???0`). This is normal behavior as the script probes undefined or reserved bit patterns. These entries are typically filtered out or ignored in the final solver stage.

## 3. Cross-Mutation

Leverage the existing instruction cache to discover new valid instructions by cross-combining Opcodes and Operands, and insert them into `disasm_cache.txt`.

```bash
python3 -m nv_isa_solver.mutate_opcodes --arch SM100a --cache_file disasm_cache.txt
```

## 4. Extracting Real Instructions from CUDA Samples

Write or use existing CUDA kernel files (e.g., `test_kernel.cu`) to generate real SASS instructions via the compiler, supplementing complex instructions that brute-force enumeration cannot cover.

1.  **Compile CUDA File**:
    ```bash
    nvcc -arch=sm_100a -cubin test_kernel.cu
    ```

2.  **Export SASS Assembly**:
    ```bash
    cuobjdump --dump-sass test_kernel.cubin > sass.txt
    ```

3.  **Scan SASS and Update Cache**:
    Parse `sass.txt` and write newly discovered instruction formats into `disasm_cache.txt`.
    ```bash
    python3 -m nv_isa_solver.scan_disasm --arch SM100a sass.txt
    ```

## 5. Iterative Enhancement

Since Step 4 introduces new instruction structures and operand types, we can run the cross-mutation script again to use these new "seeds" to discover more variants.

```bash
python3 -m nv_isa_solver.mutate_opcodes --arch SM100a --cache_file disasm_cache.txt
```

*It is recommended to repeat steps 4 and 5 until the number of instructions in `disasm_cache.txt` no longer increases significantly.*

## 6. Generating Final ISA Documentation

Once the `disasm_cache.txt` file is sufficiently rich and stable, run the solver to generate the final `isa.json` and HTML visualization report.

```bash
python3 -m nv_isa_solver.instruction_solver --arch SM100a --cache_file disasm_cache.txt
```

The generated HTML report is located in the `output/` directory, and `isa.json` is located in the current directory.
