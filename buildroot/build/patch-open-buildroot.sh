#!/bin/bash

set -e

OPEN_BR=buildroot
AML_BR=br-aml

test -f $OPEN_BR/.amlogic_patched && echo "Amlogic Patches are applied, exiting ... " && exit 0

echo "Begin patch open buildroot"

pushd $OPEN_BR > /dev/null
printf "..."
if [ -d ../$AML_BR/patches/ ]; then
    patches_list=`ls ../$AML_BR/patches/`
fi
for d in $patches_list; do
    git am --whitespace=nowarn ../$AML_BR/patches/$d 
done

mkdir -p OSS/{arch,board,boot,package}
mkdir -p OSS/support/{scripts,dependencies,download}
# print dot to indicate progress 
printf "..."

# process in alphabeta sequence
# ====process directory====
# only Config.in.arm is modified in arch dir
git mv arch/Config.in.arm OSS/arch
ln -srf ../$AML_BR/arch/Config.in.arm arch/

# only uboot dir is modified
git mv boot/uboot OSS/boot
ln -srf ../$AML_BR/boot/uboot boot/
printf "..."
ln -srf ../$AML_BR/board/amlogic board/
ln -srf ../$AML_BR/board/neucore board/

ln -srf ../$AML_BR/build

git mv configs OSS/
ln -srf ../$AML_BR/configs

git mv fs OSS/
ln -srf ../$AML_BR/fs

git mv linux OSS/
ln -srf ../$AML_BR/linux


git mv system OSS/
ln -srf ../$AML_BR/system

git mv toolchain OSS/
ln -srf ../$AML_BR/toolchain

printf "..."
# ====process file====
# top dir file
git mv Config.in OSS/
ln -srf ../$AML_BR/Config.in

git mv Config.in.legacy OSS/
ln -srf ../$AML_BR/Config.in.legacy

git mv Makefile OSS/
ln -srf ../$AML_BR/Makefile
printf "..."
# process suppport dir file
git mv support/scripts/check-bin-arch OSS/support/scripts/
git mv support/dependencies/check-host-cmake.mk OSS/support/dependencies/
git mv support/download/wget  OSS/support/download/
ln -srf ../$AML_BR/support/scripts/check-bin-arch support/scripts/
ln -srf ../$AML_BR/support/dependencies/check-host-cmake.mk support/dependencies/
ln -srf ../$AML_BR/support/download/wget support/download/

printf "..."
# ====process package====
# get all the amlogic modified offical packages list
packages_list=`ls ../$AML_BR/package`
# skip gstreamer1 and x11r7 direcotory, they have many subdir to process
#packages_list=${packages_list/gstreamer1/}


for d in $packages_list; do
    # echo "rm -rf $BUILDROOT_DIR/package/$d"
    if [ -e package/$d ]; then
        git mv package/$d OSS/package/
    fi
    ln -srf ../$AML_BR/package/$d package/
    printf "."
done
# process gstreamer1 
# gstreamer1_packages_list=`ls ../$AML_BR/package/gstreamer1`
# mkdir -p OSS/package/gstreamer1
# for d in $gstreamer1_packages_list; do
#     # echo "rm -rf $BUILDROOT_DIR/package/$d"
#     if [ -e package/gstreamer1/$d ]; then
#         git mv package/gstreamer1/$d OSS/package/gstreamer1
#     fi
#     ln -srf ../$AML_BR/package/gstreamer1/$d package/gstreamer1
# done
echo ""
echo "Patch open buildroot done"

touch .amlogic_patched

popd > /dev/null
