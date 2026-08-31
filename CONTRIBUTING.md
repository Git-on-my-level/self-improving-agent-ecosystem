# Contributing

Prefer small changes that strengthen a reusable contract or prove a real
failure class. Avoid accumulating rules for hypothetical edge cases.

Before submitting a change:

1. Explain the concrete failure or missing decision the change addresses.
2. Keep private endpoints, prompts, identities, credentials, and production
   payloads out of fixtures and documentation.
3. Add a behavioral fixture when changing evaluator, event, promotion, or
   validation semantics.
4. Run:

   ```bash
   python3 scripts/validate.py --allow-placeholders templates
   python3 -m unittest discover -s tests -v
   python3 /path/to/skill-creator/scripts/quick_validate.py \
     skills/self-improving-ecosystem
   ```

5. State whether the change affects correctness, quality measurement,
   authority, promotion, rollback, or public behavior.

Do not weaken a hard gate merely to keep a loop moving. A stalled loop is safer
than a confidently wrong one.
