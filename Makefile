.PHONY: build dist test test-dbus test-packages test-policies test-thunderbird test-gnome install uninstall doctor
build:
	python3 scripts/build.py
dist: build
test:
	node tests/run.mjs
	python3 -m unittest discover -s tests -p 'test_*.py'
test-dbus:
	dbus-run-session -- python3 tests/dbus_integration.py
test-packages:
	python3 tests/package_lifecycle.py
test-policies:
	dbus-run-session -- xvfb-run -a python3 tests/policy_integration.py
test-thunderbird:
	dbus-run-session -- xvfb-run -a python3 tests/thunderbird_integration.py
test-gnome:
	dbus-run-session -- python3 tests/gnome_integration.py
install:
	python3 scripts/install.py
uninstall:
	python3 scripts/install.py --uninstall
doctor:
	/usr/bin/python3 scripts/doctor.py
