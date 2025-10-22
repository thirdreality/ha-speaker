#!/bin/bash

ALL_LINE=""
while read LINE
do
  if [[ $LINE != \#*  &&  $LINE != "" ]]; then
    ALL_LINE="$ALL_LINE"" ""$LINE"
  fi
done < $1
echo $ALL_LINE

