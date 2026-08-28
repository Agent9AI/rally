.PHONY: help test check serve dry fmt clean

help:
	@echo "make test    run the suite"
	@echo "make check   preflight: pins, binaries, credentials, limits"
	@echo "make dry     exercise the loop with stub agents, no tokens spent"
	@echo "make serve   poll the ingress Worker and run what arrives"
	@echo "make clean   remove run state and caches"

test:
	@python3 -m unittest discover -s tests -v

check:
	@./bin/rally --check

dry:
	@./bin/rally --run "stub exercise" --dry --no-mail --workdir /tmp --max-turns 12

serve:
	@./bin/rally --serve

clean:
	@rm -rf runs/*/ __pycache__ src/__pycache__ tests/__pycache__
	@echo "cleaned"
