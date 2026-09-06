"""Compatibility entry point for the approved TYMRO icon generator.

The canonical generator is generate-icons.mjs. Keeping this wrapper prevents
the former placeholder generator from overwriting approved brand assets.
"""
from pathlib import Path
import subprocess


if __name__ == "__main__":
    script = Path(__file__).with_name("generate-icons.mjs")
    subprocess.run(["node", str(script)], check=True)
