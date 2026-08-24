#!/usr/bin/env python3
"""Setuptools metadata for Hermes CoAgent — pip-installable package definition."""

from pathlib import Path

from setuptools import setup


ROOT = Path(__file__).resolve().parent


def read_requirements():
    requirements_file = ROOT / "requirements.txt"
    if not requirements_file.exists():
        return []
    requirements = []
    for line in requirements_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        requirements.append(line)
    return requirements


def root_modules():
    excluded = {"setup", "test_compile", "test_ocr", "test_tray"}
    return [
        path.stem
        for path in sorted(ROOT.glob("*.py"))
        if path.stem not in excluded
    ]


setup(
    name="hermes-coagent",
    version=(ROOT / "VERSION").read_text(encoding="utf-8").strip() if (ROOT / "VERSION").exists() else "0.0.0",
    description="Local Windows desktop automation REST API server",
    long_description=(ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").exists() else "",
    long_description_content_type="text/markdown",
    author="Hermes CoAgent contributors",
    url="https://github.com/Predator04/Hermes-CoAgent",
    py_modules=root_modules(),
    install_requires=read_requirements(),
    python_requires=">=3.11",
    entry_points={
        "console_scripts": [
            "hermes-coagent = hermes_coagent:main",
            "coagent = coagent_cli:main",
        ],
    },
    include_package_data=True,
    license="MIT",
)
