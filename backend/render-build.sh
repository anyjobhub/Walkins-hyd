#!/usr/bin/env bash
# render-build.sh — Custom build script for Render Native environment (Backend Root)

# Exit on error
set -o errexit

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browsers
# Note: On Render's native environment, we might not have permission to install system deps
# but Chromium often works with the pre-installed libraries.
playwright install chromium
