#!/bin/bash
# ELinks with JavaScript (MuJS) and real CSS (NetSurf's libcss and libdom).
# Runs as root in the unpacked Debian source of elinks, before it is built.
# NetSurf's libraries are not in Debian, so they are built here from their
# release tarballs and linked statically into ELinks.
set -euo pipefail

DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
    gperf pkg-config libexpat1-dev libmujs-dev libsqlite3-dev curl ca-certificates >/dev/null

src=$PWD

# No documentation: its tools (dblatex, docbook) pull in all of TeX.
sed -i -E '/^[[:space:]]*,[[:space:]]*(xmlto|docbook-utils|dblatex|asciidoc|doxygen)[[:space:]]*$/d' debian/control
awk 'BEGIN { RS = ""; ORS = "\n\n" } !/^Package: elinks-doc/' debian/control > debian/control.new
mv debian/control.new debian/control
rm -f debian/elinks-doc.* debian/elinks-data.manpages
sed -i 's/^CONF_OPTS= -Dtest=true/CONF_OPTS= -Dtest=false -Ddoc=false -Dapidoc=false -Dhtmldoc=false -Dpdfdoc=false -Dmujs=true -Dlibcss=true/' debian/rules
sed -i 's/ -Dlibcss=false//' debian/rules       # Debian switches it off again further down
sed -i 's/dh_auto_build -- man html pdf txt/dh_auto_build/' debian/rules
grep -q -- '-Dmujs=true' debian/rules

if PKG_CONFIG_PATH=/usr/local/lib/pkgconfig pkg-config --exists 'libdom >= 0.4.2' 'libcss >= 0.9.2'; then
    exit 0       # built already
fi
work=$(mktemp -d)
cd "$work"
base=https://download.netsurf-browser.org/libs/releases
curl -fsSLO "$base/buildsystem-1.10.tar.gz"
for lib in libwapcaplet-0.4.3 libparserutils-0.2.5 libhubbub-0.3.8 libdom-0.4.2 libcss-0.9.2; do
    curl -fsSLO "$base/$lib-src.tar.gz"
done
for f in *.tar.gz; do tar xzf "$f"; done
make -C buildsystem-1.10 install PREFIX=/usr/local >/dev/null
for lib in libwapcaplet-0.4.3 libparserutils-0.2.5 libhubbub-0.3.8 libdom-0.4.2 libcss-0.9.2; do
    sed -i 's/-Werror//g' "$lib/Makefile"      # newer compilers warn about harmless things
    make -C "$lib" install PREFIX=/usr/local COMPONENT_TYPE=lib-static \
        NSSHARED=/usr/local/share/netsurf-buildsystem >/dev/null
done

