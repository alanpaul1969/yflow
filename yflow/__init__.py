"""
yflow — The Makefile for AI workflows.

1 dependency, zero daemons, provider-agnostic.
"""

from yflow.engine import (
    build_workflow_prompt,
    classify_task,
    execute_workflow,
    get_available_templates,
    instantiate_template,
    list_workflows,
    load_template,
    load_workflow,
    resolve_execution_order,
    validate_workflow,
)

__version__ = "0.5.1"
__all__ = [
    "build_workflow_prompt",
    "classify_task",
    "execute_workflow",
    "get_available_templates",
    "instantiate_template",
    "list_workflows",
    "load_template",
    "load_workflow",
    "resolve_execution_order",
    "validate_workflow",
]
