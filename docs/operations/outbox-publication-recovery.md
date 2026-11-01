# Outbox publication recovery

The Meeting Service dispatch command remains one-shot. It does not poll or
schedule itself. Ordinary publication is limited to three claims. If the
publication outcome is unknown, the service records the safe
`publication_outcome_unknown` marker before calling the AI Service and may make
one additional claim using `ambiguity_recovery_count`, independently of the
ordinary `attempt_count`.

An unknown outcome includes a lost response, an unexpected failure after the
publisher boundary begins, or a process crash while a marked claim is leased.
After the ambiguity recovery claim also ends with an unknown outcome, or its
lease expires, the event is retained as `pending` with
`ambiguous_recovery_exhausted`. The ordinary claim path will not select it.
Known permanent failures and ordinary exhausted failures also require operator
attention.

## Operator handling

The repository does not currently provide an application-level requeue
command or authenticated operator endpoint. Stopped events therefore require
an authorized, audited operator procedure established by operations. Direct
SQL requeue is unsupported: the event’s historical claim count, lease state,
failure category, payload identity, and job identity must not be changed
without a reviewed recovery procedure and an audit record.

The stable outbox event ID and job ID are retained across recovery claims and
broker redelivery. Consumers should deduplicate by those stable identities;
delivery is at-least-once and duplicates remain possible. This mechanism does
not provide exactly-once execution.
