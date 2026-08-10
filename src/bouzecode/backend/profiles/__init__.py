# [desc] Re-exports public API for the profiles module: AgentProfile, loaders, merge, and discovery. [/desc]
from bouzecode.backend.profiles.models import AgentProfile
from bouzecode.backend.profiles.loader import load_profiles_from_dir, load_profile_from_path
from bouzecode.backend.profiles.composer import merge_profiles
from bouzecode.backend.profiles.discovery import (
    load_user_profiles, load_all_profiles, profile_search_dirs, user_global_dir,
    load_system_profiles, resolve_agent_profile, builtin_dir,
)

__all__ = [
    "AgentProfile", "load_profiles_from_dir", "load_profile_from_path", "merge_profiles",
    "load_user_profiles", "load_all_profiles", "profile_search_dirs", "user_global_dir",
    "load_system_profiles", "resolve_agent_profile", "builtin_dir",
]
