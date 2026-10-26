#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
APP=".cache/Rodent Watch Camera.app"
mkdir -p "$APP/Contents/MacOS" .cache/swift-modules
cp native/Info.plist "$APP/Contents/Info.plist"
xcrun swiftc native/Capture.swift -O -module-cache-path .cache/swift-modules \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker native/Info.plist \
  -o "$APP/Contents/MacOS/RodentWatchCapture"
codesign --force --sign - "$APP"
printf 'Built %s\n' "$APP"
