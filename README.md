# GPUDiag - HPC GPU Server Diagnostic Tool

**GPUDiag** is a Python-based diagnostic utility designed for High-Performance Computing (HPC) environments running NVIDIA Data Center GPUs (e.g., A100, H100, H800). It performs a comprehensive health check on the GPU ecosystem, identifying common hardware, software, and configuration issues that cause training instability.

## 🚀 Key Features

GPUDiag automates the manual troubleshooting process by checking:

*   **GPU Drop Detection**: Compares physical PCIe devices (`lspci`) against the driver-recognized count (`nvidia-smi`).
*   **Version Compatibility**:
    *   Verifies NVIDIA Driver vs. Fabric Manager version consistency (crucial for NVLink).
    *   Checks if NVCC version exceeds the driver's supported CUDA version.
*   **Hardware Health**:
    *   Detects PCIe link width degradation (e.g., running at x8 instead of x16).
    *   Monitors Temperature (>85°C) and Uncorrected ECC errors.
*   **NVLink Integrity**: Checks for inactive links and accumulates error counters (CRC, Recovery, Fatal).
*   **Process Hygiene**: Identifies "Zombie Processes" (PIDs holding VRAM that no longer exist in the OS).
*   **Critical Logs**: Scans `dmesg` for recent critical Xid errors (GPU hardware failures).
*   **Network Status**: Checks RDMA/InfiniBand port status (`ibv_devinfo`).

## 📋 Prerequisites

*   **OS**: Linux (Tested on Ubuntu/CentOS).
*   **Python**: Python 3.6+.
*   **Permissions**: **Root privileges are required** (to access `dmesg`, `lspci`, and system services).
*   **Dependencies**:
    *   `nvidia-smi`
    *   `lspci` (pciutils)
    *   `ibv_devinfo` (infiniband-diags) - *Optional, for RDMA check*

## 🛠️ Installation

Simply clone the repository or download the script directly. No complex pip installation is required.

```bash
git clone https://github.com/YourUsername/GPUDiag.git
cd GPUDiag
chmod +x GPUDiag.py
```

## Usage
Run the tool using sudo. The tool outputs a JSON report followed by a human-readable summary.
```
sudo ./gpudiag.py
```

## Output Example
<img width="566" height="833" alt="截屏2025-12-25 11 50 43" src="https://github.com/user-attachments/assets/5b7854f8-1d7b-46e1-90f0-08e751312098" />
<img width="504" height="743" alt="截屏2025-12-25 11 51 10" src="https://github.com/user-attachments/assets/a9c6f624-748e-4711-b9b8-fe8d5d955c08" />


## 🔍 Diagnostic Logic

| Category | Check Item | Pass Criteria | Fail/Warning Condition |
| :--- | :--- | :--- | :--- |
| **System** | **Root Privileges** | `os.getuid() == 0` | Script aborts if not run with `sudo`. |
| **Hardware** | **GPU Drop Detection** | `lspci` count == `nvidia-smi` count | **FAIL**: Driver sees fewer GPUs than physically installed on PCIe bus. |
| **Hardware** | **PCIe Health** | PCIe Current Width == Max Width (e.g., x16) | **FAIL**: Link degradation detected (e.g., operating at x8 or x4). |
| **Hardware** | **Thermals & ECC** | Temp ≤ 85°C, Uncorrected ECC == 0 | **WARNING**: Temp > 85°C<br>**FAIL**: Uncorrected ECC errors > 0. |
| **Software** | **Fabric Manager** | Service Active & Version matches Driver | **FAIL**: Service inactive OR Major version mismatch (e.g., Driver 535 vs FM 525). |
| **Software** | **CUDA Compatibility** | `nvcc` version ≤ Driver supported CUDA version | **FAIL**: Compiler version is too new for the installed driver. |
| **Interconnect**| **NVLink Status** | Link Status != "Inactive", Error Counts == 0 | **WARNING**: Inactive links detected.<br>**FAIL**: CRC/Recovery/Fatal errors > 0. |
| **Process** | **Zombie Processes** | All GPU-consuming PIDs exist in `/proc` | **FAIL**: Process holding VRAM found in `nvidia-smi` but does not exist in OS. |
| **Logs** | **Xid Errors** | No recent "NVRM: Xid" in `dmesg` | **FAIL**: Critical hardware error patterns (Xid) found in kernel logs. |
| **Network** | **RDMA Status** | InfiniBand ports state == "PORT_ACTIVE" | **FAIL**: RDMA ports found in "DOWN" state. |
