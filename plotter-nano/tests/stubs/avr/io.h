// Host stand-in for <avr/io.h>: the ATmega328P registers the sketch uses, as
// plain bytes the test sets and reads (test_nano.cpp).
#pragma once
#include <stdint.h>

#define _BV(b) (1 << (b))

volatile uint8_t PINB, PINC, PIND, DDRB, DDRC, DDRD, PORTB, PORTC, PORTD, SREG;
volatile uint8_t TCCR2A, TCCR2B, OCR2A, TIMSK2, PCMSK0, PCIFR, PCICR;

#define WGM21  1
#define CS22   2
#define OCIE2A 1
#define PCINT2 2
#define PCIF0  0
#define PCIE0  0
