#!/bin/bash

#!/bin/bash

set -e

if [ $# -lt 1 ]; then
    echo "Usage: $0 package_name"
    exit 1
fi

OPEN_BR=buildroot
AML_BR=br-aml

cd $OPEN_BR > /dev/null

mkdir -p OSS/{arch,board,boot,package}
mkdir -p OSS/support/{scripts,dependencies,download}
d=$1

if [ -e package/$d ]; then
    git mv package/$d OSS/package/
fi
echo "ln -srf ../$AML_BR/package/$d package/"
ln -srf ../$AML_BR/package/$d package/

cd - > /dev/null
