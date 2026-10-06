#!/bin/bash
# Build AR488 for Arduino Nano (ATmega328P @16 MHz) without arduino-cli.
# usage: build.sh <srcdir> <outdir> [extra -D flags]
set -e
SRC=$1; OUT=$2; shift 2
CORE=/home/claude/ArduinoCore-avr
mkdir -p $OUT
CF="-mmcu=atmega328p -DF_CPU=16000000L -DARDUINO=10819 -DARDUINO_AVR_NANO -DARDUINO_ARCH_AVR -Os -g -flto -fuse-linker-plugin -ffunction-sections -fdata-sections -w $*"
INC="-I$CORE/cores/arduino -I$CORE/variants/eightanaloginputs -I$CORE/libraries/EEPROM/src -I$CORE/libraries/SPI/src -I$CORE/libraries/SoftwareSerial/src -I$SRC"
OBJS=""
for f in $CORE/cores/arduino/*.c; do o=$OUT/core_$(basename $f).o; avr-gcc $CF -std=gnu11 $INC -c $f -o $o; OBJS="$OBJS $o"; done
for f in $CORE/cores/arduino/*.cpp $CORE/libraries/SoftwareSerial/src/*.cpp; do o=$OUT/core_$(basename $f).o; avr-g++ $CF -std=gnu++11 -fpermissive -fno-exceptions -fno-threadsafe-statics $INC -c $f -o $o; OBJS="$OBJS $o"; done
python3 /home/claude/ar488build/protos.py $SRC/AR488.ino $OUT/AR488.cpp
sed -i '1i #include <Arduino.h>' $OUT/AR488.cpp
for f in $OUT/AR488.cpp $SRC/*.cpp; do o=$OUT/$(basename $f).o; avr-g++ $CF -std=gnu++11 -fpermissive -fno-exceptions -fno-threadsafe-statics $INC -c $f -o $o; OBJS="$OBJS $o"; done
avr-gcc -mmcu=atmega328p -Os -g -flto -fuse-linker-plugin -Wl,--gc-sections -o $OUT/AR488.elf $OBJS -lm
avr-objcopy -O ihex -R .eeprom $OUT/AR488.elf $OUT/AR488.hex
avr-size -C --mcu=atmega328p $OUT/AR488.elf
