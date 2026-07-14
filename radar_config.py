#!/usr/bin/env python3
"""
Load a per-experiment radar config from a TOML file and merge it over the
built-in default config_dict.

Only the sections mmwcas.mmw_set_config() reads are honored:
  [mimo.profile], [mimo.frame], [mimo.channel]
C-binary-only sections (tx, chirp, system, dataPath, capture, network) and the
top-level devices/radar_enabled keys are ignored, so an existing config/*.toml
file written for the C binary still loads (only its profile/frame are used).

Stdlib only (tomllib, Python 3.11+). Never imports mmwcas — importable and
unit-testable on any host.
"""
import copy
import tomllib

# Sections under [mimo] the Python path programs (mmwcas reads these).
_MERGE_SECTIONS = ('profile', 'frame', 'channel')


def load_and_merge(toml_path, base):
    """
    Read `toml_path`, merge its [mimo.profile]/[mimo.frame]/[mimo.channel]
    sections over a deep copy of `base`, and return the merged config dict.

    `base` is not mutated. Unknown keys inside a honored section, or a
    non-numeric value for a honored key, raise ValueError (typo/type
    protection). A missing file raises FileNotFoundError; malformed TOML raises
    tomllib.TOMLDecodeError.
    """
    with open(toml_path, 'rb') as fh:
        data = tomllib.load(fh)

    merged = copy.deepcopy(base)
    mimo = data.get('mimo', {})

    for section in _MERGE_SECTIONS:
        if section not in mimo:
            continue
        overrides = mimo[section]
        if not isinstance(overrides, dict):
            raise ValueError(
                f'[mimo.{section}] must be a table, got {type(overrides).__name__}')
        valid = merged['mimo'][section]
        unknown = sorted(k for k in overrides if k not in valid)
        if unknown:
            raise ValueError(
                f'Unknown key(s) in [mimo.{section}]: {", ".join(unknown)}. '
                f'Valid keys: {", ".join(sorted(valid))}')
        for key, value in overrides.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f'[mimo.{section}].{key} must be a number, '
                    f'got {type(value).__name__}')
            merged['mimo'][section][key] = value

    return merged
