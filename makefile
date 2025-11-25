# Compiler
CC = gcc
CFLAGS = -o
FLAGS = -c -w -Wno-error=incompatible-pointer-types -Wno-error=int-conversion

ODIR = output
PYTHON ?= python3
# Root directory
ROOT_DIR = ti

# MMWavelink
MMWLINK_IDIR = ${ROOT_DIR}/mmwavelink/src

mmwlink:
	@${CC} ${FLAGS} ${MMWLINK_IDIR}/*.c


# MMWave Ethernet
MMWETH_IDIR = ${ROOT_DIR}/ethernet/src

mmwethernet:
	@${CC} ${FLAGS} ${MMWETH_IDIR}/*.c


mmwave: mmwlink mmwethernet
	@${CC} ${FLAGS} ${ROOT_DIR}/mmwave/*.c

cliopt:
	@${CC} ${FLAGS} opt/*.c

tomlconfig:
	@${CC} ${FLAGS} toml/*.c

# Build all
all: mmwlink mmwethernet mmwave cliopt tomlconfig
	@${CC} ${FLAGS} *.c
	@${CC} ${CFLAGS} mmwave *.o -lpthread -lm
	@rm -f *.o

clean:
	@rm -f *.o
	@rm -f mmwave
	@rm -rf build
	@rm -f mmwcas.c

build-cython:
	@echo "Skipping Cython build (not required for CLI tool)"

build: clean all

install: clean all
	@cp mmwave /usr/local/bin/
	@chmod +x /usr/local/bin/mmwave
	@echo "mmwave installed successfully to /usr/local/bin/"
	@$(MAKE) clean
