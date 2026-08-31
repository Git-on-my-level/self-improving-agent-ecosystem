# Controlled outcome evaluator

This example demonstrates an evaluator that rejects incomplete attribution,
semantic emptiness, and undersized samples before computing a difference in
success rates against a contemporaneous baseline.

```bash
python3 score.py fixtures/valid
python3 score.py fixtures/reward-hack
python3 score.py fixtures/insufficient-sample
python3 score.py fixtures/unsigned-identity
```

It is a contract example, not a universal business metric.
