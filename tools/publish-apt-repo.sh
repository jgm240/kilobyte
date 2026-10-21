#!/bin/sh
# Publish the kilobyte-transition packages in out/ as a signed APT repository
# on GitHub Pages (the gh-pages branch): https://jgm240.github.io/kilobyte/apt
#
#   tools/make-transition-deb.sh && tools/publish-apt-repo.sh
#
# Every version ever published stays in the repository. The signing key is
# kept outside the Git repository, in ~/.kilobyte-apt-key (or
# $KILOBYTE_APT_KEY); the first run makes it. Keep a copy of that folder: a
# new key would make every computer that has the repository refuse it.
# Needs Docker and git push access.
set -e
cd "$(dirname "$0")/.."
KEY=${KILOBYTE_APT_KEY:-$HOME/.kilobyte-apt-key}
URL=https://jgm240.github.io/kilobyte/apt
W=out/gh-pages
REMOTE=$(git remote get-url origin)

ls out/kilobyte-transition_*_all.deb >/dev/null 2>&1 || { echo "No package in out/: run tools/make-transition-deb.sh first" >&2; exit 1; }
mkdir -p "$KEY" && chmod 700 "$KEY"

# The gh-pages branch, checked out in out/gh-pages (made the first time).
if [ ! -d "$W/.git" ]; then
    if git ls-remote --exit-code --heads origin gh-pages >/dev/null 2>&1; then
        git clone -q --branch gh-pages "$REMOTE" "$W"
    else
        mkdir -p "$W" && git -C "$W" init -q -b gh-pages && git -C "$W" remote add origin "$REMOTE"
    fi
else
    git -C "$W" pull -q --ff-only origin gh-pages 2>/dev/null || true
fi
mkdir -p "$W/apt"
cp out/kilobyte-transition_*_all.deb "$W/apt/"
: > "$W/.nojekyll"

docker run --rm -v "$PWD/$W/apt:/repo" -v "$KEY:/gpg" -e URL="$URL" debian:trixie bash -c '
    set -e
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq >/dev/null && apt-get install -y -qq --no-install-recommends dpkg-dev apt-utils gnupg >/dev/null 2>&1
    # gpg works on a copy inside the container: its agent needs sockets,
    # which a folder shared from a Mac cannot hold.
    export GNUPGHOME=/tmp/gpg
    mkdir -p -m 700 $GNUPGHOME
    (cd /gpg && find . ! -name "S.*" ! -name . -print0 | cpio -0pdm --quiet $GNUPGHOME) 2>/dev/null ||
        (cd /gpg && tar --exclude="./S.*" -cf - . | tar -C $GNUPGHOME -xf -)
    chmod -R go-rwx $GNUPGHOME
    if ! gpg --batch --list-secret-keys 2>/dev/null | grep -q sec; then
        echo "==> Making the signing key (once)"
        gpg --batch --passphrase "" --quick-gen-key "Kilobyte APT repository <kilobyte@users.noreply.github.com>" ed25519 sign 5y
        gpgconf --kill gpg-agent
        (cd $GNUPGHOME && tar --exclude="./S.*" -cf - .) | tar -C /gpg -xf -
    fi
    cd /repo
    dpkg-scanpackages --multiversion . /dev/null 2>/dev/null > Packages
    gzip -9kf Packages
    apt-ftparchive -o APT::FTPArchive::Release::Origin=Kilobyte -o APT::FTPArchive::Release::Label=Kilobyte \
        -o APT::FTPArchive::Release::Suite=stable -o APT::FTPArchive::Release::Codename=stable \
        -o APT::FTPArchive::Release::Architectures=all \
        -o APT::FTPArchive::Release::Description="Kilobyte for normal Debian, Ubuntu and Raspberry Pi OS" \
        release . > Release
    gpg --batch --yes --clearsign -o InRelease Release
    gpg --batch --yes -abs -o Release.gpg Release
    gpg --batch --yes --export -o kilobyte-archive-keyring.gpg
    gpg --batch --yes --armor --export -o kilobyte-archive-keyring.asc
    printf "Types: deb\nURIs: %s\nSuites: ./\nSigned-By: /usr/share/keyrings/kilobyte-archive-keyring.gpg\n" "$URL" > kilobyte.sources
    chmod -R a+rX /repo
    echo "Packages:"; grep -E "^(Package|Version):" Packages | paste - -
'

v=$(ls "$W"/apt/kilobyte-transition_*_all.deb | sed 's/.*_\(.*\)_all.deb/\1/' | sort -V | tail -n 1)
# The newest package under a name that stays the same, for the one-line
# install (outside apt/, so the repository lists every version once).
cp "$W/apt/kilobyte-transition_${v}_all.deb" "$W/kilobyte-transition.deb"
cat > "$W/index.html" <<HTML
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kilobyte APT repository</title>
<style>
  :root { --bg: #0000aa; --fg: #ffffff; --box: #aaaaaa; --ink: #000000; --hi: #55ffff; }
  body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.5 ui-monospace, Menlo, Consolas, monospace; }
  main { max-width: 52rem; margin: 2rem auto; padding: 0 16px; }
  section { background: var(--box); color: var(--ink); padding: 1rem 1.25rem; margin: 1.25rem 0; box-shadow: 8px 8px 0 #000; }
  h1 { color: var(--hi); font-size: 1.4rem; } h2 { margin-top: 0; font-size: 1.05rem; }
  pre { background: #000; color: #fff; padding: .75rem; overflow-x: auto; white-space: pre; }
  a { color: inherit; }
</style>
</head>
<body>
<main>
<h1>■ Kilobyte APT repository</h1>
<p><b>kilobyte-transition</b> $v adds Kilobyte, the text-mode desktop, to a normal Debian, Ubuntu
or Raspberry Pi OS, next to its own desktop.</p>
<section>
<h2>Install</h2>
<p>One line in a terminal:</p>
<pre>cd /tmp &amp;&amp; wget -q https://jgm240.github.io/kilobyte/kilobyte-transition.deb &amp;&amp; sudo apt install ./kilobyte-transition.deb</pre>
<p>The package sets up this repository too, so updates come with <code>sudo apt upgrade</code>.
Already have the repository? Then <code>sudo apt install kilobyte-transition</code> is enough.</p>
</section>
<section>
<h2>Use</h2>
<pre>kb open             go to Kilobyte
kb close            go back to the desktop
kb autolaunch on    start the computer into Kilobyte
kb autolaunch off   start the computer into the desktop again</pre>
</section>
<p>Kilobyte is free software (GNU GPL 3 or later): <a href="https://github.com/jgm240/kilobyte">github.com/jgm240/kilobyte</a>.
The packages are signed with the key in <a href="apt/kilobyte-archive-keyring.asc">kilobyte-archive-keyring.asc</a>.</p>
</main>
</body>
</html>
HTML
cp "$W/index.html" "$W/apt/index.html"
sed -i '' 's|href="apt/kilobyte-archive-keyring.asc"|href="kilobyte-archive-keyring.asc"|' "$W/apt/index.html" 2>/dev/null ||
    sed -i 's|href="apt/kilobyte-archive-keyring.asc"|href="kilobyte-archive-keyring.asc"|' "$W/apt/index.html"

git -C "$W" add -A
if git -C "$W" diff --cached --quiet; then
    echo "Nothing new to publish."
else
    git -C "$W" commit -q -m "APT repository: kilobyte-transition $v"
    git -C "$W" push -q origin gh-pages
    echo "Published: $URL"
fi
