"""Full-flow test harness: chat transports are shells — tests inject synthetic
mentions at the real intake seam and run the ENTIRE product pipeline in-process
(intake → ops intent → decompose → confirm → tick → steps → review → clarify →
delivery → mirror), with only two boundaries doubled: the Telegram HTTP call
(`telegram_write.api_call`) and the LLM rung (`LlmClient.complete`).
Every hop is traced to a per-scenario JSONL file for root-cause analysis.
"""
