#!/usr/bin/env bash
# render-build.sh — Custom build script for Render Native environment (Backend Root)
# Optimized: Removed install-deps to prevent root/authentication failures on Render.

# Exit on error
set -o errexit

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright Chromium browser ONLY
# We skip install-deps because Render does not allow root/sudo access during build.
playwright install chromium