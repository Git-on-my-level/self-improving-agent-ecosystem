.PHONY: check test validate shellcheck

check: validate test shellcheck

validate:
	python3 scripts/validate.py --allow-placeholders templates
	python3 -m compileall -q scripts examples tests

test:
	python3 -m unittest discover -s tests -v

shellcheck:
	sh -n scripts/install-avo-lite.sh
	sh -n scripts/init-ecosystem.sh
	find templates/stubs -type f -name '*.sh' -exec sh -n {} \;
	@if command -v shellcheck >/dev/null 2>&1; then shellcheck scripts/*.sh templates/stubs/*/*.sh; fi
