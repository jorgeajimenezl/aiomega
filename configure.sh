set -e
cd sdk

echo "Configuring sdk"
sh autogen.sh
./configure --enable-python --with-python3 --without-freeimage

echo "Compiling sdk"
make

echo "Patching sdk generated python files"
patch bindings/python/megaapi_wrap.cpp ../megaapi_wrap.patch
make

# Build python mega sdk package
cd bindings/python
python setup.py build
rm build/lib/mega/test_libmega.py
cp -r build/lib/mega ../../../aiomega/megasdk