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
	@${CC} ${FLAGS} mimo.c
	@${CC} ${CFLAGS} mmwave *.o -lpthread -lm
	@rm -f *.o

clean:
	@rm -f *.o
	@rm -f mmwave
	@rm -rf build
	@rm -f mmwcas.c

build-cython:
	@${PYTHON} setup.py build_ext --inplace

build: clean all build-cython

install: all build-cython
	@echo "Installing mmwave to /usr/local/bin..."
	@sudo cp mmwave /usr/local/bin/
	@sudo chmod +x /usr/local/bin/mmwave
	@echo "Installation complete."
