.PHONY: help test cloud-test cloud-eval infra-check release-check check smoke serve dry demo fmt clean

help:
	@echo "make test    run the suite"
	@echo "make cloud-test  validate the Google coordinator"
	@echo "make cloud-eval  run the live ADK scorecard and enforce its result"
	@echo "make infra-check validate production Terraform"
	@echo "make release-check run every deterministic release gate; never deploys"
	@echo "make check   preflight: pins, binaries, credentials, limits"
	@echo "make dry     exercise the loop with stub agents, no tokens spent"
	@echo "make smoke   preflight AND make every configured worker actually answer"
	@echo "make demo    a full live run on fast models, about 60 seconds"
	@echo "make serve   poll the ingress Worker and run what arrives"
	@echo "make clean   remove run state and caches"

test:
	@python3 -m unittest discover -s tests -v

cloud-test:
	@uv run --project cloud ruff check cloud
	@uv run --project cloud pytest cloud/tests -q

cloud-eval:
	@cd cloud && agents-cli eval run \
	  --evalset tests/eval/evalsets/rally_intake.evalset.json \
	  --config tests/eval/eval_config.json
	@uv run --project cloud python cloud/scripts/assert_eval_gate.py

infra-check:
	@terraform -chdir=cloud/infra fmt -check -recursive
	@terraform -chdir=cloud/infra init -backend=false
	@terraform -chdir=cloud/infra validate

release-check: test cloud-test infra-check
	@node --check src/worker/index.js
	@cd src/worker && wrangler deploy --dry-run --outdir /tmp/rally-worker-build
	@git diff --check
	@git diff --cached --check
	@echo "release gates passed: 105 automated tests, Terraform, Worker bundle, syntax, whitespace"

check:
	@./bin/rally --check

dry:
	@./bin/rally --run "stub exercise" --dry --no-mail --workdir /tmp --max-turns 12

smoke:
	@./bin/rally --check --smoke --config config/rally.demo.json

demo:
	@./bin/rally --config config/rally.demo.json --no-mail \
	  --run "Create a polished, self-contained HTML presentation for an executive AI strategy meeting covering the most consequential Google AI product launches and major releases from 2025-08-29 through 2026-08-29. Use primary Google sources only. For every included launch, show the release date, what changed, who it matters to, a concrete business use, and a source URL. Include an executive synthesis, a coverage appendix grouped by product family, and a machine-readable claim ledger. Do not guess: unsupported or disputed claims must be omitted or labeled. Add automated checks for required sections, dates, source URLs, and local presentation loading. Every factual claim and the finished presentation must be independently verified."

serve:
	@./bin/rally --serve

clean:
	@rm -rf runs/*/ __pycache__ src/__pycache__ tests/__pycache__
	@echo "cleaned"
