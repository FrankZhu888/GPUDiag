#!/usr/bin/env python3
# GPUDiag - GPU Diagnostic Tool for HPC GPU Server
# Written by Frank Zhu <zhuzhenquan@bytedance.com>	2025-12-25

import subprocess
import re
import sys
import json
import os
from datetime import datetime

class GPUDiagnosticTool:
    def __init__(self):
        self._check_root_requirement()

        self.report = {
            "timestamp": datetime.now().isoformat(),
            "status": "PASS",
            "issues": [],
            "version_compatibility": {},
            "drop_detection": {},
            "gpu_info": [],
            "network_info": {},
            "nvlink_status": [],
            "xid_errors": [],
            "zombie_processes": []
        }

    def _check_root_requirement(self):
        if os.getuid() != 0:
            print("="*60)
            print("ERROR: This tool MUST be run with sudo or as root.")
            print("="*60)
            sys.exit(1)

    def _run_cmd(self, cmd):
        try:
            result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return result.stdout.strip() if result.returncode == 0 else None
        except:
            return None

    def check_version_compatibility(self):
        versions = {
            "driver_version": None,
            "fabric_manager_version": None,
            "fabric_manager_service": "inactive",
            "cuda_smi_version": None,
            "nvcc_version": "NOT_FOUND"
        }

        smi_out = self._run_cmd("nvidia-smi --query-gpu=driver_version --format=csv,noheader")
        if smi_out:
            all_drivers = set(line.strip() for line in smi_out.split('\n'))
            if len(all_drivers) > 1:
                self.add_issue(f"Driver Version Mismatch: Multiple versions found {all_drivers}", level="FAIL")
            versions["driver_version"] = list(all_drivers)[0]

        cuda_smi_out = self._run_cmd("nvidia-smi")
        if cuda_smi_out:
            match = re.search(r"CUDA Version: (\d+\.\d+)", cuda_smi_out)
            if match:
                versions["cuda_smi_version"] = match.group(1)

        fm_status = self._run_cmd("systemctl is-active nvidia-fabricmanager")
        versions["fabric_manager_service"] = fm_status if fm_status else "not_installed"

        fm_out = self._run_cmd("/usr/bin/nv-fabricmanager --version")
        if fm_out:
            fm_match = re.search(r"version\s+is\s*:\s*(\d+\.\d+\.\d+)", fm_out, re.IGNORECASE)
            if fm_match:
                versions["fabric_manager_version"] = fm_match.group(1)

        nvcc_out = self._run_cmd("nvcc --version")
        if nvcc_out:
            nvcc_match = re.search(r"release (\d+\.\d+)", nvcc_out)
            if nvcc_match:
                versions["nvcc_version"] = nvcc_match.group(1)

        if versions["driver_version"] and versions["fabric_manager_service"] == "active":
            if versions["fabric_manager_version"]:
                drv_main = versions["driver_version"].split('.')[0]
                fm_main = versions["fabric_manager_version"].split('.')[0]
                if drv_main != fm_main:
                    self.add_issue(
                        f"Compatibility FAIL: Driver ({versions['driver_version']}) and Fabric Manager ({versions['fabric_manager_version']}) major version mismatch. NVLink will not function correctly.",
                        level="FAIL"
                    )
        elif versions["driver_version"] and versions["fabric_manager_service"] != "active":
            self.add_issue("Fabric Manager is NOT active.", level="FAIL")

        if versions["nvcc_version"] != "NOT_FOUND" and versions["cuda_smi_version"]:
            if float(versions["nvcc_version"]) > float(versions["cuda_smi_version"]):
                self.add_issue(
                    f"CUDA Compatibility: NVCC v{versions['nvcc_version']} is higher than the maximum supported version v{versions['cuda_smi_version']}. This may cause compilation or runtime failures.",
                    level="FAIL"
                )

        self.report["version_compatibility"] = versions

    def check_gpu_health(self):
        lspci_cmd = "lspci | grep -i 'NVIDIA' | grep -i 'VGA\\|3D' | wc -l"
        physical_count_str = self._run_cmd(lspci_cmd)
        physical_count = int(physical_count_str) if physical_count_str else 0

        query_fields = "index,name,uuid,temperature.gpu,power.draw,power.limit,pcie.link.width.current,pcie.link.width.max"
        cmd = f"nvidia-smi --query-gpu={query_fields} --format=csv,noheader,nounits"
        output = self._run_cmd(cmd)

        detected_gpus_count = 0
        if output:
            lines = output.split('\n')
            detected_gpus_count = len([l for l in lines if l.strip()])

            for line in lines:
                if not line.strip(): continue
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 8:
                    idx, name, uuid, temp, pwr, pwr_lim, curr_w, max_w = parts

                    if curr_w != max_w:
                        self.add_issue(f"GPU {idx} PCIe Bandwidth Degraded: Current x{curr_w}, Max x{max_w}", level="FAIL")

                    ecc_cmd = f"nvidia-smi -i {idx} --query-gpu=ecc.errors.uncorrected.aggregate.total --format=csv,noheader,nounits"
                    ecc_out = self._run_cmd(ecc_cmd)
                    ecc_val = int(ecc_out) if (ecc_out and ecc_out.isdigit()) else 0

                    gpu_data = {
                        "id": idx,
                        "name": name,
                        "uuid": uuid,
                        "temperature": int(temp),
                        "ecc_uncorrected": ecc_val,
                        "pcie_width": f"x{curr_w}/x{max_w}",
                        "power_draw_w": float(pwr),
                        "power_limit_w": float(pwr_lim)
                    }
                    self.report["gpu_info"].append(gpu_data)

                    if int(temp) > 85:
                        self.add_issue(f"GPU {idx} Temperature too high: {temp}C")
                    if ecc_val > 0:
                        self.add_issue(f"GPU {idx} Detected {ecc_val} UNCORRECTED ECC errors", level="FAIL")

        self.report["drop_detection"] = {
            "physical_lspci_count": physical_count,
            "driver_smi_count": detected_gpus_count
        }

        if detected_gpus_count < physical_count:
            self.add_issue(
                f"GPU DROP DETECTED: Physical Bus has {physical_count} GPUs, but Driver only sees {detected_gpus_count}.",
                level="FAIL"
            )
        elif physical_count == 0:
            self.add_issue("No NVIDIA GPUs found on PCIe bus.", level="FAIL")

    def check_zombie_processes(self):
        cmd = "nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits"
        output = self._run_cmd(cmd)
        if not output: return

        for line in output.split('\n'):
            if not line.strip(): continue
            parts = line.split(',')
            if len(parts) < 2: continue
            pid, mem = parts[0].strip(), parts[1].strip()

            if not os.path.exists(f"/proc/{pid}"):
                self.report["zombie_processes"].append({"pid": pid, "gpu_memory_usage": f"{mem} MiB"})
                self.add_issue(f"Zombie Process Detected: PID {pid} is occupying {mem}MiB vRAM but does not exist in system.", level="FAIL")

    def check_nvlink_status(self):
        topo_output = self._run_cmd("nvidia-smi nvlink -s")
        if not topo_output: return

        inactive_links = re.findall(r"Link \d+: Inactive", topo_output)
        if inactive_links:
            self.add_issue(f"Detected {len(inactive_links)} Inactive NVLink(s).", level="WARNING")

        error_output = self._run_cmd("nvidia-smi nvlink -e")
        if error_output:
            errors = re.findall(r"(Replay|Recovery|CRC|Data|Fatal)\s+:\s+([1-9]\d*)", error_output)
            for err_type, count in errors:
                self.report["nvlink_status"].append({"type": err_type, "count": count})
                self.add_issue(f"NVLink {err_type} Error: {count} counts.", level="FAIL")

    def check_xid_errors(self):
        cmd = "dmesg -T | grep -i 'NVRM: Xid'"
        out = self._run_cmd(cmd)
        if out:
            recent_logs = out.split('\n')[-5:]
            self.report["xid_errors"] = recent_logs
            for line in recent_logs:
                match = re.search(r"Xid \(PCI:.*?\): (\d+)", line)
                if match:
                    self.add_issue(f"Critical Xid {match.group(1)} found in dmesg (Potential Hardware Issue)", level="FAIL")

    def check_rdma_status(self):
        ib_out = self._run_cmd("ibv_devinfo")
        if ib_out:
            active_ports = ib_out.count("PORT_ACTIVE")
            down_ports = ib_out.count("PORT_DOWN")
            self.report["network_info"] = {"active_ports": active_ports, "down_ports": down_ports}
            if down_ports > 0:
                self.add_issue(f"Found {down_ports} RDMA ports DOWN", level="FAIL")
        else:
            ib_path = "/sys/class/infiniband"
            if os.path.exists(ib_path):
                self.report["network_info"]["adapter_count"] = len(os.listdir(ib_path))

    def add_issue(self, message, level="WARNING"):
        self.report["issues"].append({"level": level, "message": message})
        if level == "FAIL":
            self.report["status"] = "FAIL"
        elif level == "WARNING" and self.report["status"] != "FAIL":
            self.report["status"] = "WARNING"

    def run(self):
        print(f"--- Running Advanced GPU Diagnostics ---")
        self.check_version_compatibility()
        self.check_gpu_health()
        self.check_zombie_processes()
        self.check_nvlink_status()
        self.check_xid_errors()
        self.check_rdma_status()

        print(json.dumps(self.report, indent=4))
        print("\n" + "="*30)
        print(f"DIAGNOSTIC RESULT: {self.report['status']}")
        if self.report["issues"]:
            for issue in self.report["issues"]:
                print(f" - [{issue['level']}] {issue['message']}")
        else:
            print("✅ All systems appear normal.")
        print("="*30)

if __name__ == "__main__":
    GPUDiagnosticTool().run()
