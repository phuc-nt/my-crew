"""Live full-flow scenarios: real model, real search, simulated Telegram wire.

Sibling of `tests/fullflow` and deliberately NOT a replacement for it. The scripted
suite pins contracts — prompt shape, DAG shape, store rows — deterministically and for
free. This suite exists for the one class of defect that suite structurally cannot
catch: the model behaving differently under the real prompt. Repo precedent is
`tests/test_ops_intent_delegation_live.py`, where every offline test stayed green
through a full production outage caused by a tool DESCRIPTION the model stopped finding
persuasive.

So the rule here is: assert only what needs a real model. Contract shape belongs
offline.
"""
