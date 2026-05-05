#!/usr/bin/env bash
# render-build.sh — Custom build script for Render Native environment
# This script installs Python dependencies and Playwright browsers.

# Exit on error
set -o errexit

# Move to the backend directory where requirements.txt is located
cd backend

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browsers
# Note: On Render's native environment, we might not have permission to install system deps
# but Chromium often works with the pre-installed libraries.
playwright install chromium
