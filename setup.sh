#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
NS3_ROOT="$(cd .. && pwd)"
if [[ ! -f "$NS3_ROOT/ns3" ]]; then
  echo "Place the cloned project folder directly inside your ns-3.45 folder before running setup.sh."
  exit 1
fi
python3 -m zipfile -e measured-data.zip .
sudo apt update
sudo apt install -y python3-venv
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -c 'import lab_backend; lab_backend.install_source(lab_backend.default_ns3_root()); print("New C++ source installed; original udp-fec.cc is unchanged.")'
echo "Setup complete. Start with: bash launch.sh"
