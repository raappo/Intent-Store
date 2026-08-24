"""
setup.py — allows installing Intent-Store as a package with the
`intent-store` CLI entry point.
"""
from setuptools import setup, find_packages

setup(
    name="intent-store",
    version="0.1.0",
    description="Semantic storage intelligence for Linux — explainable archival recommendations",
    author="Intent-Store Team",
    python_requires=">=3.10",
    py_modules=["cli", "scanner", "profiler", "scorer", "reasoner"],
    install_requires=[
        "click>=8.0",
        "rich>=13.0",
        "sentence-transformers>=2.2",
        "requests>=2.28",
        "numpy>=1.24",
        "tabulate>=0.9",
    ],
    entry_points={
        "console_scripts": [
            "intent-store=cli:cli",
        ]
    },
)
