set -e
export PYTHONWARNINGS="ignore"
cd sdk

echo "Configuring sdk"
sh autogen.sh
./configure --enable-python --with-python3 --without-freeimage --disable-examples \
            --without-sqlite --disable-shared --enable-static --without-libuv \
            --without-libraw --without-ffmpeg

echo "Compiling sdk"
make

echo "Patching sdk generated python files"
patch bindings/python/megaapi_wrap.cpp ../megaapi_wrap.patch
patch bindings/python/mega.py ../mega.patch
make

echo "Build python mega sdk package"
cd bindings/python
python setup.py build

echo "Coping library"
rm build/lib/mega/test_libmega.py
cp -r build/lib/mega ../../../aiomega/megasdk