PY ?= python3

.PHONY: test reset-demo check

test:
	$(PY) -m pytest -q

check: test
	@echo "Tools OK. Now run the Day-1 checks in DEMO_SCRIPT.md."

# Restores the clean demo state. Deletes every cases/OC-* folder. Use only before a rehearsal or recording.
reset-demo:
	@echo "This restores vendors/acme.json from seed/ and DELETES cases/OC-*. Ctrl-C within 5s to abort."
	@sleep 5
	cp seed/acme.json vendors/acme.json
	rm -rf cases/OC-*
	@echo "Demo state reset."

# Automated build targets for test and verification
