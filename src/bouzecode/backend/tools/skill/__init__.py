# [desc] Package init that exports skill loading, execution, and builtin registration utilities. [/desc]
"""skill package — reusable prompt templates (skills)."""
from .loader import (  # noqa: F401
    SkillDef,
    load_skills,
    find_skill,
    substitute_arguments,
    register_builtin_skill,
    _parse_skill_file,
    _parse_list_field,
)


# Importing builtin registers the built-in skills
from . import builtin as _builtin  # noqa: F401
