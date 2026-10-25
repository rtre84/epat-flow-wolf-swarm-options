"""Prompt loader: prompts are config bricks in swarm/prompts/*.md, 1:1 portable
to any other framework. Never inline prompts in code."""

from importlib import resources


def load(name: str) -> str:
    return resources.files("swarm.prompts").joinpath(f"{name}.md").read_text()
