#!/usr/bin/env bash
set -euo pipefail
sudo apt update
sudo apt install -y git cmake ninja-build g++ qtbase5-dev
TASK_NETANIM_DIR="$HOME/ns3-work/netanim"
if [[ -e "$TASK_NETANIM_DIR" ]]; then
  echo "Existing directory found: $TASK_NETANIM_DIR"
  for TASK_NETANIM_BIN in "$TASK_NETANIM_DIR/build/netanim" "$TASK_NETANIM_DIR/build/bin/netanim"; do
    if [[ -x "$TASK_NETANIM_BIN" ]]; then
      echo "Launch: $TASK_NETANIM_BIN"
      exit 0
    fi
  done
  echo "Keeping it; build it with the commands in README.md."
  exit 0
fi
git clone --depth 1 https://gitlab.com/nsnam/netanim.git "$TASK_NETANIM_DIR"
cmake -S "$TASK_NETANIM_DIR" -B "$TASK_NETANIM_DIR/build" -G Ninja
cmake --build "$TASK_NETANIM_DIR/build" -j 2
for TASK_NETANIM_BIN in "$TASK_NETANIM_DIR/build/netanim" "$TASK_NETANIM_DIR/build/bin/netanim"; do
  if [[ -x "$TASK_NETANIM_BIN" ]]; then
    echo "Launch: $TASK_NETANIM_BIN"
    exit 0
  fi
done
echo "Build completed, but the executable was not found at either expected location." >&2
exit 1
