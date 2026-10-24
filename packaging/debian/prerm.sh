#!/bin/sh
set -eu
case "${1:-}" in
    remove|deconfigure)
        /usr/bin/python3 "${DPKG_ROOT:-}/usr/share/thunderbird-closetobackground/tools/policy.py" remove
        ;;
esac
