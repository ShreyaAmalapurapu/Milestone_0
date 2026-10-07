#!/bin/sh
set -eu
mkdir -p /app
pids=""
cleanup() {
  for f in /app/node_8000.pid /app/node_8001.pid /app/node_8002.pid; do
    if [ -f "$f" ]; then kill "$(cat "$f")" 2>/dev/null || true; fi
  done
  exit 0
}
trap cleanup INT TERM
start_node() {
  port="$1"
  PORT="$port" python3 /app/app.py >>"/app/node_${port}.log" 2>&1 &
  pid=$!
  echo "$pid" >"/app/node_${port}.pid"
}
for port in 8000 8001 8002; do start_node "$port"; done
PORT=6667 python3 /app/irc.py >>/app/irc.log 2>&1 &
echo $! >/app/irc.pid
while :; do
  for port in 8000 8001 8002; do
    file="/app/node_${port}.pid"
    if [ ! -f "$file" ] || ! kill -0 "$(cat "$file")" 2>/dev/null; then
      start_node "$port"
    fi
  done
  sleep 1
done
