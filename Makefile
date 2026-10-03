# Asus-helper — установка файлов по стандартным путям.
#   make install DESTDIR="$pkgdir" PREFIX=/usr          — пакет (AUR)
#   install.sh вызывает make с PREFIX=/usr/local и системными каталогами для D-Bus/polkit/udev
#
# Python не компилируется: пакет asushelper кладётся как есть, команды — короткие обёртки.

PREFIX     ?= /usr
SYSCONFDIR ?= /etc
BINDIR     ?= $(PREFIX)/bin
LIBDIR     ?= $(PREFIX)/lib/asus-helper
DATADIR    ?= $(PREFIX)/share
UNITDIR    ?= $(PREFIX)/lib/systemd/system
USERUNITDIR?= $(PREFIX)/lib/systemd/user
UDEVDIR    ?= $(PREFIX)/lib/udev/rules.d
DBUSDIR    ?= $(DATADIR)/dbus-1/system.d
POLKITDIR  ?= $(DATADIR)/polkit-1/actions
AUTOSTARTDIR ?= $(SYSCONFDIR)/xdg/autostart
PYTHON     ?= /usr/bin/python3

COMMANDS = asus-helperd:asushelper.daemon asus-helper:asushelper.app \
           asus-helper-cli:asushelper.cli asus-helper-agent:asushelper.agent

.PHONY: install uninstall test

install:
	install -d "$(DESTDIR)$(LIBDIR)"
	cp -r asushelper "$(DESTDIR)$(LIBDIR)/"
	find "$(DESTDIR)$(LIBDIR)" -name '__pycache__' -prune -exec rm -rf {} +
	chmod -R a+rX "$(DESTDIR)$(LIBDIR)"
	install -d "$(DESTDIR)$(BINDIR)"
	for c in $(COMMANDS); do \
		name=$${c%%:*}; mod=$${c#*:}; \
		printf '#!/bin/sh\n# Asus-helper\nPYTHONPATH=%s exec %s -m %s "$$@"\n' "$(LIBDIR)" "$(PYTHON)" "$$mod" \
			> "$(DESTDIR)$(BINDIR)/$$name"; \
		chmod 755 "$(DESTDIR)$(BINDIR)/$$name"; \
	done
	install -Dm755 data/prime-run "$(DESTDIR)$(BINDIR)/prime-run"
	sed 's|@BINDIR@|$(BINDIR)|' data/asus-helperd.service | install -Dm644 /dev/stdin "$(DESTDIR)$(UNITDIR)/asus-helperd.service"
	install -Dm644 data/asus-helper-kwin.conf "$(DESTDIR)$(USERUNITDIR)/plasma-kwin_wayland.service.d/asus-helper.conf"
	install -Dm644 data/61-asus-helper-igpu.rules "$(DESTDIR)$(UDEVDIR)/61-asus-helper-igpu.rules"
	install -Dm644 data/org.asushelper.Daemon.conf "$(DESTDIR)$(DBUSDIR)/org.asushelper.Daemon.conf"
	install -Dm644 data/org.asushelper.policy "$(DESTDIR)$(POLKITDIR)/org.asushelper.policy"
	install -Dm644 data/asus-helper.desktop "$(DESTDIR)$(DATADIR)/applications/asus-helper.desktop"
	install -Dm644 data/asus-helper-autostart.desktop "$(DESTDIR)$(AUTOSTARTDIR)/asus-helper.desktop"
	install -Dm644 data/icons/asus-helper.svg "$(DESTDIR)$(DATADIR)/icons/hicolor/scalable/apps/asus-helper.svg"
	install -Dm644 README.md "$(DESTDIR)$(DATADIR)/doc/asus-helper/README.md"
	install -Dm644 README.ru.md "$(DESTDIR)$(DATADIR)/doc/asus-helper/README.ru.md"

uninstall:
	rm -rf "$(DESTDIR)$(LIBDIR)" "$(DESTDIR)$(DATADIR)/doc/asus-helper"
	for c in $(COMMANDS); do rm -f "$(DESTDIR)$(BINDIR)/$${c%%:*}"; done
	rm -f "$(DESTDIR)$(BINDIR)/prime-run" \
	      "$(DESTDIR)$(UNITDIR)/asus-helperd.service" \
	      "$(DESTDIR)$(USERUNITDIR)/plasma-kwin_wayland.service.d/asus-helper.conf" \
	      "$(DESTDIR)$(UDEVDIR)/61-asus-helper-igpu.rules" \
	      "$(DESTDIR)$(DBUSDIR)/org.asushelper.Daemon.conf" \
	      "$(DESTDIR)$(POLKITDIR)/org.asushelper.policy" \
	      "$(DESTDIR)$(DATADIR)/applications/asus-helper.desktop" \
	      "$(DESTDIR)$(AUTOSTARTDIR)/asus-helper.desktop" \
	      "$(DESTDIR)$(DATADIR)/icons/hicolor/scalable/apps/asus-helper.svg"
	-rmdir "$(DESTDIR)$(USERUNITDIR)/plasma-kwin_wayland.service.d" 2>/dev/null

test:
	$(PYTHON) -m unittest discover -s tests -t .
