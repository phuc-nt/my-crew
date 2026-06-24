"""SSE stream generator for a run (v2 M2-P6).

Drains a run's event queue and yields SSE frames: one `node` event per graph node
(projected through the `summarize_node` PII firewall), then exactly one `terminal`
event, then stops — the stream does NOT block waiting for a Lớp B resume (the operator
resumes via `mpm agent resume`; the terminal `interrupted` event carries the thread_id).

Single-drain model (INTENTIONAL M2 scope — the plan's per-subscriber fan-out is
deferred): exactly ONE live stream drains a still-running run's queue. A second
concurrent attach to a running run is REFUSED (409) rather than left to block forever
competing for the single terminal sentinel. A late attach AFTER the run already
finished always gets the cached terminal immediately (the handle caches `terminal`),
so a fast run that completes before the client connects is never missed. Multi-watcher
fan-out is a P7/later concern if the dashboard needs concurrent viewers.
"""

from __future__ import annotations

import asyncio

from src.server.graph_runner import Terminal
from src.server.run_manager import RunHandle, StreamBusyError
from src.server.sse_events import node_event, terminal_event


async def stream_run(handle: RunHandle):
    """Yield SSE `{"data": ...}` frames for the run until (and including) its terminal.

    If the run already reached its terminal before this attaches, emit the cached
    terminal once and stop (late-watcher path). Otherwise claim the single live drain
    (a second concurrent attach to a still-running run → StreamBusyError) and drain
    the queue, releasing the claim when done so a later replay can attach.
    """
    # Late attach: run already finished AND its queue is drained → replay the terminal.
    if handle.status == "terminal" and handle.queue.empty() and handle.terminal is not None:
        yield {"data": terminal_event(handle.terminal)}
        return

    # Claim the single live drain. A second concurrent stream on a running run is
    # refused rather than left to block forever on the one-consumer queue.
    if handle.attached:
        raise StreamBusyError(handle.run_id)
    handle.attached = True
    try:
        while True:
            item = await handle.queue.get()
            if isinstance(item, Terminal):
                yield {"data": terminal_event(item)}
                return
            # item is a raw astream chunk {node: delta} — project + emit per node.
            for node, delta in item.items():
                yield {"data": node_event(node, delta if isinstance(delta, dict) else {})}
            await asyncio.sleep(0)  # cooperative yield between frames
    finally:
        handle.attached = False
