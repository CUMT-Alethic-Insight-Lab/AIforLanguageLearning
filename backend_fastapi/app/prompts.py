from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, Template

from .runtime_config import get_prompt_override

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def render_prompt(template_name: str, **kwargs: object) -> str:
    override = (get_prompt_override(template_name) or "").strip()
    if override:
        tpl = Template(override)
        return tpl.render(**kwargs)

    env = Environment(
        loader=FileSystemLoader(str(_PROMPTS_DIR)),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    tpl = env.get_template(template_name)
    return tpl.render(**kwargs)
