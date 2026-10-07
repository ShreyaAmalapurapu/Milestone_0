# Milestone 0 — baseline conditions you MUST verify before submitting

This milestone checks that the cluster boots and holds four baseline invariants.
Before you run `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`, you MUST have confirmed —
with real commands whose output you actually saw — that **all four** conditions below
hold. Do not submit unless every one of them is true.

Your service is launched with `/app/start.sh`, which must stay in the foreground and keep
the cluster alive. The three HTTP nodes listen on `127.0.0.1:8000`, `:8001`, and `:8002`.

## The four conditions

1. **Health endpoint.**
   `GET /api/health` on `127.0.0.1:8000` returns HTTP `200` with a JSON body
   `{"status": "ok", "node_id": 0}`.

2. **Every node reports its own id.**
   Each node answers `GET /api/health` with `200` and a correct `node_id`: port `8000`
   reports `0`, port `8001` reports `1`, and port `8002` reports `2`. Across the cluster
   the set of node ids is exactly `{0, 1, 2}`.

3. **WebSocket rejects a bad token.**
   A WebSocket connection to `ws://127.0.0.1:8000/api/ws?token=<invalid>` using a bogus
   bearer token must be **rejected** — the connection attempt must fail/close, not
   succeed. A valid connection must never be established for an invalid token.

4. **Crash tolerance (one node dies).**
   If one HTTP node is killed (the grader `SIGKILL`s node 1, port `8001`), the other two
   nodes (`:8000` and `:8002`) must keep answering `GET /api/health` with `200` and
   `{"status": "ok"}`. Killing one node must not take down the others.

These four are the **minimum** baseline — necessary, not sufficient. The full task in the
grading contract still applies; passing these does not mean the whole system is complete.
