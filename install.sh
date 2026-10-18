#!/bin/bash
# digenx installer — /usr/local/bin me symlinks banata hai
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
sudo ln -sf "$DIR/digenx-bin" /usr/local/bin/digenx
sudo ln -sf "$DIR/digenx-mcp-bin" /usr/local/bin/digenx-mcp
echo "Installed: digenx, digenx-mcp"
digenx --version
