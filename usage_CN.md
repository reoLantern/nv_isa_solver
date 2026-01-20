# NVIDIA ISA Solver 使用指南

本指南介绍如何使用 `nv_isa_solver` 工具集对 NVIDIA GPU（例如 SM100a）进行逆向工程并生成 ISA 文档。

## 0. 前置条件

确保已安装 **NVIDIA CUDA Toolkit**，并且以下工具位于系统 PATH 中：
- `nvcc`：NVIDIA CUDA Compiler
- `nvdisasm`：NVIDIA Disassembler
- `cuobjdump`：CUDA Object Dump Utility

您可以通过以下命令验证安装：
```bash
nvcc --version
nvdisasm --version
```

## 1. 安装

首先，确保 `requirements.txt` 中列出的所有依赖项（如 `tqdm`）均已安装。强烈建议使用虚拟环境以避免"externally-managed-environment"错误。

```bash
# 创建虚拟环境（如果尚未创建）
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 安装依赖项
pip install -r requirements.txt
```

## 2. 初始缓存填充（暴力破解）

在 `nv_isa_solver` 源目录中，使用 `populate_cache` 脚本对指令空间进行初始暴力搜索。

**注意**：此脚本可能会覆盖或重置 `disasm_cache.txt`。建议仅在初始化阶段使用，或在使用前备份现有缓存。

```bash
python3 -m nv_isa_solver.populate_cache --arch SM100a --cache_file disasm_cache.txt
```

> **提示**：在暴力破解过程中，您可能会看到包含 `???` 的反汇编指令（例如 `ATOM.???0`）。这是正常行为，因为脚本会探测未定义或保留的位模式。这些条目通常会在最终的求解器阶段被过滤或忽略。

## 3. 交叉变异

利用现有指令缓存，通过交叉组合 Opcodes 和 Operands 来发现新的有效指令，并将其插入到 `disasm_cache.txt` 中。

```bash
python3 -m nv_isa_solver.mutate_opcodes --arch SM100a --cache_file disasm_cache.txt
```

> **注意**：如果遇到 `ValueError: not enough values to unpack` 错误，这意味着您的 `disasm_cache.txt` 包含格式错误的行。最新版本的 `disasm_utils.py` 包含自动跳过这些行的修复。请确保您的代码是最新的。

## 4. 从 CUDA Samples 中提取真实指令

编写或使用现有的 CUDA kernel 文件（例如 `test_kernel.cu`），通过编译器生成真实的 SASS 指令，补充暴力破解枚举无法覆盖的复杂指令。

1. **编译 CUDA 文件**：
    ```bash
    nvcc -arch=sm_100a -cubin test_kernel.cu
    ```

2. **导出 SASS 汇编**：
    ```bash
    cuobjdump --dump-sass test_kernel.cubin > sass.txt
    ```

3. **扫描 SASS 并更新缓存**：
    解析 `sass.txt` 并将新发现的指令格式写入 `disasm_cache.txt`。
    ```bash
    python3 -m nv_isa_solver.scan_disasm --arch SM100a sass.txt
    ```
> **注意**：对于 SM100a（Blackwell）架构，`nvdisasm` 输出可能包含 `.headerflags` 行或其他可能混淆解析器的元数据。`disasm_utils.py` 已更新以严格过滤输出行，仅处理包含 `/*` 注释的行。

## 5. 迭代优化

由于步骤 4 引入了新的指令结构和操作数类型，我们可以再次运行交叉变异脚本，使用这些新的"种子"来发现更多变体。

```bash
python3 -m nv_isa_solver.mutate_opcodes --arch SM100a --cache_file disasm_cache.txt
```

*建议重复步骤 4 和 5，直到 `disasm_cache.txt` 中的指令数量不再显著增加。*

## 6. 生成最终的 ISA 文档

一旦 `disasm_cache.txt` 文件足够丰富和稳定，运行求解器以生成最终的 `isa.json` 和 HTML 可视化报告。

```bash
python3 -m nv_isa_solver.instruction_solver --arch SM100a --cache_file disasm_cache.txt
```

生成的 HTML 报告位于 `output/` 目录中，`isa.json` 位于当前目录中。

