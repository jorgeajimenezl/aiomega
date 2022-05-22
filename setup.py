import re
from setuptools import setup, find_packages

with open("aiomega/__init__.py", "r") as fd:
    version = re.search(
        r'^__version__\s*=\s*[\'"]([^\'"]*)[\'"]', fd.read(), re.MULTILINE
    ).group(1)

# with open("requirements.txt", "r") as file:
#     INSTALL_REQUIRES = file.readlines()

with open("README.md") as readme:
    setup(
        name="aiomega",
        version=version,
        description="A Python Async Mega.nz client",
        long_description=readme.read(),
        long_description_content_type="text/markdown",
        license="MIT License",
        author="Jorge Alejandro Jimenez Luna",
        author_email="jorgeajimenezl17@gmail.com",
        url="https://github.com/jorgeajimenezl/aiomega",
        classifiers=[
            "Intended Audience :: Developers",
            "License :: OSI Approved :: MIT License",
            "Operating System :: OS Independent",
            "Programming Language :: Python",
            "Programming Language :: Python :: 3.7",
            "Programming Language :: Python :: 3.8",
            "Programming Language :: Python :: 3.9",
            "Programming Language :: Python :: 3.10",
        ],
        keywords=["mega", "client", "internet", "download", "async"],
        install_requires=[],
        packages=find_packages(),
        package_data={
            "megasdk": ["megasdk/libmega.so", "megasdk/_mega.so"],
        },
        include_package_data=True
    )
