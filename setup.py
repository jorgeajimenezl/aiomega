import re, sys
from setuptools import setup, find_packages, Extension

with open("aiomega/__init__.py", "r") as fd:
    version = re.search(
        r'^__version__\s*=\s*[\'"]([^\'"]*)[\'"]', fd.read(), re.MULTILINE
    ).group(1)

# with open("requirements.txt", "r") as file:
#     INSTALL_REQUIRES = file.readlines()

static_libraries = ["mega"]
static_lib_dir = "sdk/src/.libs"
libraries = [
    "z",
    "ssl",
    "crypto",
    "cryptopp",
    "sodium",
    "sqlite3",
    "cares",
    "curl",
    "uv",
    "raw",
    "avcodec",
    "avformat",
    "avutil",
    "swscale",
    "dl",
    "stdc++fs",
    "rt",
]
library_dirs = ["/usr/local/lib"]

if sys.platform == "win32":
    libraries.extend(static_libraries)
    library_dirs.append(static_lib_dir)
    extra_objects = []
else:  # POSIX
    extra_objects = ["{}/lib{}.a".format(static_lib_dir, l) for l in static_libraries]

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
            "Programming Language :: Python",
            "Programming Language :: Python :: 3.7",
            "Programming Language :: Python :: 3.8",
            "Programming Language :: Python :: 3.9",
            "Programming Language :: Python :: 3.10",
        ],
        keywords=["mega", "client", "internet", "download", "async"],
        install_requires=[],
        packages=find_packages(),
        include_package_data=True,
        platforms=["Linux"],
        ext_modules=[
            Extension(
                name="_mega",
                sources=["sdk/bindings/python/megaapi_wrap.cpp"],
                include_dirs=["/usr/local/include", "sdk/include"],
                libraries=libraries,
                library_dirs=library_dirs,
                extra_objects=extra_objects,
                extra_link_args=["-pthread", "-fopenmp"],
            )
        ],
    )
