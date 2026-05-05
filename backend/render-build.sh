#!/usr/bin/env bash
# render-build.sh — Custom build script for Render Native environment (Backend Root)

# Exit on error
set -o errexit

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browsers and their system dependencies
# Using --with-deps to ensure all OS-level libraries are present
playwright install --with-deps chromium