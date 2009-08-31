pyRoastUI.py: pyRoastUI.ui
	pyuic4 pyRoastUI.ui > pyRoastUI.py

clean:
	rm -f pyRoastUI.py pyRoastUI.pyc *~


