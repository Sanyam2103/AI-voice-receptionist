from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grooming.vapi import vapi_function_specs


def main() -> None:
    print(json.dumps(vapi_function_specs(), indent=2))


if __name__ == "__main__":
    main()
