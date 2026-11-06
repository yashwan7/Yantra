# FRDM Safety Logic — Host Test Makefile
#
# Usage:
#   make -C firmware/frdm_safety test   # compile and run unit tests
#   make -C firmware/frdm_safety clean

CC      = gcc
CFLAGS  = -Wall -Wextra -std=c11 -g -fsanitize=address,undefined
SRCS    = safety_logic.c test_safety_logic.c
TARGET  = test_safety_logic

.PHONY: test clean

test: $(TARGET)
	./$(TARGET)

$(TARGET): $(SRCS) safety_logic.h hal.h
	$(CC) $(CFLAGS) -o $@ $(SRCS)

clean:
	rm -f $(TARGET)
