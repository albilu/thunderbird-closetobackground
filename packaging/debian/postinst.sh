#!/bin/sh
set -eu
case "${1:-}" in
    configure|abort-remove|abort-deconfigure)
        /usr/bin/python3 "${DPKG_ROOT:-}/usr/share/thunderbird-closetobackground/tools/policy.py" configure
        ;;
esac
