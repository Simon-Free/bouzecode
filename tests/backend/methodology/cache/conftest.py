# [desc] Root pytest conftest re-exporting the fake_anthropic fixture for use across the test suite [/desc]
from tests.backend.cache.fake_anthropic import fake_anthropic  # noqa: F401
