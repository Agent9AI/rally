.PHONY: help test check serve dry demo fmt clean

help:
	@echo "make test    run the suite"
	@echo "make check   preflight: pins, binaries, credentials, limits"
	@echo "make dry     exercise the loop with stub agents, no tokens spent"
	@echo "make demo    a full live run on fast models, about 60 seconds"
	@echo "make serve   poll the ingress Worker and run what arrives"
	@echo "make clean   remove run state and caches"

test:
	@python3 -m unittest discover -s tests -v

check:
	@./bin/rally --check

dry:
	@./bin/rally --run "stub exercise" --dry --no-mail --workdir /tmp --max-turns 12

demo:
	@./bin/rally --config config/rally.demo.json --no-mail \
	  --run "Write fizzbuzz.py with a fizzbuzz(n) function returning the FizzBuzz string for n, and test_fizzbuzz.py covering 1, 3, 5 and 15. Must pass python3 -m unittest discover."

serve:
	@./bin/rally --serve

clean:
	@rm -rf runs/*/ __pycache__ src/__pycache__ tests/__pycache__
	@echo "cleaned"
