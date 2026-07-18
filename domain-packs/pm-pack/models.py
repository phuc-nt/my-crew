"""pm-pack entity ↔ generic model mapping (v3 M5 S6).

The generic `Task` (in `my_crew/tools/models.py`) is the cross-domain shape every pack maps
onto. PM's source entity is a Jira `Issue`; this module maps `Issue → Task` (and back),
proving the generic model covers PM without losing any field. PM's analyzers still run on
`Issue` (byte-identical), so this mapping is the *abstraction proof* M6 relies on: HR maps
a headcount row → `Task` the same way, and the generic shape is validated to be sufficient.

A round-trip `task_to_issue(issue_to_task(x)) == x` holds, so nothing is lost in the map.
"""

from __future__ import annotations

from my_crew.tools.models import Issue, Task


def issue_to_task(issue: Issue) -> Task:
    """Map a Jira Issue onto the generic Task (kind="issue"). No information lost."""
    return Task(
        id=issue.key,
        title=issue.summary,
        status=issue.status,
        assignee=issue.assignee,
        due_date=issue.due_date,
        labels=issue.labels,
        flagged=issue.flagged,
        kind="issue",
    )


def task_to_issue(task: Task) -> Issue:
    """Inverse map: a Task carrying PM issue semantics back to an Issue."""
    return Issue(
        key=task.id,
        summary=task.title,
        status=task.status,
        assignee=task.assignee,
        due_date=task.due_date,
        labels=task.labels,
        flagged=task.flagged,
    )
