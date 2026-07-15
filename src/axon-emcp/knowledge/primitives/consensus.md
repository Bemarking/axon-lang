---
name: consensus
summary: "Multi-candidate consensus — FAILS CLOSED (axon-T940, §111): refused at check time; no votes, no aggregation, no candidates in the old placeholder."
category: cognition
top_level: false
since: pre-§111 (introduction unrecorded)
grammar: |
  consensus { <body> }   # REFUSED at check time (axon-T940)
---

# `consensus`

`consensus` was sold as multi-candidate voting. **It fails closed**
(§111): the checker refuses it with `axon-T940` — no votes, no
aggregation, no candidates ever existed behind the old placeholder.

Same posture as `deliberate`: refusal over silent no-op. Use
`ensemble` for the consensus machinery that IS real (quorum over
observations, §112).

## See also

- `axon://primitives/ensemble` — real quorum, real tie-breaking.
