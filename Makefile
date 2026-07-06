PYTHON ?= python

.PHONY: doctor test compile

doctor:
	pogo doctor

test:
	$(PYTHON) -m pytest

compile:
	$(PYTHON) -m py_compile pogo_auto/*.py
