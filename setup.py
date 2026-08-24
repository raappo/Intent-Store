from setuptools import setup, find_packages

setup(
    name="intent-store",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "click",
        "rich",
        "requests",
        "sentence-transformers",
        "numpy",
        "scikit-learn"
    ],
    entry_points={
        "console_scripts": [
            "intent-store=cli:cli",
        ],
    },
)
