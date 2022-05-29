# Python Async Mega Client
<!-- ![PyPI](https://img.shields.io/pypi/v/aiomega)
![Downloads](https://img.shields.io/pypi/dm/aiomega)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/aiomega) -->

A asynchronous [Mega](https://mega.nz/) client that use `asyncio`. This package wraps the official [Mega SDK](https://mega.nz/#sdk)

<!-- ## Installation
We periodically publish source code and wheels [on PyPI](https://pypi.python.org/pypi/aiomega).
```bash
$ pip install aiomega
```

For install the most updated version:
```bash
$ git clone https://github.com/jorgeajimenezl/aiomega.git
$ cd aiomega
$ pip install -e .
``` -->
## Build from source
### Dependencies
+ cURL (`libcurl4-openssl-dev`, `libcurl-devel`), compiled with `--enable-ssl`
+ c-ares (`libc-ares-dev`, `libcares-devel`, `c-ares-devel`)
+ OpenSSL (`libssl-dev`, `openssl-devel`)
+ Crypto++ (`libcrypto++-dev`, `libcryptopp-devel`)
+ zlib (`zlib1g-dev`, `zlib-devel`)
+ pthread

### Build
To build this package from source open the terminal and write:

```shell
$ git clone https://github.com/jorgeajimenezl/aiomega.git
$ cd aiomega
$ sh configure.sh
```

Then, to install it write `pip install -e .`

## Getting started
```python
from aiomega import Mega
import asyncio

async def main():
    async with Mega() as client:
        await client.login(email='juan@cabilla.com', password='cabilla')

        async def progress(c, t, s):
            print(f"{c} bytes / {t} bytes. Speed: {s} bytes/sec")

        await client.download_file('/file', 
                                    '/path/to/file',
                                    progress=progress)

asyncio.run(main())
```

## License
[MIT License](./LICENSE)

## Author
This program was deverloped by Jorge Alejandro Jiménez Luna <<jorgeajimenezl17@gmail.com>>