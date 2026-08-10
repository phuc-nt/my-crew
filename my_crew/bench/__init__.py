"""Benchmark harness for measuring task-completion speed.

v77 traded a model-driven react loop for a code-paced pipeline on the claim that it
finishes the same brief far faster. That claim was first established by hand, one
Telegram task at a time, which is not a thing anyone can re-run six months from now
when a prompt change quietly costs back the win.

This package turns the measurement into something repeatable:

- `task_metrics` reads what actually happened from the live store, so a run measured
  here is the same run the CEO received — not a re-enactment.
- `pipeline_bench` runs the sprint pipeline against a scripted model, which removes
  network variance entirely and measures the part v77 actually changed: how many
  searches and model calls the CODE decides to make.
"""
