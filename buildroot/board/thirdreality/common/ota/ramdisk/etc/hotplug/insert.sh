if [ -n "$1" ]; then
  if [ ! -d /media ]; then
    mkdir -p /media
  fi
  
  if [ -b /dev/$11 ]; then
      mount /dev/$11 /media
  elif [ -b /dev/$1 ]; then
      mount /dev/$1 /media
  fi
  
  if [ $? -ne 0 ]; then
    rm -rf /media
  fi
fi
