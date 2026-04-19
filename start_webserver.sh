#!/bin/bash
# App webserver entry point
# This script is run by the app-webserver systemd service
# It should start your web server on 0.0.0.0:8080
# and handle auto-reloading when code changes are detected
#
# Example (Python):
#   exec python3 -m http.server 8080 --bind 0.0.0.0
#
# Example (Node):
#   exec npx nodemon --watch . --exec 'node server.js'

echo 'start_webserver.sh: No webserver configured yet'
echo 'Edit this file to launch your app on port 8080'
sleep infinity
