from setuptools import find_packages, setup

setup(
    name='q99-utils',
    packages=find_packages(include=['q99_utils']),
    version='0.1.0',
    description='Library of common q99 services',
    author='Q99',
    install_requires=["pydantic", "httpx"],
    tests_require=[],
    test_suite='tests'
)
