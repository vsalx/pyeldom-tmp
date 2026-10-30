import os
from setuptools import setup, find_packages

# Allow Home Assistant to install this test fork directly from a pinned archive.
# Preserve PACKAGE_VERSION for the upstream release workflow.
version = os.environ.get("PACKAGE_VERSION", "2.1.1+convector.energy.1")

# Setup the package.
setup(
    name="pyeldom",
    version=version,
    description="A Python client for the Eldom API",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Daniel Gospodinow",
    author_email="danielgospodinow@gmail.com",
    url="https://github.com/qbaware/pyeldom",
    packages=find_packages(),
    install_requires=[
        "aiohttp>=3.9.0",
        "PyJWT>=2.10.1",
        "pycryptodome>=3.23.0",
        "requests",
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.6",
)

