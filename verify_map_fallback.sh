#!/bin/bash
# Queued verification (created 2026-06-11): prove the maplibre map-init try/catch
# (commit b66372b) lets the dashboard survive a synchronous map-init throw.
#
# It forces a synchronous throw at map init (bad container = same throw-class as a
# WebGL failure), screenshots the Grondwater tab under SwiftShader, and reverts
# app.js on exit (even on failure). If the Vooruitblik projection chart renders in
# /tmp/mapfail_crop.png while the map is dead, the fallback works.
#
# Run from a FRESH session (this session's sandbox blocked all browser launches
# after ~12 chromium runs). After running, Read /tmp/mapfail_crop.png.
set -u
cd /mnt/nvme/workspaces/waterlab || exit 1
APP=dashboard/app.js
cp "$APP" /tmp/app.js.preverify
trap 'cp /tmp/app.js.preverify "$APP"; echo "[app.js reverted to good state]"' EXIT

echo "[1] dashboard health: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/)"
curl -s -o /dev/null --max-time 60 http://127.0.0.1:8000/api/grondwater/projection   # warm cache

echo "[2] inject synchronous throw at map init"
sed -i 's/container: "map",/container: "FORCED-BAD-CONTAINER-VERIFY",/' "$APP"
grep -q 'FORCED-BAD-CONTAINER' "$APP" && echo "    bad container live (served from disk)" || { echo "    inject failed"; exit 1; }

echo "[3] screenshot #grondwater under SwiftShader (browser WebGL ok; map ctor still throws)"
pkill -9 -f chrom 2>/dev/null; sleep 3
P=$(mktemp -d); rm -f /tmp/mapfail.png /tmp/mapfail.log
chromium --headless=new --no-sandbox --enable-unsafe-swiftshader --use-gl=angle --use-angle=swiftshader \
  --user-data-dir="$P" --virtual-time-budget=22000 --screenshot=/tmp/mapfail.png \
  --window-size=1400,1500 "http://127.0.0.1:8000/#grondwater" > /tmp/mapfail.log 2>&1
echo "    chromium rc=$?"
if [ -f /tmp/mapfail.png ]; then
  python3 -c "from PIL import Image; im=Image.open('/tmp/mapfail.png'); im.crop((0,int(im.size[1]*0.60),im.size[0],im.size[1])).save('/tmp/mapfail_crop.png'); print('    cropped -> /tmp/mapfail_crop.png ('+str(im.size)+')')"
  echo "[4] PASS criterion: Read /tmp/mapfail_crop.png — projection chart + table present == fallback works"
else
  echo "    NO PNG — browser still blocked in this session too; try a later session."
fi
# trap reverts app.js
