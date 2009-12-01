all: pyRoastUI.py RawMeterReader

pyRoastUI.py: pyRoastUI.ui
	pyuic4 pyRoastUI.ui > pyRoastUI.py

RawMeterReader: RawMeterReader.c
	cc -Wall -o RawMeterReader RawMeterReader.c -lusb-1.0

clean:
	rm -f pyRoastUI.py pyRoastUI.pyc *~ RawMeterReader
