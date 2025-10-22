#!/bin/bash

PRE_DEFINE=""
for y_config in `cat $1 | grep "^CONFIG_.*=y" | sed 's/=y//'`;
do
  PRE_DEFINE="$PRE_DEFINE"" -D"${y_config}
done

for m_config in `cat $1 | grep "^CONFIG_.*=m" | sed 's/=m//'`;
do
  PRE_DEFINE="$PRE_DEFINE"" -D"${m_config}_MODULE
done
echo $PRE_DEFINE

