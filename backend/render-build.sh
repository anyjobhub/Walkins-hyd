#!/usr/bin/env bash
# render-build.sh — Custom build script for Render Native environment

# Exit on error
set -o errexit

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Playwright and Selenium are no longer needed as we use Apify API.
echo "Build completed successfully (Apify Integration Ready)"